import asyncio
import asyncpg

async def main():
    conn = await asyncpg.connect('postgresql://outreach:OmniOutreach2026@db:5432/outreach')
    
    rolbypassrls = await conn.fetchval("SELECT rolbypassrls FROM pg_roles WHERE rolname = 'outreach'")
    print(f"outreach rolbypassrls: {rolbypassrls}")
    
    await conn.close()

asyncio.run(main())
