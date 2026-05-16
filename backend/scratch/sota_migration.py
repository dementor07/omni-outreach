import asyncio

from app.db import execute


async def migrate():
    print("Running SOTA Migration: Creating stream_log table...")
    await execute("""
        CREATE TABLE IF NOT EXISTS stream_log (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            event_type TEXT NOT NULL,
            payload JSONB NOT NULL,
            occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    print("Migration complete.")

if __name__ == "__main__":
    asyncio.run(migrate())
