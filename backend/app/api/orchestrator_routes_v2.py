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
    preference_weights: Optional[Dict[str, int]] = Field(
        None,
        description="Weighted interest preferences (1-5). Keys: culture, food, adventure, shopping, nature, nightlife"
    )
    
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
                    session_id=session_id,
                    preference_weights=request.preference_weights
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

# ==================== HOTEL RECOMMENDATIONS ENDPOINT ====================

@router.get("/session/{session_id}/hotels")
async def get_hotel_recommendations(session_id: str, force_refresh: bool = False):
    """
    Get hotel recommendations for a trip session.

    Pipeline:
      1. Check Redis cache (6-hour TTL with generated_at)
      2. If miss: Booking.com RapidAPI → real data
      3. Groq LLM → tier categorization + descriptions + tips
      4. Graceful degradation: API fail → Groq-only → empty state

    Rate limited: 1 force-refresh per 10 minutes per session.
    """
    from app.services.hotel_service import (
        fetch_hotels_from_booking,
        enrich_hotels_with_llm,
        generate_hotels_via_llm_only,
        HOTEL_CACHE_TTL,
        RATE_LIMIT_SECONDS,
    )
    from datetime import timezone

    try:
        orchestrator = get_orchestrator()
        redis_client = orchestrator.redis_client

        # 1. Get session state
        state = await redis_client.get_state(session_id)
        if not state:
            raise HTTPException(status_code=404, detail="Session not found")

        destination = state.get("destination")
        if not destination:
            raise HTTPException(status_code=400, detail="No destination in this session")

        travel_dates = state.get("travel_dates", [])

        # 2. Check cache — return immediately if fresh
        cached_hotel_data = state.get("hotel_data")
        if cached_hotel_data and not force_refresh:
            generated_at = cached_hotel_data.get("generated_at", "")
            if generated_at:
                try:
                    gen_time = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
                    age_seconds = (datetime.now(timezone.utc) - gen_time).total_seconds()
                    if age_seconds < HOTEL_CACHE_TTL:
                        logger.info(f"[Hotels] Cache hit for '{destination}' (age: {int(age_seconds)}s)")
                        return cached_hotel_data
                except (ValueError, TypeError):
                    pass  # Invalid timestamp, re-fetch

        # 3. Rate limiting on force-refresh
        if force_refresh:
            last_refresh = state.get("hotel_last_refresh", "")
            if last_refresh:
                try:
                    last_time = datetime.fromisoformat(last_refresh.replace("Z", "+00:00"))
                    since = (datetime.now(timezone.utc) - last_time).total_seconds()
                    if since < RATE_LIMIT_SECONDS:
                        remaining = int(RATE_LIMIT_SECONDS - since)
                        raise HTTPException(
                            status_code=429,
                            detail=f"Rate limited. Try again in {remaining}s."
                        )
                except (ValueError, TypeError):
                    pass

        # 4. Compute checkin / checkout from travel_dates
        if travel_dates and len(travel_dates) >= 2:
            checkin = travel_dates[0]
            checkout = travel_dates[-1]
        elif travel_dates and len(travel_dates) == 1:
            checkin = travel_dates[0]
            # Assume single day → next day checkout
            from datetime import timedelta
            try:
                dt = datetime.strptime(checkin, "%Y-%m-%d")
                checkout = (dt + timedelta(days=1)).strftime("%Y-%m-%d")
            except ValueError:
                checkout = checkin
        else:
            # Fallback to tomorrow/day-after
            from datetime import timedelta
            today = datetime.now().strftime("%Y-%m-%d")
            tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
            checkin = today
            checkout = tomorrow

        # Ensure dates are in the future for Booking.com API stability
        try:
            from datetime import timedelta
            today_dt = datetime.now().date()
            checkin_dt = datetime.strptime(checkin, "%Y-%m-%d").date()
            checkout_dt = datetime.strptime(checkout, "%Y-%m-%d").date()
            if checkin_dt < today_dt:
                duration = max((checkout_dt - checkin_dt).days, 1)
                new_checkin = today_dt + timedelta(days=1)
                new_checkout = new_checkin + timedelta(days=duration)
                checkin = new_checkin.strftime("%Y-%m-%d")
                checkout = new_checkout.strftime("%Y-%m-%d")
                logger.info(f"[Hotels] Shifted past dates to future checkin: {checkin}, checkout: {checkout} (duration: {duration} days)")
        except (ValueError, TypeError):
            pass

        # 5. Fetch from Booking.com → real data
        source = "booking_com+groq"
        hotels = await fetch_hotels_from_booking(destination, checkin, checkout)

        if hotels:
            # 6. Enrich with Groq LLM
            groq_key = getattr(settings, "groq_api_key", None)
            if groq_key:
                hotels = await enrich_hotels_with_llm(hotels, destination, groq_key)
        else:
            # 7. Graceful degradation → Groq-only fallback
            logger.warning(f"[Hotels] Booking.com returned no results, falling back to Groq-only")
            source = "groq_fallback"
            groq_key = getattr(settings, "groq_api_key", None)
            if groq_key:
                hotels = await generate_hotels_via_llm_only(
                    destination, checkin, checkout, groq_key
                )

        # 8. Sort: 2 budget → 2 mid-range → 2 luxury (pick top 2 per tier)
        tier_order = {"budget": 0, "mid-range": 1, "luxury": 2}
        tier_buckets: dict = {"budget": [], "mid-range": [], "luxury": []}
        for h in hotels:
            tier = h.get("tier", "mid-range")
            if tier in tier_buckets and len(tier_buckets[tier]) < 2:
                tier_buckets[tier].append(h)

        sorted_hotels = tier_buckets["budget"] + tier_buckets["mid-range"] + tier_buckets["luxury"]

        # If we have fewer than 6 after filtering, add remaining hotels
        seen_ids = {h["id"] for h in sorted_hotels}
        for h in hotels:
            if len(sorted_hotels) >= 6:
                break
            if h["id"] not in seen_ids:
                sorted_hotels.append(h)
                seen_ids.add(h["id"])

        # 8b. Calculate distance to first itinerary stop coordinates
        try:
            import math
            def calculate_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
                R = 6371.0 # Earth's radius in km
                dlat = math.radians(lat2 - lat1)
                dlng = math.radians(lng2 - lng1)
                a = (math.sin(dlat / 2) ** 2 + 
                     math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2)
                c = 2 * math.asin(math.sqrt(a))
                return R * c

            # Find first stop in day_routes that has valid lat/lng
            first_stop = None
            route_opt = state.get("route_optimization")
            if route_opt and "day_routes" in route_opt:
                day_routes = route_opt["day_routes"]
                if day_routes and len(day_routes) > 0:
                    first_day_stops = day_routes[0]
                    for stop in first_day_stops:
                        if stop and stop.get("lat") and stop.get("lng"):
                            first_stop = stop
                            break

            if first_stop:
                ref_lat = float(first_stop.get("lat"))
                ref_lng = float(first_stop.get("lng"))
                ref_name = first_stop.get("name") or "First attraction"
                for h in sorted_hotels:
                    h_lat = h.get("lat")
                    h_lng = h.get("lng")
                    if h_lat and h_lng:
                        dist = calculate_distance(ref_lat, ref_lng, h_lat, h_lng)
                        h["proximity"] = {
                            "attraction_name": ref_name,
                            "distance_km": round(dist, 1)
                        }
        except Exception as proximity_err:
            logger.error(f"[Hotels] Failed to calculate proximity: {proximity_err}")

        # 9. Build response
        now_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        hotel_response = {
            "destination": destination,
            "currency": "INR",
            "generated_at": now_utc,
            "source": source,
            "hotels": sorted_hotels,
        }

        # 10. Cache in session state
        state["hotel_data"] = hotel_response
        state["hotel_last_refresh"] = now_utc
        await redis_client.set_state(session_id, state)

        logger.info(
            f"[Hotels] Returning {len(sorted_hotels)} hotels for '{destination}' "
            f"(source={source})"
        )
        return hotel_response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Hotels] Failed to get recommendations: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# ==================== SWAP SUGGESTIONS ENDPOINTS ====================

class SwapOption(BaseModel):
    name: str
    description: str
    category: str
    lat: float
    lng: float
    estimated_cost: str

class SwapOptionsResponse(BaseModel):
    activity_id: str
    alternatives: List[SwapOption]

class SwapApplyRequest(BaseModel):
    activity_id: str
    selected_alternative: SwapOption


@router.get("/session/{session_id}/swap-options", response_model=SwapOptionsResponse)
async def get_swap_options(session_id: str, activity_id: str):
    """
    Get 3 alternative options for a specific activity slot.
    """
    import re
    try:
        orchestrator = get_orchestrator()
        redis_client = orchestrator.redis_client
        
        # 1. Get session state
        state = await redis_client.get_state(session_id)
        if not state:
            raise HTTPException(status_code=404, detail="Session not found")
        
        destination = state.get("destination")
        if not destination:
            raise HTTPException(status_code=400, detail="No destination specified in this session")
            
        itinerary_data = state.get("itinerary_data")
        if not itinerary_data:
            raise HTTPException(status_code=400, detail="No itinerary found for this session")

        # Parse activity_id, e.g. day_1_act_2
        m = re.match(r'day_(\d+)_act_(\d+)', activity_id.lower())
        if not m:
            raise HTTPException(status_code=400, detail="Invalid activity_id format. Expected 'day_X_act_Y'")
        
        day_num = int(m.group(1))
        act_idx = int(m.group(2))
        
        itinerary_days = itinerary_data if isinstance(itinerary_data, list) else itinerary_data.get("itinerary_days", [])
        
        # Check day bounds
        day_idx = day_num - 1
        if day_idx < 0 or day_idx >= len(itinerary_days):
            raise HTTPException(status_code=404, detail=f"Day {day_num} not found in itinerary")
            
        day_obj = itinerary_days[day_idx]
        activities = day_obj.get("activities", [])
        if act_idx < 0 or act_idx >= len(activities):
            raise HTTPException(status_code=404, detail=f"Activity index {act_idx} not found on Day {day_num}")
            
        # 2. Get list of tourist attractions for the city
        from app.ml.attraction_database import get_attractions_for_city
        all_attractions = await get_attractions_for_city(destination)
        
        # Collect all attraction names currently in the itinerary to avoid suggesting them
        # Activity strings are formatted like: "10:00 AM - Taj Mahal - 2h (description)"
        # We extract just the name part for accurate matching.
        planned_names = set()
        for day in itinerary_days:
            for act in day.get("activities", []):
                act_str = str(act).strip()
                # Split by " - " to extract the name (second segment)
                parts = [p.strip() for p in act_str.split(" - ")]
                if len(parts) >= 2:
                    # The name is typically the second part after the time
                    extracted_name = parts[1].lower()
                    planned_names.add(extracted_name)
                else:
                    # Fallback: use the whole string
                    planned_names.add(act_str.lower())
                
        # 3. Filter attractions — use normalized name matching
        alternatives = []
        for attr in all_attractions:
            attr_name_lower = attr["name"].lower().strip()
            is_planned = False
            for planned in planned_names:
                # Exact match or one contains the other (on extracted names only)
                if attr_name_lower == planned or attr_name_lower in planned or planned in attr_name_lower:
                    is_planned = True
                    break
            if is_planned:
                continue
                
            category = attr.get("category", "landmark")
            est_cost = "Free"
            if category in ("monument", "museum", "palace", "fort"):
                est_cost = "₹50 - ₹200"
            elif category == "market":
                est_cost = "Varies"
            
            alternatives.append(SwapOption(
                name=attr["name"],
                description=attr.get("description") or f"A popular {category} in {destination}.",
                category=category,
                lat=attr["lat"],
                lng=attr["lng"],
                estimated_cost=est_cost
            ))
            
            if len(alternatives) >= 3:
                break
                
        # Note: No hardcoded fallbacks — get_attractions_for_city() returns
        # 8-12 real attractions via Google Places / Groq LLM, which is more
        # than enough to provide 3 alternatives after filtering.
                
        return SwapOptionsResponse(
            activity_id=activity_id,
            alternatives=alternatives
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get swap options: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/session/{session_id}/swap-apply")
async def apply_swap(session_id: str, request: SwapApplyRequest):
    """
    Apply a swap to a specific activity slot, updating the itinerary text and Leaflet route optimization.
    """
    import re
    try:
        orchestrator = get_orchestrator()
        redis_client = orchestrator.redis_client
        
        # 1. Get session state
        state = await redis_client.get_state(session_id)
        if not state:
            raise HTTPException(status_code=404, detail="Session not found")
            
        itinerary_data = state.get("itinerary_data")
        if not itinerary_data:
            raise HTTPException(status_code=400, detail="No itinerary found for this session")
            
        activity_id = request.activity_id
        selected = request.selected_alternative
        
        m = re.match(r'day_(\d+)_act_(\d+)', activity_id.lower())
        if not m:
            raise HTTPException(status_code=400, detail="Invalid activity_id format")
            
        day_num = int(m.group(1))
        act_idx = int(m.group(2))
        
        itinerary_days = itinerary_data if isinstance(itinerary_data, list) else itinerary_data.get("itinerary_days", [])
        day_idx = day_num - 1
        
        if day_idx < 0 or day_idx >= len(itinerary_days):
            raise HTTPException(status_code=404, detail="Day not found")
            
        day_obj = itinerary_days[day_idx]
        activities = day_obj.get("activities", [])
        if act_idx < 0 or act_idx >= len(activities):
            raise HTTPException(status_code=404, detail="Activity index not found")
            
        old_activity = activities[act_idx]
        
        # 2. Parse time and duration from old activity string
        time_match = re.search(r'^(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))', old_activity)
        time_str = time_match.group(1) if time_match else "10:00 AM"
        
        duration_match = re.search(r'-\s*(\d+(?:\.\d+)?\s*(?:h|hr|hrs|mins|m))\s*(?:-|$|\()', old_activity)
        duration_str = duration_match.group(1) if duration_match else "2h"
        
        # Reconstruct new activity string
        desc_clean = selected.description.replace("(", "").replace(")", "")
        desc_clean = desc_clean[:60] + "..." if len(desc_clean) > 60 else desc_clean
        new_activity = f"{time_str} - {selected.name} - {duration_str} ({desc_clean})"
        
        # Update text activity list
        activities[act_idx] = new_activity
        
        # 3. Update route_optimization map routes
        route_opt = state.get("route_optimization")
        if route_opt and isinstance(route_opt, dict) and "day_routes" in route_opt:
            day_routes = route_opt.get("day_routes", [])
            if day_idx < len(day_routes):
                day_stops = day_routes[day_idx]
                
                # Find matching stop by name or index
                matched_stop_idx = -1
                old_name_candidate = old_activity
                parts = [p.strip() for p in old_activity.split("-")]
                if len(parts) >= 2:
                    old_name_candidate = parts[1]
                
                for idx, stop in enumerate(day_stops):
                    stop_name = stop.get("name", "").lower()
                    if stop_name in old_name_candidate.lower() or old_name_candidate.lower() in stop_name:
                        matched_stop_idx = idx
                        break
                        
                if matched_stop_idx == -1 and len(day_stops) > 0:
                    matched_stop_idx = min(act_idx, len(day_stops) - 1)
                    
                if 0 <= matched_stop_idx < len(day_stops):
                    day_stops[matched_stop_idx] = {
                        "name": selected.name,
                        "lat": selected.lat,
                        "lng": selected.lng,
                        "visit_minutes": day_stops[matched_stop_idx].get("visit_minutes", 60),
                        "category": selected.category
                    }
                    
                    # 4. Re-optimize using OR-Tools
                    from app.ml.route_optimizer import optimize_day_order, _route_total_km
                    ordered_stops = optimize_day_order(day_stops)
                    day_routes[day_idx] = ordered_stops
                    
                    # Recalculate stats
                    total_optimized_km = 0.0
                    total_naive_km = 0.0
                    for d_stops in day_routes:
                        if d_stops:
                            total_optimized_km += _route_total_km(d_stops)
                            total_naive_km += _route_total_km(d_stops)
                            
                    route_opt["stats"] = {
                        "total_optimized_km": round(total_optimized_km, 1),
                        "total_naive_km": round(total_naive_km, 1),
                        "km_saved": round(max(0, total_naive_km - total_optimized_km), 1),
                        "ortools_used": route_opt.get("stats", {}).get("ortools_used", True)
                    }
                    
        # 5. Save updated state back to Redis
        await redis_client.set_state(session_id, state)
        
        # 6. Publish streaming update on WS channel
        try:
            await orchestrator._send_streaming_update(
                session_id=session_id,
                agent="orchestrator",
                message="Itinerary updated — route optimized",
                update_type="agent_update",
                progress_percent=100,
                data={
                    "itinerary_data": itinerary_data,
                    "route_optimization": route_opt
                }
            )
        except Exception as ws_err:
            logger.warning(f"Failed to send streaming update: {ws_err}")
            
        return {
            "success": True,
            "itinerary": itinerary_data,
            "route_optimization": route_opt
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to apply swap: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==================== EXPORT STARTUP/SHUTDOWN HANDLERS ====================

async def startup():
    """Startup handler for FastAPI"""
    await init_orchestrator()


async def shutdown():
    """Shutdown handler for FastAPI"""
    await shutdown_orchestrator()


# Export handlers for use in main.py
__all__ = ["router", "startup", "shutdown"]