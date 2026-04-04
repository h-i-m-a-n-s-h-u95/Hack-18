from typing import Dict, List, Any, Optional, TypedDict
from pydantic import BaseModel, Field
from datetime import datetime, date
from enum import Enum
import json
import uuid
from app.messaging.redis_client import get_redis_client, RedisChannels
from app.messaging import redis_client


class AgentStatus(str, Enum):
    """Status of individual agents"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


class WorkflowStatus(str, Enum):
    """Overall workflow status"""
    INITIALIZED = "initialized"
    ROUTING = "routing"
    FETCHING = "fetching"
    VALIDATING = "validating"
    SYNTHESIZING = "synthesizing"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


class AirPollutionInfo(BaseModel):
    aqi: Optional[float] = None
    co: Optional[float] = None
    no: Optional[float] = None
    no2: Optional[float] = None
    o3: Optional[float] = None
    so2: Optional[float] = None
    pm2_5: Optional[float] = None
    pm10: Optional[float] = None
    nh3: Optional[float] = None


class WeatherInfo(BaseModel):
    """Weather information structure"""
    date: str
    temperature_max: float
    temperature_min: float
    description: str
    humidity: int
    wind_speed: float
    precipitation_chance: int
    air_pollution: Optional[AirPollutionInfo] = None


class RouteInfo(BaseModel):
    """Route information structure"""
    distance: str
    duration: str
    steps: List[str]
    traffic_info: Optional[str] = None
    transport_mode: str = "driving"


class RouteData(BaseModel):
    """Enhanced route data structure with all transport modes and options"""
    primary_route: Optional[Dict[str, Any]] = None
    alternative_routes: Optional[Dict[str, Dict[str, Any]]] = None  # mode -> RouteInfo dict
    route_analysis: Optional[str] = None
    recommended_mode: Optional[str] = None
    comparison: Optional[Dict[str, Dict[str, str]]] = None
    origin: Optional[str] = None
    destination: Optional[str] = None
    travel_options: Optional[Dict[str, Any]] = None  # flights, trains, buses, hotels


class BudgetBreakdown(BaseModel):
    """Budget breakdown structure"""
    transportation: float
    accommodation: float
    food: float
    activities: float
    total: float
    currency: str = "USD"


class ItineraryDay(BaseModel):
    """Single day itinerary structure"""
    day: int
    date: str
    activities: List[str]
    notes: str
    estimated_cost: float


class EventInfo(BaseModel):
    """Event information data class"""
    name: str
    date: str  # YYYY-MM-DD format
    time: str  # HH:MM format
    venue: str
    address: str
    category: str
    price_min: Optional[float] = None
    price_max: Optional[float] = None
    currency: str = "USD"
    description: str = ""
    url: str = ""
    image_url: Optional[str] = None
    
    @property
    def price_range(self) -> str:
        """Get formatted price range"""
        if self.price_min is None and self.price_max is None:
            return "Price TBA"
        elif self.price_min == 0:
            return "Free"
        elif self.price_min == self.price_max:
            return f"{self.currency} {self.price_min}"
        else:
            return f"{self.currency} {self.price_min}-{self.price_max}"


class AgentMetadata(BaseModel):
    """Metadata for agent execution tracking"""
    agent_name: str
    status: AgentStatus = AgentStatus.PENDING
    request_id: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    retry_count: int = 0
    error_message: Optional[str] = None
    timeout_ms: int = 30000


class UserPreferences(BaseModel):
    """User preferences and constraints"""
    interests: List[str] = Field(default_factory=list)  # e.g., ["art", "music", "food"]
    pace: str = "moderate"  # relaxed, moderate, packed
    dietary_restrictions: List[str] = Field(default_factory=list)
    accessibility_needs: List[str] = Field(default_factory=list)
    group_type: str = "solo"  # solo, couple, family, friends


class TravelState(TypedDict):
    """Enhanced shared state across all agents with session management"""
    
    # Session Management
    session_id: str
    workflow_status: WorkflowStatus
    created_at: str  # ISO format
    updated_at: str  # ISO format
    
    # Input Parameters
    destination: str
    origin: str
    travel_dates: List[str]
    travelers_count: int
    budget_range: Optional[str]
    user_preferences: Optional[Dict[str, Any]]  # Serialized UserPreferences
    include_travel_options: bool  # NEW: Whether to fetch flights, trains, etc.
    
    # Agent Execution Tracking
    agent_status: Dict[str, Dict[str, Any]]  # agent_name -> AgentMetadata dict
    agents_to_execute: List[str]  # Dynamic list based on routing
    
    # Agent Outputs
    weather_data: Optional[List[Dict[str, Any]]]  # Serialized WeatherInfo list
    weather_summary: Optional[str]  # NEW: Weather summary text
    events_data: Optional[List[Dict[str, Any]]]  # Serialized EventInfo list
    route_data: Optional[Dict[str, Any]]  # ENHANCED: Now contains full RouteData structure
    budget_data: Optional[Dict[str, Any]]  # Serialized BudgetBreakdown
    itinerary_data: Optional[List[Dict[str, Any]]]  # Serialized ItineraryDay list
    
    # Completion Flags (for backward compatibility)
    weather_complete: bool
    events_complete: bool
    maps_complete: bool
    budget_complete: bool
    itinerary_complete: bool
    
    # Communication
    messages: List[str]
    errors: List[str]
    streaming_updates: List[Dict[str, Any]]  # For real-time updates
    
    # Final Output
    trip_summary: Optional[str]
    final_itinerary: Optional[str]
    
    # Metadata
    total_agents: int
    completed_agents: int
    failed_agents: int


def create_initial_state(
    destination: str,
    origin: str,
    travel_dates: List[str],
    travelers_count: int = 1,
    budget_range: Optional[str] = None,
    user_preferences: Optional[UserPreferences] = None,
    session_id: Optional[str] = None,
    include_travel_options: bool = False
) -> TravelState:
    """Create initial state for the travel planning workflow"""
    
    if session_id is None:
        session_id = str(uuid.uuid4())
    
    now = datetime.utcnow().isoformat()
    
    # Initialize agent metadata
    agent_names = ["weather", "events", "maps", "budget", "itinerary"]
    agent_status = {}
    for agent_name in agent_names:
        agent_status[agent_name] = AgentMetadata(
            agent_name=agent_name,
            status=AgentStatus.PENDING,
            timeout_ms=get_agent_timeout(agent_name)
        ).dict()
    
    return TravelState(
        # Session
        session_id=session_id,
        workflow_status=WorkflowStatus.INITIALIZED,
        created_at=now,
        updated_at=now,
        
        # Input
        destination=destination,
        origin=origin,
        travel_dates=travel_dates,
        travelers_count=travelers_count,
        budget_range=budget_range,
        user_preferences=user_preferences.dict() if user_preferences else None,
        include_travel_options=include_travel_options,
        
        # Agent Tracking
        agent_status=agent_status,
        agents_to_execute=agent_names[:4],  # Don't include itinerary initially
        
        # Outputs
        weather_data=None,
        weather_summary=None,
        events_data=None,
        route_data=None,  # Will store full RouteData structure
        budget_data=None,
        itinerary_data=None,
        
        # Flags
        weather_complete=False,
        events_complete=False,
        maps_complete=False,
        budget_complete=False,
        itinerary_complete=False,
        
        # Communication
        messages=[],
        errors=[],
        streaming_updates=[],
        
        # Final
        trip_summary=None,
        final_itinerary=None,
        
        # Metadata
        total_agents=5,
        completed_agents=0,
        failed_agents=0
    )


def get_agent_timeout(agent_name: str) -> int:
    """Get timeout in milliseconds for each agent"""
    timeouts = {
        "weather": 100000,   # 100s
        "events": 150000,    # 150s
        "maps": 120000,      # 120s (increased for travel options)
        "budget": 80000,     # 80s
        "itinerary": 200000  # 200s
    }
    return timeouts.get(agent_name, 30000)


def update_agent_status(
    state: TravelState,
    agent_name: str,
    status: AgentStatus,
    error_message: Optional[str] = None,
    request_id: Optional[str] = None
) -> TravelState:
    """Update the status of a specific agent"""
    
    agent_meta = state["agent_status"][agent_name]
    agent_meta["status"] = status.value
    agent_meta["updated_at"] = datetime.utcnow().isoformat()
    
    # Store request_id if provided
    if request_id is not None:
        agent_meta["request_id"] = request_id
    
    if status == AgentStatus.PROCESSING and agent_meta["started_at"] is None:
        agent_meta["started_at"] = datetime.utcnow().isoformat()
    
    if status in [AgentStatus.COMPLETED, AgentStatus.FAILED, AgentStatus.TIMEOUT]:
        agent_meta["completed_at"] = datetime.utcnow().isoformat()
        if agent_meta["started_at"]:
            started = datetime.fromisoformat(agent_meta["started_at"])
            completed = datetime.fromisoformat(agent_meta["completed_at"])
            agent_meta["duration_ms"] = int((completed - started).total_seconds() * 1000)
        
        if status == AgentStatus.COMPLETED:
            state["completed_agents"] += 1
        elif status == AgentStatus.FAILED:
            state["failed_agents"] += 1
    
    if error_message:
        agent_meta["error_message"] = error_message
        state["errors"].append(f"[{agent_name}] {error_message}")
    
    state["updated_at"] = datetime.utcnow().isoformat()
    
    return state


async def add_streaming_update(
    session_id: str,
    agent_name: str,
    data: Dict[str, Any],
    state: TravelState = None
) -> None:
    """
    Send a streaming update to the frontend via Redis and optionally store in state.
    
    Args:
        session_id: The current session ID
        agent_name: Name of the agent sending the update
        data: Payload data to stream
        state: Optional TravelState to also store update locally
    """
    update = {
        "timestamp": datetime.utcnow().isoformat(),
        "agent": agent_name,
        "data": data
    }

    # Append to state if provided (for history/logging)
    if state is not None:
        state["streaming_updates"].append(update)

    # Publish to Redis for real-time frontend streaming
    redis_instance = get_redis_client()
    await redis_instance.publish(
        RedisChannels.get_streaming_channel(session_id),
        update
    )


def is_workflow_complete(state: TravelState) -> bool:
    """Check if all required agents have completed"""
    required_agents = ["weather", "events", "maps", "budget"]
    return all(
        state["agent_status"][agent]["status"] == AgentStatus.COMPLETED.value
        for agent in required_agents
    )


def serialize_state_for_redis(state: TravelState) -> str:
    """Serialize state to JSON for Redis storage"""
    return json.dumps(state, default=str)


def deserialize_state_from_redis(state_json: str) -> TravelState:
    """Deserialize state from Redis JSON"""
    return json.loads(state_json)


def get_route_summary(state: TravelState) -> Optional[str]:
    """Extract route summary from state for quick access"""
    if not state.get("route_data"):
        return None
    
    route_data = state["route_data"]
    primary = route_data.get("primary_route")
    
    if not primary:
        return None
    
    distance = primary.get("distance", "Unknown")
    duration = primary.get("duration", "Unknown")
    mode = route_data.get("recommended_mode", primary.get("transport_mode", "driving"))
    
    return f"{distance} in {duration} by {mode}"


def has_travel_options(state: TravelState) -> bool:
    """Check if state contains travel options data"""
    if not state.get("route_data"):
        return False
    
    return "travel_options" in state["route_data"]