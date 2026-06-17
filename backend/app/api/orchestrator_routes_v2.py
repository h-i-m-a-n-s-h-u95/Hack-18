"""
FastAPI Route for Orchestrator Agent with Memory Support
Handles user travel queries and orchestrates multi-agent workflow with WebSocket streaming
"""

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import asyncio
import json
import uuid
import logging
from datetime import datetime

from app.agents.orchestrator_agent import OrchestratorAgent
from app.messaging.redis_client import get_redis_client, RedisChannels
from app.config.settings import settings

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/api/v2/orchestrator", tags=["orchestrator-v2"])

# Global orchestrator instance (initialized on startup)
_orchestrator: Optional[OrchestratorAgent] = None


# ==================== REQUEST/RESPONSE MODELS ====================

class TravelQueryRequest(BaseModel):
    """Request model for travel queries with memory support"""
    query: str = Field(..., description="Natural language travel query", min_length=3)
    session_id: Optional[str] = Field(None, description="Session ID for conversation continuity")
    user_id: Optional[str] = Field(None, description="Optional user ID")
    force_new_session: bool = Field(False, description="Force create new session ignoring existing memory")
    
    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "query": "Plan a 3-day trip to Agra from Delhi for 2 people in July with a moderate budget",
                    "session_id": None  # New conversation
                },
                {
                    "query": "Change my budget to $2000",
                    "session_id": "session_abc123"  # Continue conversation
                },
                {
                    "query": "Add the Taj Mahal to my itinerary",
                    "session_id": "session_abc123"  # Modify existing plan
                }
            ]
        }


class TravelPlanResponse(BaseModel):
    """Response model for travel plan with memory context"""
    session_id: str
    status: str
    is_follow_up: bool
    update_type: Optional[str]
    destination: Optional[str]
    travel_dates: List[str]
    weather: Optional[Dict[str, Any]]
    events: Optional[Dict[str, Any]]
    maps: Optional[Dict[str, Any]]
    budget: Optional[Dict[str, Any]]
    itinerary: Optional[Dict[str, Any]]
    messages: List[str]
    errors: List[str]
    agent_statuses: Dict[str, str]
    conversation_turn: int  # NEW: Track conversation turns


class SessionMemoryResponse(BaseModel):
    """Response model for session memory"""
    session_id: str
    exists: bool
    destination: Optional[str]
    travel_dates: List[str]
    travelers_count: Optional[int]
    budget_range: Optional[str]
    has_itinerary: bool
    has_budget_data: bool
    conversation_turns: int
    last_updated: str
    expires_in_hours: Optional[float]


class SessionStatusResponse(BaseModel):
    """Response model for session status"""
    session_id: str
    status: str
    progress_percent: int
    current_agent: Optional[str]
    completed_agents: List[str]
    pending_agents: List[str]
    is_follow_up: bool


class ConversationHistoryResponse(BaseModel):
    """Response model for conversation history"""
    session_id: str
    conversation_history: List[Dict[str, Any]]
    total_turns: int


# ==================== STARTUP/SHUTDOWN ====================

async def init_orchestrator():
    """Initialize orchestrator on startup"""
    global _orchestrator
    try:
        redis_client = get_redis_client()
        await redis_client.connect()
        
        _orchestrator = OrchestratorAgent(
            redis_client=redis_client,
            groq_api_key=settings.groq_api_key,
            model_name=settings.model_name
        )
        logger.info("✅ Orchestrator initialized successfully with memory support")
    except Exception as e:
        logger.error(f"Failed to initialize orchestrator: {e}")
        raise


async def shutdown_orchestrator():
    """Cleanup orchestrator on shutdown"""
    global _orchestrator
    if _orchestrator and _orchestrator.redis_client:
        await _orchestrator.redis_client.disconnect()
        logger.info("✅ Orchestrator shut down")


def get_orchestrator() -> OrchestratorAgent:
    """Get orchestrator instance"""
    if _orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    return _orchestrator


# ==================== HTTP ENDPOINTS ====================
class AsyncPlanResponse(BaseModel):
    """Response model for async plan endpoint"""
    session_id: str
    status: str
    message: str
    websocket_url: str
    query: str


@router.post("/plan", response_model=AsyncPlanResponse)
async def create_travel_plan(
    request: TravelQueryRequest,
    background_tasks: BackgroundTasks
):
    """
    Create or update a travel plan from natural language query
    
    **RETURNS IMMEDIATELY** - Connect to WebSocket for real-time updates
    """
    try:
        orchestrator = get_orchestrator()
        
        # Handle session ID
        session_id = request.session_id
        
        # Force new session if requested
        if request.force_new_session and session_id:
            logger.info(f"🔄 Force new session requested, clearing: {session_id}")
            await orchestrator.clear_session_memory(session_id)
            session_id = None
        
        # Generate session ID if not provided
        if not session_id:
            session_id = f"session_{uuid.uuid4().hex[:12]}"
            logger.info(f"🆕 New session created: {session_id}")
        else:
            logger.info(f"🔄 Continuing session: {session_id}")
        
        logger.info(f"📝 Query: {request.query[:100]}...")
                # Right after session_id is determined
        initial_state = {
            "workflow_status": "queued",
            "agent_statuses": {},
            "progress_percent": 0,
            "is_follow_up": False,
            "completed_agents": [],
            "pending_agents": [],
        }
        await orchestrator.redis_client.set_state(session_id, initial_state)
        await asyncio.sleep(0.3)

        
        # Create background task for processing
        async def process_workflow():
            """Run workflow in background"""
            try:
                # Small delay to ensure WebSocket is fully connected
               
                
                logger.info(f"🚀 Starting background workflow for {session_id}")
                
                result = await orchestrator.process_query(
                    user_query=request.query,
                    session_id=session_id
                )
                
                logger.info(f"✅ Background workflow completed for {session_id}")
                
            except Exception as e:
                logger.error(f"❌ Background workflow failed for {session_id}: {e}", exc_info=True)
                
                # Send error update via WebSocket
                try:
                    await orchestrator._send_streaming_update(
                        session_id=session_id,
                        agent="orchestrator",
                        message=f"Error: {str(e)}",
                        update_type="error",
                        progress_percent=0
                    )
                except:
                    pass
        
        # Start workflow in background (fire and forget)
        asyncio.create_task(process_workflow())
        
        # Return immediately with AsyncPlanResponse
        return AsyncPlanResponse(
            session_id=session_id,
            status="started",
            message="Travel plan generation started. Connect to WebSocket for real-time updates.",
            websocket_url=f"ws://localhost:8000/api/v2/orchestrator/ws/{session_id}",
            query=request.query
        )
        
    except Exception as e:
        logger.error(f"Failed to start travel plan: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))



@router.get("/plan/{session_id}/status")
async def get_plan_status(session_id: str):
    """
    Check if a workflow is complete
    """
    orchestrator = get_orchestrator()
    redis_client = orchestrator.redis_client

    state = await redis_client.get_state(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")

    return state

@router.get("/session/{session_id}/memory", response_model=SessionMemoryResponse)
async def get_session_memory(session_id: str):
    """
    Get session memory and context
    
    Use this endpoint to check if a session exists and see its current state
    before sending a follow-up query.
    
    **Example:**
    ```bash
    GET /api/v1/orchestrator/session/session_abc123/memory
    ```
    
    **Response:**
    ```json
    {
        "session_id": "session_abc123",
        "exists": true,
        "destination": "Paris",
        "travel_dates": ["2025-07-01", "2025-07-02", "2025-07-03"],
        "travelers_count": 2,
        "budget_range": "$1500-$2000",
        "has_itinerary": true,
        "has_budget_data": true,
        "conversation_turns": 3,
        "last_updated": "2025-01-15T10:30:00Z",
        "expires_in_hours": 20.5
    }
    ```
    """
    try:
        orchestrator = get_orchestrator()
        
        # Get session memory
        memory = await orchestrator.get_session_memory(session_id)
        
        if not memory:
            return SessionMemoryResponse(
                session_id=session_id,
                exists=False,
                destination=None,
                travel_dates=[],
                travelers_count=None,
                budget_range=None,
                has_itinerary=False,
                has_budget_data=False,
                conversation_turns=0,
                last_updated="",
                expires_in_hours=None
            )
        
        # Calculate expiration time
        redis_client = orchestrator.redis_client
        ttl = await redis_client.client.ttl(f"state:{session_id}")
        expires_in_hours = ttl / 3600 if ttl > 0 else None
        
        conversation_turns = len(memory.get("conversation_history", []))
        
        return SessionMemoryResponse(
            session_id=session_id,
            exists=True,
            destination=memory.get("destination"),
            travel_dates=memory.get("travel_dates", []),
            travelers_count=memory.get("travelers_count"),
            budget_range=memory.get("budget_range"),
            has_itinerary=memory.get("itinerary_data") is not None,
            has_budget_data=memory.get("budget_data") is not None,
            conversation_turns=conversation_turns,
            last_updated=memory.get("end_time", ""),
            expires_in_hours=expires_in_hours
        )
        
    except Exception as e:
        logger.error(f"Failed to get session memory: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/session/{session_id}/history", response_model=ConversationHistoryResponse)
async def get_conversation_history(session_id: str):
    """
    Get conversation history for a session
    
    Returns the full conversation history including user queries and assistant responses.
    
    **Example Response:**
    ```json
    {
        "session_id": "session_abc123",
        "conversation_history": [
            {
                "role": "user",
                "content": "Plan a trip to Paris",
                "timestamp": "2025-01-15T10:00:00Z"
            },
            {
                "role": "assistant",
                "content": "Completed processing: 4/4 agents successful",
                "timestamp": "2025-01-15T10:00:30Z",
                "agents_executed": ["weather", "events", "maps", "budget"]
            },
            {
                "role": "user",
                "content": "Change budget to $2000",
                "timestamp": "2025-01-15T10:05:00Z"
            }
        ],
        "total_turns": 3
    }
    ```
    """
    try:
        orchestrator = get_orchestrator()
        
        # Get session memory
        memory = await orchestrator.get_session_memory(session_id)
        
        if not memory:
            raise HTTPException(status_code=404, detail="Session not found")
        
        conversation_history = memory.get("conversation_history", [])
        
        return ConversationHistoryResponse(
            session_id=session_id,
            conversation_history=conversation_history,
            total_turns=len(conversation_history)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get conversation history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/session/{session_id}/status", response_model=SessionStatusResponse)
async def get_session_status(session_id: str):
    """
    Get the current status of a travel planning session
    
    Use this endpoint to poll for progress updates if not using WebSocket.
    """
    try:
        orchestrator = get_orchestrator()
        redis_client = orchestrator.redis_client
        
        # Get session state from Redis
        state = await redis_client.get_state(session_id)
        
        if not state:
            raise HTTPException(status_code=404, detail="Session not found")
        
        agent_statuses = state.get("agent_statuses", {})
        completed = [k for k, v in agent_statuses.items() if v == "completed"]
        pending = [k for k, v in agent_statuses.items() if v in ["pending", "processing"]]
        
        # Calculate progress
        total_agents = len(agent_statuses)
        completed_count = len(completed)
        progress = int((completed_count / total_agents * 100)) if total_agents > 0 else 0
        
        current_agent = pending[0] if pending else None
        
        return SessionStatusResponse(
            session_id=session_id,
            status=state.get("workflow_status", "unknown"),
            progress_percent=progress,
            current_agent=current_agent,
            completed_agents=completed,
            pending_agents=pending,
            is_follow_up=state.get("is_follow_up", False)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get session status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/session/{session_id}/result")
async def get_session_result(session_id: str):
    """
    Get the final result of a completed travel planning session
    
    Includes all agent responses and conversation context.
    """
    try:
        orchestrator = get_orchestrator()
        redis_client = orchestrator.redis_client
        
        # Get session state from Redis
        state = await redis_client.get_state(session_id)
        
        if not state:
            raise HTTPException(status_code=404, detail="Session not found")
        
        if state.get("workflow_status") != "completed":
            raise HTTPException(
                status_code=400,
                detail=f"Session not completed. Current status: {state.get('workflow_status')}"
            )
        
        return {
            "session_id": session_id,
            "status": state.get("workflow_status"),
            "is_follow_up": state.get("is_follow_up", False),
            "update_type": state.get("update_type"),
            "destination": state.get("destination"),
            "travel_dates": state.get("travel_dates"),
            "weather": state.get("weather_data"),
            "events": state.get("events_data"),
            "maps": state.get("maps_data"),
            "budget": state.get("budget_data"),
            "itinerary": state.get("itinerary_data"),
            "route_optimization": state.get("route_optimization"),
            "messages": state.get("messages", []),
            "errors": state.get("errors", []),
            "agent_statuses": state.get("agent_statuses", {}),
            "conversation_history": state.get("conversation_history", []),
            "conversation_turns": len(state.get("conversation_history", []))
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get session result: {e}")
        raise HTTPException(status_code=500, detail=str(e))

from pydantic import BaseModel
from fastapi import Body

class ExtendSessionRequest(BaseModel):
    hours: int = Field(..., ge=1, le=168, description="Hours to extend (1-168)")


@router.put("/session/{session_id}/extend")
async def extend_session_memory(
    session_id: str,
    request: ExtendSessionRequest = Body(...)
):
    """
    Extend session memory TTL
    
    Useful to keep important sessions alive longer.
    
    **Parameters:**
    - `hours`: Number of hours to extend (default: 24, max: 168 = 7 days)
    
    **Example:**
    ```bash
    PUT /api/v1/orchestrator/session/session_abc123/extend?hours=48
    ```
    """
    try:
        orchestrator = get_orchestrator()
        
        # Check if session exists
        memory = await orchestrator.get_session_memory(session_id)
        if not memory:
            raise HTTPException(status_code=404, detail="Session not found")
        
        hours = request.hours
        
        # Extend TTL
        success = await orchestrator.extend_session_memory(session_id, hours)
        
        if success:
            return {
                "session_id": session_id,
                "message": f"Session extended by {hours} hours",
                "expires_in_hours": hours
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to extend session")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to extend session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/session/{session_id}")
async def delete_session(session_id: str):
    """
    Delete a session and its associated data
    
    This will clear all memory and conversation history for the session.
    """
    try:
        orchestrator = get_orchestrator()
        
        # Delete session state
        success = await orchestrator.clear_session_memory(session_id)
        
        if success:
            return {
                "session_id": session_id,
                "message": "Session deleted successfully"
            }
        else:
            raise HTTPException(status_code=404, detail="Session not found")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# @router.post("/session/{session_id}/reset")
# async def reset_session_to_checkpoint(
#     session_id: str,
#     keep_destination: bool = Field(True, description="Keep destination in memory"),
#     keep_dates: bool = Field(True, description="Keep travel dates in memory")
# ):
#     """
#     Reset session but keep certain fields
    
#     Useful for starting a new plan while keeping some context.
    
#     **Example:**
#     ```json
#     POST /api/v1/orchestrator/session/session_abc123/reset
#     {
#         "keep_destination": true,
#         "keep_dates": false
#     }
#     ```
#     """
#     try:
#         orchestrator = get_orchestrator()
#         redis_client = orchestrator.redis_client
        
#         # Get current memory
#         memory = await orchestrator.get_session_memory(session_id)
#         if not memory:
#             raise HTTPException(status_code=404, detail="Session not found")
        
#         # Create new state with selective fields
#         new_state = {
#             "session_id": session_id,
#             "destination": memory.get("destination") if keep_destination else None,
#             "travel_dates": memory.get("travel_dates", []) if keep_dates else [],
#             "origin": None,
#             "travelers_count": None,
#             "budget_range": None,
#             "user_preferences": None,
#             "conversation_history": [],
#             "weather_data": None,
#             "events_data": None,
#             "maps_data": None,
#             "budget_data": None,
#             "itinerary_data": None,
#             "messages": ["Session reset with partial memory"],
#             "errors": [],
#             "workflow_status": "initialized",
#             "start_time": datetime.utcnow().isoformat()
#         }
        
#         # Save new state
#         await redis_client.set_state(session_id, new_state, ttl=86400)
        
#         return {
#             "session_id": session_id,
#             "message": "Session reset successfully",
#             "kept_fields": {
#                 "destination": keep_destination,
#                 "dates": keep_dates
#             }
#         }
        
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Failed to reset session: {e}")
#         raise HTTPException(status_code=500, detail=str(e))


# ==================== WEBSOCKET ENDPOINT ====================

@router.websocket("/ws/{session_id}")
async def websocket_streaming(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for real-time travel planning updates
    
    Connect to this endpoint to receive streaming updates during travel plan creation.
    
    **Connection:**
    ```javascript
    const ws = new WebSocket('ws://localhost:8010/api/v2/orchestrator/ws/session_abc123');
    ```
    
    **Message Types:**
    - `connected` - Initial connection established
    - `progress` - Progress update with percentage
    - `agent_update` - Individual agent completion
    - `completed` - Workflow completed
    - `error` - Error occurred
    - `pong` - Response to ping
    
    **Message Format:**
    ```json
    {
        "type": "progress",
        "agent": "weather",
        "message": "Weather agent completed",
        "progress_percent": 50,
        "data": { ... },
        "timestamp": "2025-01-15T10:00:00Z"
    }
    ```
    """
    await websocket.accept()
    logger.info(f"🔌 WebSocket connected for session: {session_id}")
    
    try:
        orchestrator = get_orchestrator()
        redis_client = orchestrator.redis_client
        
        # Check if session exists and send context
        memory = await orchestrator.get_session_memory(session_id)
        is_follow_up = memory is not None
        
        # Subscribe to streaming updates for this session
        streaming_channel = RedisChannels.get_streaming_channel(session_id)
        
        # Message handler
        async def handle_message(message: Dict[str, Any]):
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.error(f"Failed to send WebSocket message: {e}")
        
        # Subscribe to Redis channel
        subscription_id = await redis_client.subscribe(streaming_channel, handle_message)
        
        logger.info(f"📡 Subscribed to streaming updates for session: {session_id}")
        
        # Send initial connection message with context
        await websocket.send_json({
            "type": "connected",
            "session_id": session_id,
            "is_follow_up": is_follow_up,
            "message": f"Connected to travel planning stream ({'continuing session' if is_follow_up else 'new session'})",
            "context": {
                "destination": memory.get("destination") if memory else None,
                "has_itinerary": memory.get("itinerary_data") is not None if memory else False
            } if is_follow_up else None,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        # Keep connection alive and listen for client messages
        try:
            while True:
                # Wait for client message (or timeout)
                data = await asyncio.wait_for(websocket.receive_text(), timeout=300)
                
                # Handle client messages
                try:
                    client_msg = json.loads(data)
                    
                    if client_msg.get("type") == "ping":
                        await websocket.send_json({
                            "type": "pong",
                            "timestamp": datetime.utcnow().isoformat()
                        })
                    
                    elif client_msg.get("type") == "get_status":
                        # Send current status
                        state = await redis_client.get_state(session_id)
                        if state:
                            await websocket.send_json({
                                "type": "status",
                                "workflow_status": state.get("workflow_status"),
                                "agent_statuses": state.get("agent_statuses", {}),
                                "timestamp": datetime.utcnow().isoformat()
                            })
                        
                except json.JSONDecodeError:
                    pass
                    
        except asyncio.TimeoutError:
            # Connection timeout after 5 minutes of inactivity
            logger.info(f"⏱️ WebSocket timeout for session: {session_id}")
            await websocket.send_json({
                "type": "timeout",
                "message": "Connection timeout due to inactivity",
                "timestamp": datetime.utcnow().isoformat()
            })
            
    except WebSocketDisconnect:
        logger.info(f"🔌 WebSocket disconnected for session: {session_id}")
    except Exception as e:
        logger.error(f"WebSocket error for session {session_id}: {e}", exc_info=True)
        try:
            await websocket.send_json({
                "type": "error",
                "message": str(e),
                "timestamp": datetime.utcnow().isoformat()
            })
        except:
            pass
    finally:
        # Cleanup subscription
        try:
            await redis_client.unsubscribe(subscription_id)
            logger.info(f"🔕 Unsubscribed from streaming updates for session: {session_id}")
        except:
            pass
        
        try:
            await websocket.close()
        except:
            pass


# ==================== HEALTH CHECK ====================

@router.get("/health")
async def health_check():
    """
    Health check endpoint for orchestrator service
    """
    try:
        orchestrator = get_orchestrator()
        redis_client = orchestrator.redis_client
        
        # Check Redis connection
        redis_healthy = await redis_client.health_check()
        
        return {
            "status": "healthy" if redis_healthy else "degraded",
            "orchestrator": "ready",
            "redis": "connected" if redis_healthy else "disconnected",
            "features": {
                "memory_support": True,
                "conversation_tracking": True,
                "incremental_updates": True
            },
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
        )


# ==================== EXPORT STARTUP/SHUTDOWN HANDLERS ====================

async def startup():
    """Startup handler for FastAPI"""
    await init_orchestrator()


async def shutdown():
    """Shutdown handler for FastAPI"""
    await shutdown_orchestrator()


# Export handlers for use in main.py
__all__ = ["router", "startup", "shutdown"]