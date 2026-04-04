"""
Events Worker - Runs EventsAgent as a standalone service

File: app/workers/events_worker.py

Usage:
    python -m app.workers.events_worker
"""

import asyncio
import sys
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.agents.event_agent import EventsAgent
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
    """Run the events worker"""
    logger.info("=" * 60)
    logger.info("🎉 EVENTS WORKER STARTING")
    logger.info("=" * 60)
    
    try:
        # Get Redis client
        redis_client = get_redis_client()
        
        # Create events agent instance with correct parameters
        agent = EventsAgent(
            redis_client=redis_client,
            gemini_api_key=settings.google_api_key,
            model_name=settings.model_name
        )
        
        logger.info(f"Agent created: {agent.name}")
        logger.info(f"Agent type: {agent.agent_type.value}")
        logger.info(f"Ready to process events requests...")
        
        # Run worker (this will block until shutdown signal)
        await run_worker(agent, AgentType.EVENTS)
        
    except KeyboardInterrupt:
        logger.info("\n🛑 Events worker stopped by user")
    except Exception as e:
        logger.error(f"❌ Events worker failed: {str(e)}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")