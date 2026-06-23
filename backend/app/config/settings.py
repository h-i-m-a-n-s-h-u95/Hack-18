from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # Google AI (Groq)
    groq_api_key: Optional[str] = None

    # Weather API (OpenWeather)
    openweather_api_key: Optional[str] = None

    # Maps API (OpenRouteService)
    openroute_api_key: Optional[str] = None

    # Google Places API (for attraction discovery and geo-optimization)
    google_places_api_key: Optional[str] = None

    # RapidAPI — field covers both RAPIDAPI_KEY and RAPIDAPI_API_KEY in .env
    rapidapi_api_key: Optional[str] = None

    # property-style alias so existing code using settings.rapidapi_key still works
    @property
    def rapidapi_key(self) -> Optional[str]:
        return self.rapidapi_api_key

    # Events API (OpenWeb Ninja)
    openweb_ninja_api_key: Optional[str] = None
    openweb_ninja_base_url: str = "https://api.openwebninja.com/realtime-events-data/search-events"
    openweb_ninja_timeout: float = 30.0

    # Travel Options API Hosts (RapidAPI)
    skyscanner_host: str = "skyscanner-flights-travel-api.p.rapidapi.com"
    trains_host: str = "irctc1.p.rapidapi.com"
    tripgo_host: str = "skedgo-tripgo-v1.p.rapidapi.com"
    hotels_host: str = "booking-com.p.rapidapi.com"

    # Redis Configuration
    redis_url: str = "redis://localhost:6379"   # overridden by REDIS_URL in .env
    redis_max_connections: int = 50
    redis_socket_timeout: int = 5
    redis_health_check_interval: int = 30

    # State Management
    state_ttl_seconds: int = 3600
    state_extend_on_activity: bool = True

    # App Configuration
    app_name: str = "TBuddy"
    debug: bool = True
    host: str = "localhost"
    port: int = 8010

    # Model Configuration
    model_name: str = "llama-3.3-70b-versatile"
    temperature: float = 0.1
    max_tokens: Optional[int] = None

    # Agent Timeout Configuration (milliseconds)
    timeout_weather: int = 100000
    timeout_events: int = 150000
    timeout_maps: int = 120000
    timeout_budget: int = 80000
    timeout_itinerary: int = 200000

    # Orchestrator Configuration
    max_parallel_agents: int = 4
    agent_retry_attempts: int = 2
    orchestrator_timeout: int = 600000

    # MCP (Model Context Protocol) Configuration
    mcp_enabled: bool = False
    mcp_server_url: str = "http://mcp-server:9000/sse"

    # Streaming Configuration
    streaming_enabled: bool = True
    streaming_chunk_delay_ms: int = 100

    # Worker Configuration
    worker_concurrency: int = 10
    worker_heartbeat_interval: int = 30

    # Event Service Configuration
    events_fallback_enabled: bool = True
    events_cache_ttl: int = 3600
    events_max_results: int = 100
    events_default_days_ahead: int = 30

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"          # unknown .env keys are silently skipped


# Global settings instance
settings = Settings()