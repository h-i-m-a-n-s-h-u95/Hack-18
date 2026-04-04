# ============================================
# REQUEST SCHEMAS
# ============================================

from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Dict, Any
from datetime import date, datetime
from app.core.state import EventInfo, WeatherInfo, RouteInfo, RouteData, BudgetBreakdown, ItineraryDay


class TravelPlanRequest(BaseModel):
    """Request model for travel planning"""
    destination: str = Field(..., description="Travel destination")
    origin: str = Field(..., description="Starting location")
    travel_dates: List[str] = Field(..., description="List of travel dates in YYYY-MM-DD format")
    travelers_count: int = Field(1, ge=1, le=20, description="Number of travelers")
    budget_range: Optional[str] = Field(None, description="Budget range (e.g., 'low', 'medium', 'high')")
    preferences: Optional[str] = Field(None, description="Additional preferences or requirements")
    include_travel_options: bool = Field(False, description="Include flights, trains, buses, and hotels")
    
    @field_validator('travel_dates')
    def validate_dates(cls, v):
        """Validate date format and ensure dates are in the future"""
        if not v:
            raise ValueError("At least one travel date is required")
        
        validated_dates = []
        for date_str in v:
            try:
                # Parse the date to ensure it's valid
                parsed_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                
                # Check if date is not in the past
                if parsed_date < date.today():
                    raise ValueError(f"Travel date {date_str} cannot be in the past")
                
                validated_dates.append(date_str)
            except ValueError as e:
                if "does not match format" in str(e):
                    raise ValueError(f"Invalid date format: {date_str}. Use YYYY-MM-DD format")
                raise e
        
        return validated_dates
    
    @field_validator('destination', 'origin')
    def validate_locations(cls, v):
        """Validate location strings"""
        if not v or len(v.strip()) < 2:
            raise ValueError("Location must be at least 2 characters long")
        return v.strip()


class WeatherRequest(BaseModel):
    """Request model for weather service"""
    location: str
    dates: List[str]


class RouteRequest(BaseModel):
    """Request model for enhanced route planning"""
    origin: str
    destination: str
    transport_mode: str = Field("driving", description="Primary transport mode")
    include_alternatives: bool = Field(True, description="Include alternative transport modes")
    include_travel_options: bool = Field(False, description="Include flights, trains, buses, hotels")
    travel_date: Optional[str] = Field(None, description="Travel date for flights/trains (YYYY-MM-DD)")
    checkin_date: Optional[str] = Field(None, description="Hotel check-in date (YYYY-MM-DD)")
    checkout_date: Optional[str] = Field(None, description="Hotel check-out date (YYYY-MM-DD)")
    
    @field_validator('transport_mode')
    def validate_transport_mode(cls, v):
        """Validate transport mode"""
        valid_modes = ["driving", "walking", "cycling", "public_transport"]
        if v not in valid_modes:
            raise ValueError(f"Invalid transport mode. Must be one of: {valid_modes}")
        return v


class BudgetRequest(BaseModel):
    """Request model for budget estimation"""
    destination: str
    origin: str
    travel_dates: List[str]
    travelers_count: int
    budget_range: Optional[str] = None


class EventRequest(BaseModel):
    """Request model for event information using OpenWeb Ninja API"""
    location: str = Field(..., description="Location name for event search")
    dates: List[str] = Field(..., description="List of dates in YYYY-MM-DD format")
    categories: Optional[List[str]] = Field(None, description="Event categories to filter by")
    limit: Optional[int] = Field(20, ge=1, le=100, description="Maximum number of events to return")
    is_virtual: Optional[bool] = Field(False, description="Include only virtual events")
    
    @field_validator('dates')
    def validate_dates(cls, v):
        """Validate date format"""
        for date_str in v:
            try:
                date.fromisoformat(date_str)
            except ValueError:
                raise ValueError(f"Invalid date format: {date_str}. Use YYYY-MM-DD format.")
        return v
    
    @field_validator('categories')
    def validate_categories(cls, v):
        """Validate event categories"""
        if v is None:
            return v
        
        valid_categories = [
            "music", "sports", "arts", "theatre", "comedy", 
            "family", "business", "food", "film", "miscellaneous"
        ]
        
        for category in v:
            if category.lower() not in valid_categories:
                raise ValueError(f"Invalid category: {category}. Must be one of: {valid_categories}")
        
        return [cat.lower() for cat in v]


class EventSearchRequest(BaseModel):
    """Request model for event search with OpenWeb Ninja date filters"""
    query: str = Field(..., description="Search query for events")
    location: Optional[str] = Field(None, description="Location to search in")
    date_filter: Optional[str] = Field("any", description="Date filter for events")
    is_virtual: Optional[bool] = Field(False, description="Include only virtual events")
    limit: Optional[int] = Field(20, ge=1, le=100, description="Maximum events to return")
    
    @field_validator('date_filter')
    def validate_date_filter(cls, v):
        """Validate OpenWeb Ninja date filter"""
        valid_filters = [
            "any", "today", "tomorrow", "week", 
            "weekend", "next_week", "month", "next_month"
        ]
        
        if v.lower() not in valid_filters:
            raise ValueError(f"Invalid date filter: {v}. Must be one of: {valid_filters}")
        
        return v.lower()


class EventCategorySearchRequest(BaseModel):
    """Request model for event search by category with date range"""
    location: str = Field(..., description="Location name")
    category: str = Field(..., description="Event category")
    start_date: str = Field(..., description="Start date in YYYY-MM-DD format")
    end_date: str = Field(..., description="End date in YYYY-MM-DD format")
    limit: Optional[int] = Field(20, ge=1, le=100, description="Maximum events to return")
    is_virtual: Optional[bool] = Field(False, description="Include only virtual events")
    
    @field_validator('start_date', 'end_date')
    def validate_date_format(cls, v):
        """Validate date format"""
        try:
            date.fromisoformat(v)
        except ValueError:
            raise ValueError(f"Invalid date format: {v}. Use YYYY-MM-DD format.")
        return v
    
    @field_validator('category')
    def validate_category(cls, v):
        """Validate event category"""
        valid_categories = [
            "music", "sports", "arts", "theatre", "comedy", 
            "family", "business", "food", "film", "miscellaneous"
        ]
        
        if v.lower() not in valid_categories:
            raise ValueError(f"Invalid category: {v}. Must be one of: {valid_categories}")
        
        return v.lower()


class PopularEventsRequest(BaseModel):
    """Request model for popular events"""
    location: str = Field(..., description="Location name")
    days_ahead: Optional[int] = Field(30, ge=1, le=365, description="Number of days to look ahead")
    limit: Optional[int] = Field(10, ge=1, le=50, description="Maximum events to return")
    categories: Optional[List[str]] = Field(None, description="Event categories to include")
    is_virtual: Optional[bool] = Field(False, description="Include virtual events")
    
    @field_validator('categories')
    def validate_categories(cls, v):
        """Validate event categories"""
        if v is None:
            return v
        
        valid_categories = [
            "music", "sports", "arts", "theatre", "comedy", 
            "family", "business", "food", "film", "miscellaneous"
        ]
        
        for category in v:
            if category.lower() not in valid_categories:
                raise ValueError(f"Invalid category: {category}. Must be one of: {valid_categories}")
        
        return [cat.lower() for cat in v]


class EventDetailsRequest(BaseModel):
    """Request model for getting specific event details"""
    event_id: str = Field(..., description="OpenWeb Ninja event ID")
    
    @field_validator('event_id')
    def validate_event_id(cls, v):
        """Validate event ID format"""
        if not v or len(v) < 10:
            raise ValueError("Invalid event ID format")
        return v


class VirtualEventsRequest(BaseModel):
    """Request model for virtual events only"""
    query: str = Field(..., description="Search query for virtual events")
    date_filter: Optional[str] = Field("any", description="Date filter")
    limit: Optional[int] = Field(20, ge=1, le=100, description="Maximum events to return")
    categories: Optional[List[str]] = Field(None, description="Event categories to filter by")
    
    @field_validator('date_filter')
    def validate_date_filter(cls, v):
        """Validate date filter"""
        valid_filters = [
            "any", "today", "tomorrow", "week", 
            "weekend", "next_week", "month", "next_month"
        ]
        
        if v.lower() not in valid_filters:
            raise ValueError(f"Invalid date filter: {v}. Must be one of: {valid_filters}")
        
        return v.lower()
    
    @field_validator('categories')
    def validate_categories(cls, v):
        """Validate categories"""
        if v is None:
            return v
        
        valid_categories = [
            "music", "sports", "arts", "theatre", "comedy", 
            "family", "business", "food", "film", "miscellaneous"
        ]
        
        for category in v:
            if category.lower() not in valid_categories:
                raise ValueError(f"Invalid category: {category}. Must be one of: {valid_categories}")
        
        return [cat.lower() for cat in v]
