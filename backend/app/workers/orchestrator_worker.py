"""
Orchestrator Worker
Runs the orchestrator agent as a standalone service
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from app.agents.orchestrator_agent import OrchestratorAgent
from app.messaging.redis_client import get_redis_client
from app.config.settings import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


async def main():
    """Main entry point for orchestrator worker"""
    logger.info("=" * 60)
    logger.info("🎪 ORCHESTRATOR WORKER STARTING")
    logger.info("=" * 60)
    
    # Get Redis client
    redis_client = get_redis_client()
    
    try:
        # Connect to Redis
        await redis_client.connect()
        logger.info(f"✅ Connected to Redis at {settings.redis_url}")
        
        # Note: Orchestrator doesn't subscribe to channels like other agents
        # It's used via HTTP/WebSocket API calls
        # We just keep it running and ready
        
        logger.info("✅ Orchestrator Worker is ready!")
        logger.info(f"   Model: {settings.model_name}")
        logger.info(f"   Redis URL: {settings.redis_url}")
        logger.info("\n🎯 Orchestrator is ready to coordinate agents")
        logger.info("   Access via API: http://localhost:8000/api/v1/orchestrator")
        logger.info("\nPress Ctrl+C to stop...")
        
        # Keep the worker running
        while True:
            await asyncio.sleep(60)
            logger.debug("Orchestrator worker heartbeat")
            
    except KeyboardInterrupt:
        logger.info("\n\n🛑 Shutting down Orchestrator Worker...")
    except Exception as e:
        logger.error(f"❌ Orchestrator worker failed: {e}", exc_info=True)
        sys.exit(1)
    finally:
        await redis_client.disconnect()
        logger.info("✅ Orchestrator Worker stopped")


if __name__ == "__main__":
    asyncio.run(main())