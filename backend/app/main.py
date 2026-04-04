"""
app/main.py - Updated with API Key Authentication
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import logging
import sys
from datetime import datetime

from app.config.settings import settings
from app.api.orchestrator_routes_v2 import router as orchestrtor_routes_v2
from app.api.api_routes import router as api_key_router
from app.models.response import ErrorResponse
from app.scripts.create_admin_key import router as admin_key_router
from app.messaging.redis_client import get_redis_client
from app.api import orchestrator_routes_v2
from app.auth.middleware import APIKeyAuthMiddleware

# Configure logging
logging.basicConfig(
    level=logging.INFO if not settings.debug else logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for FastAPI app"""
    # Startup
    logger.info(f"🎪 Starting {settings.app_name} v2.0")
    logger.info(f"Debug mode: {settings.debug}")
    
    # Initialize Redis
    try:
        redis_client = get_redis_client()
        await redis_client.connect()
        logger.info("✅ Redis connected")
    except Exception as e:
        logger.error(f"❌ Failed to connect to Redis: {e}")
        raise
    
    # Initialize orchestrator
    try:
        logger.info("🔧 Initializing Orchestrator Agent...")
        await orchestrator_routes_v2.startup()
        logger.info("✅ Orchestrator initialized successfully")
    except Exception as e:
        logger.error(f"❌ Failed to initialize orchestrator: {e}", exc_info=True)
        logger.warning("⚠️ Orchestrator features disabled")
    
    logger.info(f"🚀 API Documentation: http://{settings.host}:{settings.port}/docs")
    logger.info(f"📊 Status endpoint: http://{settings.host}:{settings.port}/status")
    logger.info(f"🔑 API Key Management: http://{settings.host}:{settings.port}/api/v1/keys")
    
    yield
    
    # Shutdown
    logger.info(f"👋 Shutting down {settings.app_name}")
    try:
        await orchestrator_routes_v2.shutdown()
        logger.info("✅ Orchestrator shutdown complete")
    except Exception as e:
        logger.error(f"Error during orchestrator shutdown: {e}")
    
    try:
        redis_client = get_redis_client()
        await redis_client.disconnect()
        logger.info("✅ Redis disconnected")
    except Exception as e:
        logger.error(f"Error disconnecting Redis: {e}")


# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    description="""
    🎪 **Ringmaster Round Table** - AI-Powered Travel Planning System
    
    ## 🔐 Authentication
    All API endpoints (except `/docs`, `/status`, `/health`) require API key authentication.
    
    **How to authenticate:**
    - Include `X-API-Key` header in your requests
    - Create API keys via `/api/v1/keys` endpoint (requires admin key)
    
    ## Features
    - 🤖 Multi-agent orchestration with Redis pub/sub
    - ⚡ Parallel agent execution for faster responses
    - 📡 Real-time streaming updates
    - 🌤️ Weather forecasting
    - 🗺️ Route planning & navigation
    - 🎭 Event discovery
    - 💰 Budget estimation
    - 📅 Itinerary generation
    - 🔑 API Key management with rate limiting
    
    ## API Versions
    - **v2 (Orchestrator)**: `/api/v2/orchestrator/*` - Orchestrated workflow with session memory
    """,
    version="2.0.0",
    debug=settings.debug,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add API Key Authentication Middleware
# Set enforce_auth=False in development if you want to skip auth
enforce_auth = not settings.debug  # Disable auth in debug mode
app.add_middleware(APIKeyAuthMiddleware, enforce_auth=enforce_auth)

if not enforce_auth:
    logger.warning("⚠️ API Key authentication is DISABLED (debug mode)")
else:
    logger.info("🔒 API Key authentication is ENABLED")

# Include routers
app.include_router(orchestrtor_routes_v2, tags=["Orchestrator-v2"])
app.include_router(api_key_router, tags=["API Key Management"])
app.include_router(admin_key_router, tags=["Admin Key Router"])

# Exception handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Handle HTTP exceptions"""
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error=exc.detail if isinstance(exc.detail, str) else str(exc.detail),
            details={"status_code": exc.status_code}
        ).dict()
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Handle general exceptions"""
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="Internal server error",
            details={"message": str(exc) if settings.debug else "An error occurred"}
        ).dict()
    )


@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "app": settings.app_name,
        "version": "2.0.0",
        "status": "running",
        "timestamp": datetime.now().isoformat(),
        "authentication": {
            "enabled": enforce_auth,
            "method": "API Key (X-API-Key header)",
            "key_management": "/api/v1/keys"
        },
        "features": {
            "orchestrated_planning": "Parallel agent execution with Redis",
            "streaming_updates": "Real-time progress notifications",
            "session_memory": "Context-aware follow-up queries",
            "api_key_management": "Secure API key creation and management"
        },
        "endpoints": {
            "orchestrator_v2": {
                "plan": "/api/v2/orchestrator/plan (POST)",
                "status": "/api/v2/orchestrator/plan/{session_id}/status (GET)",
                "result": "/api/v2/orchestrator/session/{session_id}/result (GET)",
                "memory": "/api/v2/orchestrator/session/{session_id}/memory (GET)",
                "history": "/api/v2/orchestrator/session/{session_id}/history (GET)",
                "websocket": "ws://host/api/v2/orchestrator/ws/{session_id}"
            },
            "api_keys": {
                "create": "/api/v1/keys (POST)",
                "list": "/api/v1/keys (GET)",
                "get_my_key": "/api/v1/keys/me (GET)",
                "get_key": "/api/v1/keys/{key_id} (GET)",
                "update": "/api/v1/keys/{key_id} (PATCH)",
                "revoke": "/api/v1/keys/{key_id}/revoke (POST)",
                "delete": "/api/v1/keys/{key_id} (DELETE)",
                "stats": "/api/v1/keys/stats/usage (GET)"
            }
        },
        "docs": "/docs",
        "redoc": "/redoc"
    }


@app.get("/status")
async def status():
    """Enhanced status endpoint with orchestrator and auth information"""
    
    # Check Redis health
    redis_status = "unknown"
    redis_info = {}
    try:
        redis_client = get_redis_client()
        is_healthy = await redis_client.health_check()
        redis_status = "healthy" if is_healthy else "unhealthy"
        redis_info = await redis_client.get_info()
    except Exception as e:
        redis_status = "disconnected"
        redis_info = {"error": str(e)}
    
    return {
        "app_status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "2.0.0",
        "authentication": {
            "enabled": enforce_auth,
            "method": "API Key",
            "header": "X-API-Key"
        },
        "orchestrator": {
            "enabled": redis_status == "healthy",
            "redis_status": redis_status,
            "redis_info": redis_info,
            "workers": {
                "weather": "1 replicas",
                "events": "1 replicas",
                "maps": "1 replicas",
                "budget": "1 replica",
                "itinerary": "1 replica"
            }
        },
        "agents": {
            "weather": {
                "name": "Sky Gazer",
                "status": "active",
                "service": "OpenWeatherMap",
                "capabilities": ["weather forecasts", "climate analysis", "travel recommendations"],
                "timeout": f"{settings.timeout_weather}ms"
            },
            "events": {
                "name": "Buzzfinder",
                "status": "active",
                "service": "OpenWeb Ninja",
                "capabilities": ["event discovery", "venue information", "category filtering"],
                "timeout": f"{settings.timeout_events}ms"
            },
            "maps": {
                "name": "Trailblazer",
                "status": "active",
                "service": "OpenRouteService",
                "capabilities": ["route planning", "transportation comparison", "navigation guidance"],
                "timeout": f"{settings.timeout_maps}ms"
            },
            "budget": {
                "name": "Quartermaster",
                "status": "active",
                "service": "Internal Cost Database",
                "capabilities": ["budget estimation", "cost breakdown", "expense planning"],
                "timeout": f"{settings.timeout_budget}ms"
            },
            "itinerary": {
                "name": "Chronomancer",
                "status": "active",
                "service": "Gemini AI",
                "capabilities": ["day planning", "activity scheduling", "timeline optimization"],
                "timeout": f"{settings.timeout_itinerary}ms"
            }
        },
        "configuration": {
            "model": settings.model_name,
            "temperature": settings.temperature,
            "max_parallel_agents": settings.max_parallel_agents,
            "orchestrator_timeout": f"{settings.orchestrator_timeout}ms",
            "streaming_enabled": settings.streaming_enabled
        }
    }


@app.get("/health")
async def health_check():
    """Simple health check for load balancers"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat()
    }


if __name__ == "__main__":
    import uvicorn
    
    logger.info(f"Starting {settings.app_name}...")
    logger.info(f"OpenWeb Ninja API Key configured: {'Yes' if settings.openweb_ninja_api_key else 'No'}")
    logger.info(f"API Key Authentication: {'Disabled (Debug Mode)' if not enforce_auth else 'Enabled'}")
    
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="info"
    )