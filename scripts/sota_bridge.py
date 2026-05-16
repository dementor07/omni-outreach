import asyncio
import logging
from uuid import uuid4
from app.db import fetch_all, execute
from app.core.events import ActionCommand, LeadContext, ChannelType
from app.services.bus import bus

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("sota-bridge")

async def migrate_legacy_queue():
    """
    The 'Strangler Bridge'
    Moves legacy tasks from Postgres 'queue' to the Redpanda 'outreach.commands' topic.
    """
    log.info("Starting SOTA Migration Bridge...")
    
    # 1. Fetch all pending tasks from the legacy queue
    legacy_tasks = await fetch_all(
        "SELECT q.*, l.email, l.linkedin_url, l.first_name, l.company "
        "FROM queue q JOIN leads l ON l.id = q.lead_id "
        "WHERE q.status = 'queued' AND q.scheduled_at <= NOW()"
    )
    
    log.info(f"Found {len(legacy_tasks)} tasks to migrate.")

    for task in legacy_tasks:
        try:
            # 2. Map Legacy Channel to SOTA ChannelType
            channel_str = task['channel']
            try:
                channel = ChannelType(channel_str)
            except ValueError:
                log.warning(f"Skipping unknown channel: {channel_str}")
                continue

            # 3. Construct the SOTA Command
            command = ActionCommand(
                command_id=uuid4(),
                task_id=task['id'],
                channel=channel,
                lead=LeadContext(
                    id=task['lead_id'],
                    campaign_id=task['campaign_id'],
                    email=task.get('email'),
                    linkedin_url=task.get('linkedin_url'),
                    first_name=task.get('first_name'),
                    company=task.get('company')
                ),
                payload=task.get('payload') or {},
                metadata={"migration": "strangler_fig_v1"}
            )

            # 4. Publish to the SOTA Bus
            await bus.publish_command(command)

            # 5. Mark as Migrated in Legacy DB
            await execute(
                "UPDATE queue SET status = 'migrated', locked_by = 'sota-bridge' WHERE id = $1",
                task['id']
            )

        except Exception as e:
            log.error(f"Failed to migrate task {task['id']}: {e}")

    log.info("Migration Bridge execution complete.")

if __name__ == "__main__":
    asyncio.run(migrate_legacy_queue())
