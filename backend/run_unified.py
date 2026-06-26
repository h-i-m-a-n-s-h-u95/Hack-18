import asyncio
import logging
import sys
from pathlib import Path
import uvicorn

# Setup path to import from 'app'
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Import settings & utils
from app.config.settings import settings
from app.messaging.redis_client import get_redis_client
from app.messaging.protocols import AgentType
from app.workers.base_worker import BaseWorker

# Import all agents
from app.agents.weather_agent import WeatherAgent
from app.agents.event_agent import EventsAgent
from app.agents.maps_agent import MapsAgent
from app.agents.budget_agent import BudgetAgent
from app.agents.itinerary_agent import ItineraryAgent

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("unified_runner")


async def start_agent_worker(agent_cls, agent_type):
    """Initializes and runs a background agent worker task"""
    logger.info(f"Starting {agent_type.value} worker task...")
    try:
        redis_client = get_redis_client()
        # Connect if not connected
        if not redis_client.is_connected():
            await redis_client.connect()
            
        agent = agent_cls(
            redis_client=redis_client,
            groq_api_key=settings.groq_api_key,
            model_name=settings.model_name
        )
        worker = BaseWorker(agent, agent_type, redis_client)
        await worker.start()
    except asyncio.CancelledError:
        logger.info(f"{agent_type.value} worker task was cancelled.")
    except Exception as e:
        logger.error(f"Error in {agent_type.value} worker task: {e}", exc_info=True)


async def main():
    logger.info("🎪 Starting Unified Runner (FastAPI + Workers in single process)...")
    
    # 1. Start the FastAPI + Uvicorn server in the background
    config = uvicorn.Config(
        "app.main:app", 
        host="0.0.0.0", 
        port=settings.port, 
        log_level="info",
        loop="asyncio"
    )
    server = uvicorn.Server(config)
    
    # Run uvicorn serve as an async task
    server_task = asyncio.create_task(server.serve())
    
    # Give the server and main Redis connection 2 seconds to initialize
    await asyncio.sleep(2)
    
    # 2. Start the background workers inside the same event loop
    workers = [
        start_agent_worker(WeatherAgent, AgentType.WEATHER),
        start_agent_worker(EventsAgent, AgentType.EVENTS),
        start_agent_worker(MapsAgent, AgentType.MAPS),
        start_agent_worker(BudgetAgent, AgentType.BUDGET),
        start_agent_worker(ItineraryAgent, AgentType.ITINERARY),
    ]
    
    worker_tasks = [asyncio.create_task(w) for w in workers]
    
    # Wait for the server task to run/finish
    try:
        await server_task
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Shutdown signal received")
    finally:
        # Clean up background tasks
        logger.info("Stopping all background workers...")
        for task in worker_tasks:
            task.cancel()
        await asyncio.gather(*worker_tasks, return_exceptions=True)
        logger.info("All background workers stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Unified runner stopped.")
