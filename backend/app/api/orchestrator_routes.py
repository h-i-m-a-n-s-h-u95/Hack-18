from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import asyncio
import json
from datetime import datetime

from app.core.orchestrator import TravelOrchestrator
from app.messaging.redis_client import get_redis_client, RedisChannels
from app.core.state import UserPreferences
import logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["orchestrator"])


# ==================== REQUEST/RESPONSE MODELS ====================

class TripPlanRequest(BaseModel):
    """Request model for trip planning"""
    destination: str = Field(..., description="Destination city or location")
    origin: str = Field(..., description="Origin city or location")
    travel_dates: List[str] = Field(..., description="Travel dates in YYYY-MM-DD format")
    travelers_count: int = Field(default=1, ge=1, le=20, description="Number of travelers")
    budget_range: Optional[str] = Field(None, description="Budget range (e.g., '$1000-2000')")
    user_preferences: Optional[Dict[str, Any]] = Field(None, description="User preferences")
    session_id: Optional[str] = Field(None, description="Session ID for resuming")
    include_travel_options: bool = Field(False, description="Include flights, trains, buses, hotels")
    
    class Config:
        json_schema_extra = {
            "example": {
                "destination": "Paris, France",
                "origin": "New York, USA",
                "travel_dates": ["2025-07-01", "2025-07-05"],
                "travelers_count": 2,
                "budget_range": "$3000-5000",
                "user_preferences": {
                    "interests": ["art", "food", "history"],
                    "pace": "moderate",
                    "dietary_restrictions": ["vegetarian"]
                },
                "include_travel_options": True
            }
        }


class RouteData(BaseModel):
    """Enhanced route data model"""
    primary_route: Optional[Dict[str, Any]] = None
    alternative_routes: Optional[Dict[str, Any]] = None
    route_analysis: Optional[str] = None
    recommended_mode: Optional[str] = None
    comparison: Optional[Dict[str, Any]] = None
    travel_options: Optional[Dict[str, Any]] = None


class TripPlanResponse(BaseModel):
    """Response model for trip planning"""
    session_id: str
    status: str
    message: str
    data: Optional[Dict[str, Any]] = None
    errors: List[str] = Field(default_factory=list)
    processing_time_ms: Optional[int] = None


class SessionStatusResponse(BaseModel):
    """Response model for session status"""
    session_id: str
    workflow_status: str
    completed_agents: int
    failed_agents: int
    total_agents: int
    messages: List[str]
    errors: List[str]
    created_at: str
    updated_at: str


# ==================== ENDPOINTS ====================

@router.post("/plan-trip", response_model=TripPlanResponse)
async def plan_trip(request: TripPlanRequest):
    """
    Plan a trip using the orchestrated agent workflow
    
    This endpoint orchestrates multiple AI agents in parallel to:
    - Get weather forecasts
    - Find local events
    - Calculate routes and travel times (with alternatives)
    - Optionally fetch flights, trains, buses, and hotels
    - Estimate budget
    - Generate a complete itinerary
    """
    start_time = datetime.utcnow()
    
    try:
        logger.info(
            f"Trip planning request: {request.origin} → {request.destination}, "
            f"{len(request.travel_dates)} days, travel_options={request.include_travel_options}"
        )
        
        # Initialize orchestrator
        orchestrator = TravelOrchestrator()
        
        # Execute orchestrated workflow
        final_state = await orchestrator.plan_trip(
            destination=request.destination,
            origin=request.origin,
            travel_dates=request.travel_dates,
            travelers_count=request.travelers_count,
            budget_range=request.budget_range,
            user_preferences=request.user_preferences,
            session_id=request.session_id,
            include_travel_options=request.include_travel_options
        )
        
        # Calculate processing time
        processing_time = (datetime.utcnow() - start_time).total_seconds() * 1000
        
        # Extract route data (now includes more than just primary_route)
        route_data = final_state.get("route_data", {})
        
        # Build enhanced response with all route data
        return TripPlanResponse(
            session_id=final_state["session_id"],
            status=final_state["workflow_status"].value,
            message=final_state.get("trip_summary", "Trip planning completed"),
            data={
                "weather": final_state.get("weather_data"),
                "weather_summary": final_state.get("weather_summary"),
                "events": final_state.get("events_data"),
                "route": {
                    "primary_route": route_data.get("primary_route"),
                    "alternative_routes": route_data.get("alternative_routes"),
                    "route_analysis": route_data.get("route_analysis"),
                    "recommended_mode": route_data.get("recommended_mode"),
                    "comparison": route_data.get("comparison"),
                    "travel_options": route_data.get("travel_options") if request.include_travel_options else None
                },
                "budget": final_state.get("budget_data"),
                "itinerary": final_state.get("itinerary_data"),
                "final_itinerary_text": final_state.get("final_itinerary"),
                "agent_status": final_state.get("agent_status"),
                "completed_agents": final_state.get("completed_agents"),
                "failed_agents": final_state.get("failed_agents")
            },
            errors=final_state.get("errors", []),
            processing_time_ms=int(processing_time)
        )
        
    except Exception as e:
        logger.error(f"Trip planning failed: {str(e)}", exc_info=True)
        processing_time = (datetime.utcnow() - start_time).total_seconds() * 1000
        
        raise HTTPException(
            status_code=500,
            detail={
                "message": f"Trip planning failed: {str(e)}",
                "processing_time_ms": int(processing_time)
            }
        )


@router.post("/plan-trip/stream")
async def plan_trip_stream(request: TripPlanRequest):
    """
    Plan a trip with real-time streaming updates
    
    Returns Server-Sent Events (SSE) stream with progress updates
    """
    
    async def event_generator():
        """Generate SSE events for real-time updates"""
        redis_client = get_redis_client()
        await redis_client.connect()
        
        try:
            # Start planning in background
            orchestrator = TravelOrchestrator(redis_client)
            
            # Create session first
            from app.core.state import create_initial_state
            initial_state = create_initial_state(
                destination=request.destination,
                origin=request.origin,
                travel_dates=request.travel_dates,
                travelers_count=request.travelers_count,
                budget_range=request.budget_range
            )
            
            session_id = initial_state["session_id"]
            
            # Subscribe to streaming updates
            streaming_channel = RedisChannels.get_streaming_channel(session_id)
            updates_queue = asyncio.Queue()
            
            async def streaming_handler(data):
                await updates_queue.put(data)
            
            subscription_id = await redis_client.subscribe(
                streaming_channel,
                streaming_handler
            )
            
            # Send initial event
            yield f"data: {json.dumps({'type': 'started', 'session_id': session_id})}\n\n"
            
            # Start planning in background
            planning_task = asyncio.create_task(
                orchestrator.plan_trip(
                    destination=request.destination,
                    origin=request.origin,
                    travel_dates=request.travel_dates,
                    travelers_count=request.travelers_count,
                    budget_range=request.budget_range,
                    session_id=session_id,
                    include_travel_options=request.include_travel_options
                )
            )
            
            # Stream updates
            while not planning_task.done():
                try:
                    update = await asyncio.wait_for(updates_queue.get(), timeout=1.0)
                    # Send the update with proper JSON serialization
                    yield f"data: {json.dumps(update, default=str)}\n\n"
                except asyncio.TimeoutError:
                    # Send heartbeat
                    yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
            
            # Get final result
            final_state = await planning_task
            
            # Extract full route data for streaming response
            route_data = final_state.get("route_data", {})
            
            result = {
                "type": "completed",
                "status": final_state["workflow_status"].value,
                "session_id": session_id,
                "data": {
                    "completed_agents": final_state["completed_agents"],
                    "failed_agents": final_state["failed_agents"],
                    "trip_summary": final_state.get("trip_summary"),
                    "weather_summary": final_state.get("weather_summary"),
                    "route_analysis": route_data.get("route_analysis"),
                    "recommended_transport": route_data.get("recommended_mode"),
                    "has_travel_options": bool(route_data.get("travel_options"))
                },
            }
            
            yield f"data: {json.dumps(result, default=str)}\n\n"
            
            # Cleanup
            await redis_client.unsubscribe(subscription_id)
            
        except Exception as e:
            logger.error(f"Streaming failed: {str(e)}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
        finally:
            await redis_client.disconnect()
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.get("/session/{session_id}", response_model=SessionStatusResponse)
async def get_session_status(session_id: str):
    """Get the status of a planning session"""
    try:
        orchestrator = TravelOrchestrator()
        await orchestrator.redis_client.connect()
        
        state = await orchestrator.get_session_state(session_id)
        
        if not state:
            raise HTTPException(status_code=404, detail="Session not found")
        
        return SessionStatusResponse(
            session_id=session_id,
            workflow_status=state["workflow_status"].value,
            completed_agents=state["completed_agents"],
            failed_agents=state["failed_agents"],
            total_agents=state["total_agents"],
            messages=state["messages"],
            errors=state["errors"],
            created_at=state["created_at"],
            updated_at=state["updated_at"]
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get session status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await orchestrator.redis_client.disconnect()


@router.get("/session/{session_id}/full-data")
async def get_session_full_data(session_id: str):
    """Get the complete data for a planning session including all route details"""
    try:
        orchestrator = TravelOrchestrator()
        await orchestrator.redis_client.connect()
        
        state = await orchestrator.get_session_state(session_id)
        
        if not state:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Extract full route data
        route_data = state.get("route_data", {})
        
        return {
            "session_id": session_id,
            "workflow_status": state["workflow_status"].value,
            "data": {
                "weather": state.get("weather_data"),
                "weather_summary": state.get("weather_summary"),
                "events": state.get("events_data"),
                "route": {
                    "primary_route": route_data.get("primary_route"),
                    "alternative_routes": route_data.get("alternative_routes"),
                    "route_analysis": route_data.get("route_analysis"),
                    "recommended_mode": route_data.get("recommended_mode"),
                    "comparison": route_data.get("comparison"),
                    "travel_options": route_data.get("travel_options")
                },
                "budget": state.get("budget_data"),
                "itinerary": state.get("itinerary_data"),
                "final_itinerary_text": state.get("final_itinerary")
            },
            "metadata": {
                "completed_agents": state["completed_agents"],
                "failed_agents": state["failed_agents"],
                "total_agents": state["total_agents"],
                "created_at": state["created_at"],
                "updated_at": state["updated_at"]
            },
            "messages": state.get("messages", []),
            "errors": state.get("errors", [])
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get session full data: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await orchestrator.redis_client.disconnect()


@router.delete("/session/{session_id}")
async def cancel_session(session_id: str):
    """Cancel an ongoing planning session"""
    try:
        orchestrator = TravelOrchestrator()
        await orchestrator.redis_client.connect()
        
        await orchestrator.cancel_session(session_id)
        
        return {
            "success": True,
            "message": f"Session {session_id} cancelled",
            "session_id": session_id
        }
        
    except Exception as e:
        logger.error(f"Failed to cancel session: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await orchestrator.redis_client.disconnect()


@router.get("/health")
async def orchestrator_health():
    """Check orchestrator and Redis health"""
    try:
        redis_client = get_redis_client()
        await redis_client.connect()
        
        is_healthy = await redis_client.health_check()
        redis_info = await redis_client.get_info()
        
        await redis_client.disconnect()
        
        return {
            "status": "healthy" if is_healthy else "unhealthy",
            "redis_connected": is_healthy,
            "redis_info": redis_info,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return {
            "status": "unhealthy",
            "redis_connected": False,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }