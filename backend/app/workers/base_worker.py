import asyncio
import signal
from typing import Optional, Type
from datetime import datetime
import logging

from app.messaging.redis_client import RedisClient, RedisChannels
from app.messaging.protocols import MCPMessage, AgentType, MessageAction
from app.agents.base_agent import BaseAgent
from app.config.settings import settings


logger = logging.getLogger(__name__)


class BaseWorker:
    """
    Base worker class for agent workers
    
    Each agent runs as an independent worker that:
    - Subscribes to its request channel
    - Processes incoming requests
    - Publishes responses to session-specific channels
    - Handles graceful shutdown
    """
    
    def __init__(
        self,
        agent: BaseAgent,
        agent_type: AgentType,
        redis_client: RedisClient
    ):
        self.agent = agent
        self.agent_type = agent_type
        self.redis_client = redis_client
        self.logger = logging.getLogger(f"worker.{agent_type.value}")
        
        self._running = False
        self._shutdown_event = asyncio.Event()
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._request_count = 0
        self._error_count = 0
        self._start_time = datetime.utcnow()
        
        # Setup graceful shutdown
        signal.signal(signal.SIGINT, self._handle_shutdown_signal)
        signal.signal(signal.SIGTERM, self._handle_shutdown_signal)
    
    def _handle_shutdown_signal(self, signum, frame):
        """Handle shutdown signals"""
        self.logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self._shutdown_event.set()
    
    async def start(self):
        """Start the worker"""
        self.logger.info(f"🚀 Starting {self.agent_type.value} worker...")
        
        try:
            # Connect to Redis
            await self.redis_client.connect()
            
            # Start heartbeat
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            
            # Subscribe to request channel
            request_channel = RedisChannels.get_request_channel(self.agent_type.value)
            
            self.logger.info(f"📡 Subscribing to channel: {request_channel}")
            
            await self.redis_client.subscribe(
                channel=request_channel,
                handler=self._handle_request,
                error_handler=self._handle_error
            )
            
            self._running = True
            self.logger.info(f"✅ {self.agent_type.value} worker is running")
            
            # Wait for shutdown signal
            await self._shutdown_event.wait()
            
        except Exception as e:
            self.logger.error(f"❌ Worker failed to start: {str(e)}")
            raise
        finally:
            await self.stop()
    
    async def stop(self):
        """Stop the worker gracefully"""
        if not self._running:
            return
        
        self.logger.info(f"⏹️ Stopping {self.agent_type.value} worker...")
        
        self._running = False
        
        # Cancel heartbeat
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        
        # Disconnect Redis
        await self.redis_client.disconnect()
        
        # Log final stats
        uptime = (datetime.utcnow() - self._start_time).total_seconds()
        self.logger.info(
            f"📊 Final Stats - Requests: {self._request_count}, "
            f"Errors: {self._error_count}, Uptime: {uptime:.0f}s"
        )
        
        self.logger.info(f"✅ {self.agent_type.value} worker stopped")
    
    async def _handle_request(self, message_data: dict):
        """Handle incoming request message"""
        try:
            self._request_count += 1
        
            # Parse message based on agent type
            request = self._parse_request(message_data)
        
            if request.action != MessageAction.REQUEST:
                self.logger.warning(f"Ignoring non-request message: {request.action}")
                return
        
            self.logger.info(
                f"📥 Received request - Session: {request.session_id}, "
                f"Request: {request.request_id}"
            )
        
            # Process request with timeout
            timeout = message_data.get("metadata", {}).get("timeout_ms", 30000) / 1000
        
            try:
                # Convert Pydantic model to dict before passing to agent
                agent_response = await asyncio.wait_for(
                    self.agent.handle_request(request.dict()),
                    timeout=timeout
                )   
            
             # Wrap agent's dict response in proper MCP response message
                from app.messaging.protocols import MessageFactory
                response = MessageFactory.create_response(
                    request=request,
                    agent=self.agent_type,
                    success=True,
                    data=agent_response  # Agent's dict response goes in data field
                )
            
            except asyncio.TimeoutError:
                self.logger.error(f"Request timeout after {timeout}s")
                from app.messaging.protocols import MessageFactory
                response = MessageFactory.create_response(
                request=request,
                agent=self.agent_type,
                success=False,
                error=f"Request timeout after {timeout}s"
                )
            except Exception as e:
                self.logger.error(f"Agent error: {str(e)}", exc_info=True)
                from app.messaging.protocols import MessageFactory
                response = MessageFactory.create_response(
                    request=request,
                    agent=self.agent_type,
                    success=False,
                    error=str(e)
                )
        
            # Publish response to session-specific channel
            response_channel = RedisChannels.get_response_channel(
                self.agent_type.value,
                request.session_id
            )
        
            # Now response is a Pydantic model, so .dict() works
            await self.redis_client.publish(response_channel, response.dict())
        
            self.logger.info(
                f"📤 Sent response - Session: {request.session_id}, "
                f"Success: {response.success}"
            )
        
        except Exception as e:
            self._error_count += 1
            self.logger.error(f"Failed to handle request: {str(e)}", exc_info=True)
    async def _handle_error(self, error: Exception):
        """Handle subscription errors"""
        self._error_count += 1
        self.logger.error(f"Subscription error: {str(error)}")
    
    def _parse_request(self, message_data: dict) -> MCPMessage:
        """Parse incoming message to appropriate request type"""
        from app.messaging.protocols import (
            WeatherRequest, EventsRequest, MapsRequest,
            BudgetRequest, ItineraryRequest
        )
        
        request_types = {
            AgentType.WEATHER: WeatherRequest,
            AgentType.EVENTS: EventsRequest,
            AgentType.MAPS: MapsRequest,
            AgentType.BUDGET: BudgetRequest,
            AgentType.ITINERARY: ItineraryRequest
        }
        
        request_class = request_types.get(self.agent_type)
        if not request_class:
            raise ValueError(f"Unknown agent type: {self.agent_type}")
        
        return request_class(**message_data)
    
    async def _heartbeat_loop(self):
        """Send periodic heartbeat messages"""
        try:
            while self._running:
                await asyncio.sleep(settings.worker_heartbeat_interval)
                
                try:
                    from app.messaging.protocols import MessageFactory
                    
                    uptime = (datetime.utcnow() - self._start_time).total_seconds()
                    
                    health_msg = MessageFactory.create_health_check(
                        agent=self.agent_type,
                        status="healthy",
                        uptime_seconds=int(uptime),
                        version="1.0.0",
                        metadata={
                            "requests_processed": self._request_count,
                            "errors": self._error_count
                        }
                    )
                    
                    await self.redis_client.publish(
                        RedisChannels.HEALTH_CHECK,
                        health_msg.dict()
                    )
                    
                    self.logger.debug(f"💓 Heartbeat sent - Uptime: {uptime:.0f}s")
                    
                except Exception as e:
                    self.logger.error(f"Heartbeat failed: {str(e)}")
                    
        except asyncio.CancelledError:
            self.logger.debug("Heartbeat loop cancelled")
    
    def get_stats(self) -> dict:
        """Get worker statistics"""
        uptime = (datetime.utcnow() - self._start_time).total_seconds()
        
        return {
            "agent_type": self.agent_type.value,
            "running": self._running,
            "uptime_seconds": int(uptime),
            "requests_processed": self._request_count,
            "errors": self._error_count,
            "error_rate": self._error_count / max(self._request_count, 1)
        }


# ==================== WORKER RUNNER ====================

async def run_worker(agent: BaseAgent, agent_type: AgentType):
    """
    Run a worker with the given agent
    
    Usage:
        agent = WeatherAgent(...)
        asyncio.run(run_worker(agent, AgentType.WEATHER))
    """
    from app.messaging.redis_client import get_redis_client
    
    redis_client = get_redis_client()
    worker = BaseWorker(agent, agent_type, redis_client)
    
    try:
        await worker.start()
    except KeyboardInterrupt:
        logger.info("Worker interrupted by user")
    except Exception as e:
        logger.error(f"Worker crashed: {str(e)}", exc_info=True)
        raise