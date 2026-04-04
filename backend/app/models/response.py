
# ============================================
# RESPONSE SCHEMAS
# ============================================
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Dict, Any
from datetime import date, datetime
from app.core.state import EventInfo, WeatherInfo, RouteInfo, RouteData, BudgetBreakdown, ItineraryDay


class TravelPlanResponse(BaseModel):
    """Response model for complete travel plan with enhanced route data"""
    success: bool
    message: str
    trip_summary: Optional[str] = None
    weather: Optional[List[WeatherInfo]] = None
    weather_summary: Optional[str] = None
    route: Optional[RouteData] = None  # CHANGED: Now uses RouteData instead of RouteInfo
    budget: Optional[BudgetBreakdown] = None
    itinerary: Optional[List[ItineraryDay]] = None
    errors: List[str] = []
    processing_time: Optional[float] = None


class WeatherResponse(BaseModel):
    """Response model for weather data"""
    success: bool
    data: Optional[List[WeatherInfo]] = None
    weather_summary: Optional[str] = None
    error: Optional[str] = None


class RouteResponse(BaseModel):
    """Response model for enhanced route data"""
    success: bool
    data: Optional[RouteData] = None  # CHANGED: Now uses RouteData
    error: Optional[str] = None


class BudgetResponse(BaseModel):
    """Response model for budget data"""
    success: bool
    data: Optional[BudgetBreakdown] = None
    error: Optional[str] = None


class ItineraryResponse(BaseModel):
    """Response model for itinerary data"""
    success: bool
    data: Optional[List[ItineraryDay]] = None
    error: Optional[str] = None


class HealthResponse(BaseModel):
    """Response model for health check"""
    status: str
    timestamp: str
    version: str = "1.0.0"


class ErrorResponse(BaseModel):
    """Standard error response"""
    success: bool = False
    error: str
    details: Optional[Dict[str, Any]] = None


class StatusResponse(BaseModel):
    """Response model for system status"""
    status: str
    timestamp: str
    agents: Dict[str, str]
    available_features: List[str]


class EventResponse(BaseModel):
    """Response model for event data from OpenWeb Ninja API"""
    success: bool
    location: Optional[str] = None
    dates: Optional[List[str]] = None
    events_count: Optional[int] = None
    data: Optional[List[EventInfo]] = None
    error: Optional[str] = None
    request_id: Optional[str] = None
    processing_time: Optional[float] = None


class EventSearchResponse(BaseModel):
    """Response model for event search with OpenWeb Ninja"""
    success: bool
    query: Optional[str] = None
    location: Optional[str] = None
    date_filter: Optional[str] = None
    events_count: Optional[int] = None
    data: Optional[List[EventInfo]] = None
    error: Optional[str] = None
    request_id: Optional[str] = None
    has_more_results: Optional[bool] = None


class PopularEventsResponse(BaseModel):
    """Response model for popular events"""
    success: bool
    location: Optional[str] = None
    events_count: Optional[int] = None
    days_ahead: Optional[int] = None
    data: Optional[List[EventInfo]] = None
    error: Optional[str] = None
    categories_found: Optional[List[str]] = None


class EventCategoriesResponse(BaseModel):
    """Response model for event categories"""
    success: bool
    categories: Optional[List[str]] = None
    descriptions: Optional[Dict[str, str]] = None
    date_filters: Optional[List[str]] = None
    error: Optional[str] = None
    
    class Config:
        schema_extra = {
            "example": {
                "success": True,
                "categories": [
                    "music", "sports", "arts", "theatre", "comedy",
                    "family", "business", "food", "film", "miscellaneous"
                ],
                "descriptions": {
                    "music": "Concerts, festivals, live performances",
                    "sports": "Games, matches, tournaments, competitions",
                    "arts": "Exhibitions, galleries, art shows",
                    "theatre": "Plays, musicals, theatrical performances",
                    "comedy": "Stand-up comedy, comedy shows",
                    "family": "Family-friendly events and activities",
                    "business": "Conferences, seminars, networking",
                    "food": "Food festivals, wine tastings, culinary events",
                    "film": "Movie screenings, film festivals",
                    "miscellaneous": "Other events and activities"
                },
                "date_filters": [
                    "any", "today", "tomorrow", "week", 
                    "weekend", "next_week", "month", "next_month"
                ]
            }
        }


class EventDetailsResponse(BaseModel):
    """Response model for specific event details"""
    success: bool
    event_id: Optional[str] = None
    data: Optional[EventInfo] = None
    error: Optional[str] = None
    venue_details: Optional[Dict[str, Any]] = None
    ticket_sources: Optional[List[Dict[str, str]]] = None
    info_sources: Optional[List[Dict[str, str]]] = None


class VirtualEventsResponse(BaseModel):
    """Response model for virtual events"""
    success: bool
    query: Optional[str] = None
    events_count: Optional[int] = None
    data: Optional[List[EventInfo]] = None
    error: Optional[str] = None
    total_virtual_events: Optional[int] = None