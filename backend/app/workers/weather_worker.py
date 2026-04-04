"""
Weather Worker - Runs WeatherAgent as a standalone service

This worker:
1. Creates a WeatherAgent instance
2. Wraps it in BaseWorker for Redis pub/sub handling
3. Listens to weather requests on Redis channel
4. Processes requests using WeatherAgent.handle_request()
5. Publishes responses back to orchestrator
"""

import asyncio
import sys
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.agents.weather_agent import WeatherAgent
from app.messaging.protocols import AgentType
from app.messaging.redis_client import get_redis_client
from app.workers.base_worker import run_worker
from app.config.settings import settings

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


async def main():
    """Run the weather worker"""
    logger.info("=" * 60)
    logger.info("🌤️  WEATHER WORKER STARTING")
    logger.info("=" * 60)
    
    try:
        # Get Redis client
        redis_client = get_redis_client()
        
        # Create weather agent instance with correct parameters
        agent = WeatherAgent(
            redis_client=redis_client,
            gemini_api_key=settings.google_api_key,
            model_name=settings.model_name
        )
        
        logger.info(f"Agent created: {agent.name}")
        logger.info(f"Agent type: {agent.agent_type.value}")
        logger.info(f"Ready to process weather requests...")
        
        # Run worker (this will block until shutdown signal)
        await run_worker(agent, AgentType.WEATHER)
        
    except KeyboardInterrupt:
        logger.info("\n🛑 Weather worker stopped by user")
    except Exception as e:
        logger.error(f"❌ Weather worker failed: {str(e)}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")