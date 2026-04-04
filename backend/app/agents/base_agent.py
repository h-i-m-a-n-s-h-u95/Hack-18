from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
import asyncio
import logging
from datetime import datetime
from enum import Enum

from app.config.settings import settings
from app.messaging.redis_client import RedisClient, RedisChannels


# ==================== ENUMS & PROTOCOLS ====================

class AgentType(str, Enum):
    """Agent type identifiers"""
    ORCHESTRATOR = "orchestrator"
    WEATHER = "weather"
    EVENTS = "events"
    MAPS = "maps"
    BUDGET = "budget"
    ITINERARY = "itinerary"


class AgentStatus(str, Enum):
    """Agent execution status"""
    IDLE = "idle"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


class StreamingUpdateType(str, Enum):
    """Types of streaming updates"""
    STARTED = "started"
    PROGRESS = "progress"
    COMPLETED = "completed"
    ERROR = "error"
    INFO = "info"


# ==================== BASE AGENT ====================

class BaseAgent(ABC):
    """
    Base class for all travel planning agents with Redis pub/sub support
    
    Features:
    - Redis pub/sub communication
    - LangChain/LangGraph integration
    - Streaming updates
    - Tool execution
    - Error handling
    """
    
    def __init__(
        self,
        name: str,
        role: str,
        expertise: str,
        agent_type: AgentType,
        redis_client: RedisClient,
        tools: Optional[List] = None,
        gemini_api_key: str = None,
        model_name: str = "gemini-2.0-flash-exp"
    ):
        self.name = name
        self.role = role
        self.expertise = expertise
        self.agent_type = agent_type
        self.redis_client = redis_client
        self.tools = tools or []
        
        self.logger = logging.getLogger(f"agent.{name.lower().replace(' ', '_')}")
        
        # Initialize Gemini LLM
        api_key = gemini_api_key or getattr(settings, 'google_api_key', None)
        self.llm = ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=api_key,
            temperature=getattr(settings, 'temperature', 0.7),
            max_output_tokens=getattr(settings, 'max_tokens', 4096)
        )
        
        # Bind tools to LLM if provided
        if self.tools:
            self.llm = self.llm.bind_tools(self.tools)
        
        self.start_time = datetime.utcnow()
        self._subscription_id: Optional[str] = None
        self._is_running = False
    
    # ==================== ABSTRACT METHODS ====================
    
    @abstractmethod
    async def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle incoming request and return response data
        
        Args:
            request: Request dictionary with payload and metadata
            
        Returns:
            Response data dictionary
        """
        pass
    
    @abstractmethod
    def get_system_prompt(self) -> str:
        """Get the system prompt for this agent"""
        pass
    
    # ==================== AGENT LIFECYCLE ====================
    
    async def start(self):
        """Start the agent and subscribe to Redis channel"""
        if self._is_running:
            self.logger.warning(f"{self.name} is already running")
            return
        
        # Ensure Redis is connected
        await self.redis_client.connect()
        
        # Subscribe to request channel
        request_channel = RedisChannels.get_request_channel(self.agent_type.value)
        
        self._subscription_id = await self.redis_client.subscribe(
            channel=request_channel,
            handler=self._handle_incoming_request,
            error_handler=self._handle_subscription_error
        )
        
        self._is_running = True
        self.logger.info(f"🚀 {self.name} started - Listening on {request_channel}")
    
    async def stop(self):
        """Stop the agent and unsubscribe from Redis"""
        if not self._is_running:
            return
        
        if self._subscription_id:
            await self.redis_client.unsubscribe(self._subscription_id)
            self._subscription_id = None
        
        self._is_running = False
        self.logger.info(f"🛑 {self.name} stopped")
    
    # ==================== REQUEST HANDLING ====================
    
    async def _handle_incoming_request(self, request_data: Dict[str, Any]):
        """Handle incoming request from Redis pub/sub"""
        request_id = request_data.get("request_id", "unknown")
        session_id = request_data.get("session_id", "unknown")
        
        self.logger.info(f"📨 Received request {request_id} for session {session_id}")
        
        start_time = datetime.utcnow()
        
        try:
            # Send started update
            await self._send_streaming_update(
                session_id=session_id,
                update_type=StreamingUpdateType.STARTED,
                message=f"{self.name} started processing",
                progress_percent=0
            )
            
            # Process the request using agent-specific logic
            response_data = await self.handle_request(request_data)
            
            # Calculate processing time
            processing_time = (datetime.utcnow() - start_time).total_seconds() * 1000
            
            # Send completed update
            await self._send_streaming_update(
                session_id=session_id,
                update_type=StreamingUpdateType.COMPLETED,
                message=f"{self.name} completed successfully",
                progress_percent=100
            )
            
            # Create success response
            response = {
                "request_id": request_id,
                "session_id": session_id,
                "agent": self.agent_type.value,
                "success": True,
                "data": response_data,
                "processing_time_ms": int(processing_time),
                "timestamp": datetime.utcnow().isoformat()
            }
            
            # Publish response
            await self._publish_response(session_id, response)
            
            self.logger.info(f"✅ Request {request_id} completed in {processing_time:.0f}ms")
            
        except Exception as e:
            self.logger.error(f"❌ Request {request_id} failed: {str(e)}", exc_info=True)
            
            # Send error update
            await self._send_streaming_update(
                session_id=session_id,
                update_type=StreamingUpdateType.ERROR,
                message=f"{self.name} encountered an error: {str(e)}"
            )
            
            # Create error response
            processing_time = (datetime.utcnow() - start_time).total_seconds() * 1000
            response = {
                "request_id": request_id,
                "session_id": session_id,
                "agent": self.agent_type.value,
                "success": False,
                "error": str(e),
                "processing_time_ms": int(processing_time),
                "timestamp": datetime.utcnow().isoformat()
            }
            
            # Publish error response
            await self._publish_response(session_id, response)
    
    async def _handle_subscription_error(self, error: Exception):
        """Handle subscription errors"""
        self.logger.error(f"Subscription error: {str(error)}", exc_info=True)
    
    # ==================== REDIS COMMUNICATION ====================
    
    async def _publish_response(self, session_id: str, response: Dict[str, Any]):
        """Publish response to Redis response channel"""
        response_channel = RedisChannels.get_response_channel(
            self.agent_type.value,
            session_id
        )
        
        await self.redis_client.publish(response_channel, response)
        self.logger.debug(f"📤 Published response to {response_channel}")
    
    async def _send_streaming_update(
        self,
        session_id: str,
        update_type: StreamingUpdateType,
        message: str,
        progress_percent: Optional[int] = None,
        data: Optional[Dict[str, Any]] = None
    ):
        """Send streaming update via Redis"""
        try:
            update = {
                "session_id": session_id,
                "agent": self.agent_type.value,
                "agent_name": self.name,
                "type": update_type.value,
                "message": message,
                "progress_percent": progress_percent,
                "data": data,
                "timestamp": datetime.utcnow().isoformat()
            }
            
            channel = RedisChannels.get_streaming_channel(session_id)
            await self.redis_client.publish(channel, update)
            
            self.logger.debug(f"📊 Streaming update: {update_type.value} - {message}")
            
        except Exception as e:
            self.logger.warning(f"Failed to send streaming update: {str(e)}")
    
    # ==================== LLM INTERACTION ====================
    
    async def invoke_llm(
        self,
        system_prompt: str,
        user_input: str,
        session_id: Optional[str] = None,
        stream_progress: bool = True
    ) -> str:
        """
        Invoke the LLM with streaming support
        
        Args:
            system_prompt: System prompt for the LLM
            user_input: User input/query
            session_id: Optional session ID for streaming updates
            stream_progress: Whether to send streaming updates
            
        Returns:
            LLM response content
        """
        try:
            if stream_progress and session_id:
                await self._send_streaming_update(
                    session_id=session_id,
                    update_type=StreamingUpdateType.PROGRESS,
                    message=f"{self.name} is analyzing...",
                    progress_percent=50
                )
            
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_input)
            ]
            
            response = await self.llm.ainvoke(messages)
            
            # Check if response has tool calls
            if hasattr(response, 'tool_calls') and response.tool_calls:
                # Handle tool execution if needed
                return await self._execute_tools_and_get_response(
                    messages,
                    response,
                    session_id
                )
            
            return response.content
            
        except Exception as e:
            self.logger.error(f"LLM invocation failed: {str(e)}")
            raise
    
    async def _execute_tools_and_get_response(
        self,
        messages: List,
        response,
        session_id: Optional[str]
    ) -> str:
        """Execute tools and get final response"""
        # This would integrate with LangGraph for complex tool execution
        # For now, return the response content
        return response.content if hasattr(response, 'content') else str(response)
    
    # ==================== UTILITY METHODS ====================
    
    def log_action(self, action: str, details: Optional[str] = None):
        """Log agent actions"""
        log_msg = f"{self.name} - {action}"
        if details:
            log_msg += f": {details}"
        self.logger.info(log_msg)
    
    def log_error(self, error: str, details: Optional[str] = None):
        """Log agent errors"""
        log_msg = f"{self.name} - ERROR: {error}"
        if details:
            log_msg += f": {details}"
        self.logger.error(log_msg)
    
    def get_health_status(self) -> Dict[str, Any]:
        """Get agent health status"""
        uptime = (datetime.utcnow() - self.start_time).total_seconds()
        
        return {
            "agent": self.name,
            "agent_type": self.agent_type.value,
            "status": "healthy" if self._is_running else "stopped",
            "uptime_seconds": int(uptime),
            "is_running": self._is_running,
            "has_subscription": self._subscription_id is not None,
            "version": "1.0.0"
        }