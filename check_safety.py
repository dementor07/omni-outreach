import asyncio
from app.db import init_pool, fetch_all, close_pool, system_scope

async def main():
    await init_pool()
    async with system_scope():
        # Check connections
        conns = await fetch_all('SELECT provider, name, capabilities, is_healthy FROM omni_connections')
        print('Connections:')
        for c in conns:
            print(f"  - {c['provider']} / {c['name']} / {c.get('capabilities')} / healthy: {c.get('is_healthy')}")
        
        # Check active workflows for outbound messaging
        nodes = await fetch_all("""
            SELECT n.node_type, n.workflow_id, w.status 
            FROM omni_workflow_nodes n 
            JOIN omni_workflows w ON n.workflow_id = w.id
            WHERE w.status = 'active' AND n.node_type LIKE 'channel.%'
        """)
        print('\nActive outbound nodes:')
        for n in nodes:
            print(f"  - Workflow {n['workflow_id']} ({n['status']}): {n['node_type']}")

    await close_pool()

asyncio.run(main())
