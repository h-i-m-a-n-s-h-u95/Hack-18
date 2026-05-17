from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from langchain_groq import ChatGroq
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
    ORCHESTRATOR = "orchestrator"
    WEATHER      = "weather"
    EVENTS       = "events"
    MAPS         = "maps"
    BUDGET       = "budget"
    ITINERARY    = "itinerary"


class AgentStatus(str, Enum):
    IDLE       = "idle"
    PROCESSING = "processing"
    COMPLETED  = "completed"
    FAILED     = "failed"
    TIMEOUT    = "timeout"


class StreamingUpdateType(str, Enum):
    STARTED   = "started"
    PROGRESS  = "progress"
    COMPLETED = "completed"
    ERROR     = "error"
    INFO      = "info"


# ==================== BASE AGENT ====================

class BaseAgent(ABC):
    """
    Base class for all travel planning agents with Redis pub/sub support.

    Fixes applied vs original:
      1. self.groq_api_key is now stored on the instance so subclasses
         (e.g. ItineraryAgent) can reference it without AttributeError.
      2. self.model_name is stored so subclasses can read the model name.
      3. LLM is created WITHOUT binding tools at init time; tools are bound
         lazily in invoke_llm so subclasses that override tools don't break.
    """

    def __init__(
        self,
        name: str,
        role: str,
        expertise: str,
        agent_type: AgentType,
        redis_client: RedisClient,
        tools: Optional[List] = None,
        groq_api_key: str = None,
        model_name: str = "llama-3.3-70b-versatile",
    ):
        self.name        = name
        self.role        = role
        self.expertise   = expertise
        self.agent_type  = agent_type
        self.redis_client = redis_client
        self.tools       = tools or []

        # FIX 1: store groq_api_key and model_name on the instance
        # so subclasses can access them via self.groq_api_key / self.model_name
        self.groq_api_key = groq_api_key or getattr(settings, "groq_api_key", None)
        self.model_name   = model_name or getattr(settings, "model_name", "llama-3.3-70b-versatile")

        self.logger = logging.getLogger(f"agent.{name.lower().replace(' ', '_')}")

        # FIX 2: create base LLM without binding tools here.
        # Binding is done in invoke_llm so subclasses that set self.tools
        # after super().__init__() still get the right tools bound.
        self.llm = ChatGroq(
            model=self.model_name,
            api_key=self.groq_api_key,
            temperature=getattr(settings, "temperature", 0.7),
        )

        # FIX 3: bind tools only if provided at construction time,
        # stored separately so invoke_llm can rebind if needed.
        self._llm_with_tools = self.llm.bind_tools(self.tools) if self.tools else self.llm

        self.start_time = datetime.utcnow()
        self._subscription_id: Optional[str] = None
        self._is_running = False

    # ==================== ABSTRACT METHODS ====================

    @abstractmethod
    async def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        pass

    @abstractmethod
    def get_system_prompt(self) -> str:
        pass

    # ==================== AGENT LIFECYCLE ====================

    async def start(self):
        if self._is_running:
            self.logger.warning(f"{self.name} is already running")
            return

        await self.redis_client.connect()
        request_channel = RedisChannels.get_request_channel(self.agent_type.value)

        self._subscription_id = await self.redis_client.subscribe(
            channel=request_channel,
            handler=self._handle_incoming_request,
            error_handler=self._handle_subscription_error,
        )

        self._is_running = True
        self.logger.info(f"🚀 {self.name} started — listening on {request_channel}")

    async def stop(self):
        if not self._is_running:
            return
        if self._subscription_id:
            await self.redis_client.unsubscribe(self._subscription_id)
            self._subscription_id = None
        self._is_running = False
        self.logger.info(f"🛑 {self.name} stopped")

    # ==================== REQUEST HANDLING ====================

    async def _handle_incoming_request(self, request_data: Dict[str, Any]):
        request_id = request_data.get("request_id", "unknown")
        session_id = request_data.get("session_id", "unknown")
        self.logger.info(f"📨 Received request {request_id} for session {session_id}")
        start_time = datetime.utcnow()

        try:
            await self._send_streaming_update(
                session_id=session_id,
                update_type=StreamingUpdateType.STARTED,
                message=f"{self.name} started processing",
                progress_percent=0,
            )

            response_data = await self.handle_request(request_data)
            processing_time = (datetime.utcnow() - start_time).total_seconds() * 1000

            await self._send_streaming_update(
                session_id=session_id,
                update_type=StreamingUpdateType.COMPLETED,
                message=f"{self.name} completed successfully",
                progress_percent=100,
            )

            response = {
                "request_id":        request_id,
                "session_id":        session_id,
                "agent":             self.agent_type.value,
                "success":           True,
                "data":              response_data,
                "processing_time_ms": int(processing_time),
                "timestamp":         datetime.utcnow().isoformat(),
            }
            await self._publish_response(session_id, response)
            self.logger.info(f"✅ Request {request_id} completed in {processing_time:.0f}ms")

        except Exception as e:
            self.logger.error(f"❌ Request {request_id} failed: {str(e)}", exc_info=True)
            await self._send_streaming_update(
                session_id=session_id,
                update_type=StreamingUpdateType.ERROR,
                message=f"{self.name} encountered an error: {str(e)}",
            )
            processing_time = (datetime.utcnow() - start_time).total_seconds() * 1000
            response = {
                "request_id":        request_id,
                "session_id":        session_id,
                "agent":             self.agent_type.value,
                "success":           False,
                "error":             str(e),
                "processing_time_ms": int(processing_time),
                "timestamp":         datetime.utcnow().isoformat(),
            }
            await self._publish_response(session_id, response)

    async def _handle_subscription_error(self, error: Exception):
        self.logger.error(f"Subscription error: {str(error)}", exc_info=True)

    # ==================== REDIS COMMUNICATION ====================

    async def _publish_response(self, session_id: str, response: Dict[str, Any]):
        response_channel = RedisChannels.get_response_channel(
            self.agent_type.value, session_id
        )
        await self.redis_client.publish(response_channel, response)
        self.logger.debug(f"📤 Published response to {response_channel}")

    async def _send_streaming_update(
        self,
        session_id: str,
        update_type: StreamingUpdateType,
        message: str,
        progress_percent: Optional[int] = None,
        data: Optional[Dict[str, Any]] = None,
    ):
        try:
            update = {
                "session_id":       session_id,
                "agent":            self.agent_type.value,
                "agent_name":       self.name,
                "type":             update_type.value,
                "message":          message,
                "progress_percent": progress_percent,
                "data":             data,
                "timestamp":        datetime.utcnow().isoformat(),
            }
            channel = RedisChannels.get_streaming_channel(session_id)
            await self.redis_client.publish(channel, update)
            self.logger.debug(f"📊 Streaming update: {update_type.value} — {message}")
        except Exception as e:
            self.logger.warning(f"Failed to send streaming update: {str(e)}")

    # ==================== LLM INTERACTION ====================

    async def invoke_llm(
        self,
        system_prompt: str,
        user_input: str,
        session_id: Optional[str] = None,
        stream_progress: bool = True,
        use_tools: bool = False,          # set True in subclasses that need tools
    ) -> str:
        """
        Invoke the LLM.

        Args:
            system_prompt:  System prompt for this call.
            user_input:     User query / constructed prompt.
            session_id:     Used to send streaming progress updates.
            stream_progress: Whether to emit a progress update mid-call.
            use_tools:      If True, uses the tool-bound LLM variant.
                            Subclasses that need tool calls should pass True.
        """
        try:
            if stream_progress and session_id:
                await self._send_streaming_update(
                    session_id=session_id,
                    update_type=StreamingUpdateType.PROGRESS,
                    message=f"{self.name} is analysing…",
                    progress_percent=50,
                )

            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_input),
            ]

            # Choose plain or tool-bound LLM
            llm = self._llm_with_tools if (use_tools and self.tools) else self.llm
            response = await llm.ainvoke(messages)

            if hasattr(response, "tool_calls") and response.tool_calls:
                return await self._execute_tools_and_get_response(
                    messages, response, session_id
                )

            return response.content

        except Exception as e:
            self.logger.error(f"LLM invocation failed: {str(e)}")
            raise

    async def _execute_tools_and_get_response(
        self,
        messages: List,
        response: Any,
        session_id: Optional[str],
    ) -> str:
        """Execute tools and get final response (override in subclasses for full tool loops)."""
        return response.content if hasattr(response, "content") else str(response)

    # ==================== UTILITY ====================

    def log_action(self, action: str, details: Optional[str] = None):
        msg = f"{self.name} — {action}"
        if details:
            msg += f": {details}"
        self.logger.info(msg)

    def log_error(self, error: str, details: Optional[str] = None):
        msg = f"{self.name} — ERROR: {error}"
        if details:
            msg += f": {details}"
        self.logger.error(msg)

    def get_health_status(self) -> Dict[str, Any]:
        uptime = (datetime.utcnow() - self.start_time).total_seconds()
        return {
            "agent":          self.name,
            "agent_type":     self.agent_type.value,
            "status":         "healthy" if self._is_running else "stopped",
            "uptime_seconds": int(uptime),
            "is_running":     self._is_running,
            "has_subscription": self._subscription_id is not None,
            "version":        "1.0.0",
        }