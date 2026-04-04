
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.schema import HumanMessage, SystemMessage
from app.config.settings import settings
from app.core.state import TravelState
from app.messaging.redis_client import RedisClient, RedisChannels
from app.messaging.protocols import (
    MCPMessage, AgentResponse, MessageFactory, 
    AgentType, StreamingUpdate
)
import logging
from datetime import datetime
import asyncio

class BaseAgent(ABC):
    """Enhanced base class for all travel planning agents with Redis/MCP support"""

    
    def __init__(
        self, 
        name: str, 
        role: str, 
        expertise: str,
        agent_type: AgentType,
        redis_client: Optional[RedisClient] = None
    ):
        self.name = name
        self.role = role
        self.expertise = expertise
        self.agent_type = agent_type
        self.logger = logging.getLogger(f"agent.{name.lower()}")
        self.redis_client = redis_client
        
        # Initialize the language model
        self.llm = ChatGoogleGenerativeAI(
            model=settings.model_name,
            google_api_key=settings.google_api_key,
            temperature=settings.temperature,
            max_output_tokens=settings.max_tokens
        )
    
    @abstractmethod
    async def process(self, state: TravelState) -> TravelState:
        """Process the travel state and return updated state"""
        pass
    
    @abstractmethod
    def get_system_prompt(self) -> str:
        """Get the system prompt for this agent"""
        pass
    

    @abstractmethod
    async def handle_request(self, request: MCPMessage) -> Dict[str, Any]:
        """
        Handle MCP request and return data
        
        This is the NEW method which agents implement for MCP pattern.
        Should return the data dictionary to be sent in response.
        """
        pass
    
    # ==================== MCP MESSAGE HANDLING ====================
    
    async def process_mcp_request(self, request: MCPMessage) -> AgentResponse:
        """
        Process MCP request and return MCP response
        
        This is the main entry point for worker pattern.
        """
        start_time = datetime.utcnow()
        
        try:
            self.log_action("Processing request", f"Request ID: {request.request_id}")
            
            # Send streaming update: started
            await self._send_streaming_update(
                request.session_id,
                "started",
                f"{self.name} started processing"
            )
            
            # Call the agent-specific handler
            data = await self.handle_request(request)
            
            # Calculate processing time
            processing_time = (datetime.utcnow() - start_time).total_seconds() * 1000
            
            # Send streaming update: completed
            await self._send_streaming_update(
                request.session_id,
                "completed",
                f"{self.name} completed successfully",
                progress_percent=100
            )
            
            # Create success response
            response = MessageFactory.create_response(
                request=request,
                agent=self.agent_type,
                success=True,
                data=data,
                processing_time_ms=int(processing_time)
            )
            
            self.log_action("Request completed", f"Time: {processing_time:.0f}ms")
            return response
            
        except Exception as e:
            self.log_error("Request failed", str(e))
            
            # Send streaming update: error
            await self._send_streaming_update(
                request.session_id,
                "error",
                f"{self.name} encountered an error: {str(e)}"
            )
            
            # Create error response
            processing_time = (datetime.utcnow() - start_time).total_seconds() * 1000
            response = MessageFactory.create_response(
                request=request,
                agent=self.agent_type,
                success=False,
                error=str(e),
                processing_time_ms=int(processing_time)
            )
            
            return response
    
    async def _send_streaming_update(
        self,
        session_id: str,
        update_type: str,
        message: str,
        progress_percent: Optional[int] = None,
        data: Optional[Dict[str, Any]] = None
    ):
        """Send streaming update via Redis"""
        if not self.redis_client or not settings.streaming_enabled:
            return
        
        try:
            update = MessageFactory.create_streaming_update(
                session_id=session_id,
                agent=self.agent_type,
                update_type=update_type,
                message=message,
                progress_percent=progress_percent,
                data=data
            )
            
            channel = RedisChannels.get_streaming_channel(session_id)
            await self.redis_client.publish(channel, update.dict())
            
        except Exception as e:
            self.logger.warning(f"Failed to send streaming update: {str(e)}")
    
    # ==================== LLM INTERACTION ====================
    def create_messages(self, system_prompt: str, user_input: str):
        """Create message list for the LLM"""
        return [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_input)
        ]
    
    async def invoke_llm(self, system_prompt: str, user_input: str) -> str:
        """Invoke the language model with system and user prompts"""
        try:
            messages = self.create_messages(system_prompt, user_input)
            response = await self.llm.ainvoke(messages)
            return response.content
        except Exception as e:
            self.logger.error(f"LLM invocation failed: {str(e)}")
            raise e

# ==================== LOGGING ====================
    
    
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

    # ==================== STATE HELPERS ====================
    
    
    def add_message_to_state(self, state: TravelState, message: str):
        """Add a message to the state"""
        state["messages"].append(f"[{self.name}] {message}")
    
    def add_error_to_state(self, state: TravelState, error: str):
        """Add an error to the state"""
        state["errors"].append(f"[{self.name}] {error}")
        self.log_error(error)
    
    def format_location_context(self, state: TravelState) -> str:
        """Format location context for prompts"""
        return f"""
        Origin: {state['origin']}
        Destination: {state['destination']}
        Travel Dates: {', '.join(state['travel_dates'])}
        Number of Travelers: {state['travelers_count']}
        Budget Range: {state.get('budget_range', 'Not specified')}
        """
    
    def should_process(self, state: TravelState) -> bool:
        """Determine if this agent should process based on state"""
        return True  # Default implementation, override as needed
    
    # ==================== HEALTH CHECK ====================
    
    def get_health_status(self) -> Dict[str, Any]:
        """Get agent health status"""
        uptime = (datetime.utcnow() - self.start_time).total_seconds()
        
        return {
            "agent": self.name,
            "status": "healthy",
            "uptime_seconds": int(uptime),
            "agent_type": self.agent_type.value,
            "version": "1.0.0"
        }