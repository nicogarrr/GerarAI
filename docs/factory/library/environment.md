# Environment

Environment variables, external dependencies, and setup notes.

**What belongs here:** Required env vars, external API keys/services, dependency quirks, platform-specific notes.
**What does NOT belong here:** Service ports/commands (use `services.yaml`).

---

## Required Environment Variables

### LLM/AI
- `OPENCODE_GO_API_KEY`: LLM provider API key (only paid service, user-provided)
- `LLM_SETTINGS_ENCRYPTION_KEY`: Fernet key for encrypting stored API keys
- `LLM_ENABLED`: Enable/disable LLM features
- `CHAT_TOTAL_TIMEOUT_SECONDS`: Max time for chat responses

### Database
- `DATABASE_URL`: PostgreSQL connection string (postgresql://user:pass@host:port/db)
- `REDIS_URL`: Redis connection string (redis://host:port)
- `QDRANT_URL`: Qdrant vector DB URL (http://host:port)

### External Services
- `SEC_USER_AGENT`: User agent for SEC EDGAR API (required)
- `NEXT_PUBLIC_SITE_URL`: Frontend public URL
- `NEXT_PUBLIC_SUPPORT_EMAIL`: Support contact email

### Optional
- `LANGFUSE_ENABLED`: Enable tracing (disabled by default)
- `RETENTION_JOB_ENABLED`: Enable data retention jobs

## External Dependencies

### Free Data Sources
- **SEC EDGAR:** No API key required, must provide User-Agent
- **Yahoo Finance:** Free, no API key
- **Finnhub:** Free tier with API key (registration required)
- **FRED:** Free with API key
- **ECB:** Free, no API key
- **World Bank:** Free, no API key
- **Alpha Vantage:** Free tier 500 req/day with API key
- **Tiingo:** Free tier 500 req/day with API key

### Platform Notes
- **Oracle Cloud Always Free:** 24 GB RAM, 4 OCPU, 200 GB storage (EUR 0/month)
- **Docker on Windows:** May require WSL2 backend
- **Python 3.12:** Required for backend (uv manages virtual env)
