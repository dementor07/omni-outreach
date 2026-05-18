import asyncio
import logging
import sys

from app.config import settings
from app.db import close_pool, fetch_one, init_pool
from app.services import voice

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger(__name__)

TARGET_NUMBER = "+919895537266"


async def main():
    log.info("Starting manual call trigger script...")

    # 1. Initialize DB Connection
    await init_pool(settings.get_asyncpg_dsn())

    try:
        # 2. Fetch an active voice agent
        agent = await fetch_one("SELECT retell_agent_id, name FROM voice_agents WHERE is_active = TRUE LIMIT 1")

        if not agent:
            log.error("No active voice agents found in database. Please provision one in Settings first.")
            return

        log.info(f"Using voice agent: {agent['name']} ({agent['retell_agent_id']})")
        log.info(f"Target number: {TARGET_NUMBER}")

        # 3. Execute the call via Retell AI service
        result = await voice.make_call(
            retell_agent_id=agent["retell_agent_id"],
            phone_number=TARGET_NUMBER,
            metadata={"source": "manual_trigger_script", "triggered_at": asyncio.get_event_loop().time()},
        )

        log.info("Call dispatched successfully!")
        log.info(f"Retell Response: {result}")

    except Exception as e:
        log.exception(f"Failed to trigger call: {e}")
    finally:
        # 4. Cleanup
        await close_pool()
        log.info("Database connection closed.")


if __name__ == "__main__":
    asyncio.run(main())
