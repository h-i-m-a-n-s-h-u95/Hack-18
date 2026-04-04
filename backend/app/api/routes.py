from fastapi import APIRouter, HTTPException
from datetime import datetime
import time
from app.models.requests import TravelPlanRequest, WeatherRequest
from app.models.response import (
    TravelPlanResponse, 
    WeatherResponse, 
    HealthResponse, 
    ErrorResponse
)
from app.agents.weather_agent import WeatherAgent
from app.core.state import create_initial_state
import logging

logger = logging.getLogger(__name__)

# Create router
router = APIRouter()

# Initialize all agents
weather_agent = WeatherAgent()



@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now().isoformat(),
        version="1.0.0"
    )


@router.post("/weather", response_model=WeatherResponse)
async def get_weather(request: WeatherRequest):
    """Get weather information for a location and dates"""
    try:
        logger.info(f"Weather request for {request.location}")
        
        weather_data = await weather_agent.weather_service.get_weather_for_dates(
            location=request.location,
            dates=request.dates
        )
        
        return WeatherResponse(
            success=True,
            data=weather_data
        )
        
    except Exception as e:
        logger.error(f"Weather request failed: {str(e)}")
        return WeatherResponse(
            success=False,
            error=f"Failed to get weather data: {str(e)}"
        )

@router.post("/plan", response_model=TravelPlanResponse)
async def create_travel_plan(request: TravelPlanRequest):
    """Create a comprehensive travel plan with all agents"""
    start_time = time.time()
    
    try:
        logger.info(f"Complete travel plan request: {request.origin} to {request.destination}")
        
        # Create initial state
        state = create_initial_state(
            destination=request.destination,
            origin=request.origin,
            travel_dates=request.travel_dates,
            travelers_count=request.travelers_count,
            budget_range=request.budget_range
        )
        
        # Process with all agents sequentially
        state = await weather_agent.process(state)
        
        # Calculate processing time
        processing_time = time.time() - start_time
        
        # Generate comprehensive trip summary
        trip_summary = await _generate_complete_trip_summary(state)
        
        return TravelPlanResponse(
            success=True,
            message="Complete travel plan created successfully",
            trip_summary=trip_summary,
            weather=state.get('weather_data'),
            route=state.get('route_data'),
            budget=state.get('budget_data'),
            itinerary=state.get('itinerary_data'),
            errors=state.get('errors', []),
            processing_time=processing_time
        )
        
    except Exception as e:
        processing_time = time.time() - start_time
        logger.error(f"Complete travel plan failed: {str(e)}")
        
        return TravelPlanResponse(
            success=False,
            message=f"Travel planning failed: {str(e)}",
            errors=[str(e)],
            processing_time=processing_time
        )


async def _generate_complete_trip_summary(state):
    """Generate a comprehensive trip summary with all agent data"""
    messages = state.get('messages', [])
    weather_data = state.get('weather_data', [])
    route_data = state.get('route_data')
    budget_data = state.get('budget_data')
    itinerary_data = state.get('itinerary_data', [])
    
    summary_parts = [
        f"Trip from {state['origin']} to {state['destination']}",
        f"Travel dates: {', '.join(state['travel_dates'])}",
        f"Travelers: {state['travelers_count']}"
    ]
    
    # Add weather summary
    if weather_data:
        avg_temp_max = sum(w.temperature_max for w in weather_data) / len(weather_data)
        avg_temp_min = sum(w.temperature_min for w in weather_data) / len(weather_data)
        summary_parts.append(
            f"Weather: {avg_temp_min:.1f}°C - {avg_temp_max:.1f}°C"
        )
    
    # Add agent messages
    if messages:
        summary_parts.extend(messages)
    
    return " | ".join(summary_parts)


@router.get("/test-weather/{location}")
async def test_weather_service(location: str, dates: str = None):
    """Test endpoint for weather service"""
    try:
        if not dates:
            # Default to next 3 days
            from datetime import date, timedelta
            test_dates = []
            for i in range(3):
                test_date = date.today() + timedelta(days=i)
                test_dates.append(test_date.strftime("%Y-%m-%d"))
        else:
            test_dates = dates.split(",")
        
        weather_data = await weather_agent.weather_service.get_weather_for_dates(
            location=location,
            dates=test_dates
        )
        
        return {
            "success": True,
            "location": location,
            "dates": test_dates,
            "weather_data": [w.dict() for w in weather_data]
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "location": location
        }



    """Test endpoint for route service"""
    try:
        route_data = await maps_agent.maps_service.get_route_between_locations(
            origin=origin,
            destination=destination,
            transport_mode=mode
        )
        
        if route_data:
            return {
                "success": True,
                "origin": origin,
                "destination": destination,
                "transport_mode": mode,
                "route_data": route_data.dict()
            }
        else:
            return {
                "success": False,
                "error": "Route calculation failed",
                "origin": origin,
                "destination": destination
            }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "origin": origin,
            "destination": destination
        }