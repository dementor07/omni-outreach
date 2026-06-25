import asyncio
import asyncpg

async def main():
    conn = await asyncpg.connect('postgresql://omni:omni@db:5432/outreach')
    await conn.execute('ALTER ROLE outreach NOBYPASSRLS;')
    print("Disabled BYPASSRLS on outreach role")
    await conn.close()

asyncio.run(main())
