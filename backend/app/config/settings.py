from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Google AI Configuration
    google_api_key:  Optional[str] = None
    
    # Weather API Configuration
    openweather_api_key:  Optional[str] = None

    openroute_api_key:  Optional[str] = None

    rapidapi_key: Optional[str] = None


    openweb_ninja_api_key: Optional[str] = None 
    openweb_ninja_base_url: str = "https://api.openwebninja.com/realtime-events-data/search-events"
    openweb_ninja_timeout: float = 30.0

     # Redis Configuration (Upstash)
    redis_url: str  # Format: redis://default:password@endpoint:port
    redis_max_connections: int = 50
    redis_socket_timeout: int = 5
    redis_health_check_interval: int = 30
    
    # State Management
    state_ttl_seconds: int = 3600  # 1 hour
    state_extend_on_activity: bool = True
    
    
    # App Configuration
    app_name: str = "TBuddy"
    debug: bool = True
    host: str = "localhost"
    port: int = 8000
    
    # Model Configuration
    model_name: str = "gemini-2.5-flash"
    temperature: float = 0.1
    max_tokens: Optional[int] = None

    # Agent Timeout Configuration (milliseconds)
    timeout_weather: int = 100000   # 100 seconds
    timeout_events: int = 150000    # 150 seconds
    timeout_maps: int = 120000      # 120 seconds
    timeout_budget: int = 80000     # 80 seconds
    timeout_itinerary: int = 200000 # 200 seconds
   

        
    # Orchestrator Configuration
    max_parallel_agents: int = 4
    agent_retry_attempts: int = 2
    orchestrator_timeout: int = 600000  # 600 seconds total
    
    # Streaming Configuration
    streaming_enabled: bool = True
    streaming_chunk_delay_ms: int = 100
    
    # Worker Configuration
    worker_concurrency: int = 10  # How many requests each worker handles concurrently
    worker_heartbeat_interval: int = 30  # Seconds between heartbeats
    

    # Event Service Configuration
    events_fallback_enabled: bool = True
    events_cache_ttl: int = 3600  # 1 hour cache
    events_max_results: int = 100
    events_default_days_ahead: int = 30
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# Global settings instance
settings = Settings()