# Omni Architecture Roadmap (TODO)

1. **[COMPLETED] Instagram & Telegram Integrations**: Update `dispatcher.py` to properly fetch provider/attendee IDs and dispatch messages via Unipile for IG and TG nodes.
2. **[COMPLETED] Event Bus Implementation**: Migrate webhook handling from synchronous Postgres inserts to Redis Streams.
3. **[ACTIVE] Lead Generation Pipeline**: Build the Apify+Serper orchestration loop to auto-inject leads.
4. **[PENDING] Canvas Telemetry Overlay**: Add WebSocket/SSE throughput data to React Flow edges.
5. **[PENDING] Auto-Optimization Engine**: Build the Reinforcement Learning loop for A/B Split nodes.