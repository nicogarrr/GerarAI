# Arquitectura de GerarAI

> Estado: consolidación de backend completada (agosto 2026; revisado septiembre 2026). La API legacy
> (`data-engine/routers/`) fue retirada del servicio; el único API del data
> engine es el research API bajo el prefijo `/api`.

## 1. Visión general

```
┌────────────────────────── Next.js (frontend) ──────────────────────────┐
│  App Router · Server Actions · better-auth con sesiones en MongoDB      │
│                                                                         │
│  lib/research/client.ts  ── researchRequest(path) ──►  FMP_BACKEND_URL  │
│       │  headers firmados:                                              │
│       │  X-CavaAI-User / X-CavaAI-Tenant / X-CavaAI-Timestamp /        │
│       │  X-CavaAI-Signature (HMAC-SHA256 con RESEARCH_AUTH_SECRET,      │
│       │  tenant = user.id, TTL 300s)                                    │
└───────┼─────────────────────────────────────────────────────────────────┘
        ▼
┌────────────────────────── FastAPI data-engine ─────────────────────────┐
│  main.py · lifespan (seed, model aliases, scheduler si WORKERS_ENABLED) │
│                                                                         │
│  /api/*              research API privado  → auth HMAC → tenant scope   │
│  /api/health         público (sin firma): BD + scheduler + versión      │
│  /health /live /ready liveness/readiness clásicos                       │
│                                                                         │
│  Postgres (DATABASE_URL) — migraciones Alembic (alembic/versions/)      │
│  Worker scheduler (APScheduler → Dramatiq/Redis)                        │
└─────────────────────────────────────────────────────────────────────────┘
```

## 2. Frontend → investigación (identidad y tenant)

- **Sesión**: `better-auth` (`lib/better-auth/auth.ts`) con adaptador MongoDB
  (`@/database/mongoose`). La sesión vive en MongoDB, no en la BD del engine.
- **Puente al backend**: `lib/research/client.ts` (`researchRequest`) firma la
  identidad del usuario autenticado con `RESEARCH_AUTH_SECRET`
  (HMAC-SHA256 sobre `{tenant}:{user}:{timestamp}`) y la envía en los headers
  `X-CavaAI-*`. El navegador nunca construye estos headers: solo el servidor
  Next.js los genera (server actions).
- **Tenant**: el tenant del backend ES el `user.id` de better-auth
  (`lib/auth/research-identity.ts`, `tenantId = user.id`). FastAPI lo valida en
  `app/core/auth.py` (`get_research_principal`) y lo usa para aislar datos por
  tenant en `app/core/database.py` (queries e inserts con scope de tenant).

## 3. FastAPI data-engine

- **Bootstrap** (`main.py`): lifespan arranca seed de company master (no en
  producción), configura aliases de modelos LLM, valida configuración y — si
  `WORKERS_ENABLED=true` — arranca el scheduler de workers.
- **Routers**:
  - Todo el research API vive en `app/api/router.py`, montado en `/api` con
    auth obligatoria (`Depends(get_research_principal)`). Incluye companies,
    portfolio, watchlist, thesis, news, risk, chat, knowledge, screeners, etc.
  - `/api/health` se monta en `main.py` **fuera** del router autenticado y es
    público: `{status, database (SELECT 1), scheduler {enabled, running, jobs,
    last_run_at}, version: "main-<sha corto>"}`.
  - `/health`, `/health/live`, `/health/ready` públicos (liveness/readiness
    clásicos con checks de BD/Redis/Qdrant/MinIO).
- **BD**: Postgres (`postgresql+psycopg://…`) en dev/producción; SQLite en
  tests (`cavaai_test.db`, hermético, `APP_ENV=test`). Migraciones con Alembic
  (`alembic upgrade head`; última: `0029_manager_holding_filing_date`).
- **Rate limiting**: `RateLimitMiddleware` global (120 req/min; 20/min para
  endpoints caros).

## 4. Fuentes de datos de mercado

| Fuente | Uso | Dónde |
|---|---|---|
| **Finnhub** | Quotes de acciones vía frontend (`lib/actions/finnhub.actions.ts`, `FINNHUB_API_KEY`) | Next.js |
| **Yahoo Finance** | Índices (S&P 500, Nasdaq, BTC, oro, plata) vía `GET /api/market/indices` (`app/api/routes/market.py`), sin key, con cache en memoria de 60 s | data-engine |
| **FMP** (opcional) | Fuente secundaria: perfiles, dividendos, splits y contraste de hechos financieros (conflict detection SEC) vía `app/services/connectors/fmp.py`; solo activa con `FMP_API_KEY`. Los errores de proveedor se propagan para marcar la cobertura como no disponible, nunca se fabrican datos | data-engine |

## 5. Trabajos programados (workers)

- **Fuente de verdad — backend**: `app/workers/scheduler.py` construye un
  scheduler APScheduler (`build_scheduler`) con jobs que encolan actores
  Dramatiq (`app/workers/dramatiq_app.py`, broker Redis) para cada tenant:
  refresh de market/noticias/RSS/SEC/IR, consolidación de memoria, revisión de
  tesis, investigación diaria y escaneo de contradicciones. Se arranca en el
  lifespan de FastAPI solo si `WORKERS_ENABLED=true` (desactivado en tests).
- **Canal de alertas**: Telegram es el ÚNICO canal de notificaciones
  (`TELEGRAM_ENABLED`, `notification_service`), usado por los flujos del
  backend. El stack de email del frontend (Inngest + nodemailer) se eliminó:
  los emails están desactivados por decisión del usuario.

## 5b. Grafo de ciclo de vida de tesis (etapa 6, límite final)

- **Plano de control durable**: `app/workflows/thesis_graph/` (LangGraph)
  gobierna el ciclo de vida de la tesis: reanudación ante fallos con
  checkpointer, `interrupt()` de aprobación real (6c), reintento idempotente
  y sondas de lectura que registran el estado persistido por la vía clásica
  (resolve_company, ensure_ingestion_complete, build_fundamental_model,
  deterministic_valuation, source_audit, deterministic_red_team) más la
  huella de freeze_input_snapshot.
- **Ejecutor único**: la vía clásica `ThesisService` sigue siendo el ÚNICO
  ejecutor LLM/escritura. `draft_synthesis`, `optional_bull_bear_debate`,
  `assemble_candidate` y `publish` son marcadores de control deliberados
  (`pending:<nodo>`): mantienen el flujo completo y reanudable sin duplicar
  coste LLM ni arriesgar dobles escrituras, y nunca ejecutan trabajo de
  negocio dentro del grafo.
- **Validación shadow**: `ThesisShadowService` compara en cada ejecución el
  orden de nodos, el reintento idempotente y cada observación de las sondas
  contra el estado persistido clásico; las divergencias quedan registradas
  explícitamente en el WorkflowRun durable. El shadow nunca muta artefactos
  de dominio.

## 6. Ejecución local

```bash
# Backend (data-engine/)
cd data-engine
python -m venv .venv && ./.venv/Scripts/pip install -r requirements.txt
# .env con DATABASE_URL (Postgres local), RESEARCH_AUTH_SECRET (≥32 chars), etc.
./.venv/Scripts/alembic upgrade head
./.venv/Scripts/python -m uvicorn main:app --reload --port 8000

# Frontend (raíz)
npm install
npm run dev            # http://localhost:3000 (FMP_BACKEND_URL=http://localhost:8000)

# Tests del backend
./.venv/Scripts/python -m pytest tests/ -q
```

## 7. Despliegue — variables de entorno requeridas

| Variable | Obligatoria | Notas |
|---|---|---|
| `DATABASE_URL` | sí | Postgres; migraciones vía Alembic antes de arrancar |
| `RESEARCH_AUTH_SECRET` | sí (producción) | ≥32 chars; compartida con el frontend; sin ella el API autenticado da 503/401 |
| `WORKERS_ENABLED` | no (default true) | `false` desactiva el scheduler (tests, workers aparte) |
| `FINNHUB_API_KEY` | según features | quotes del frontend |
| `OPENCODE_GO_API_KEY` / `OPENCODE_GO_MODEL` | sí (LLM) | provider LLM principal (`llm_provider=opencode-go`); cascada gratuita opt-in con `LLM_PROVIDER=cascade` y fallback Groq solo para chat (docs/AI_PROVIDER_STRATEGY.md) |
| `MINIO_*` | sí (producción) | almacenamiento de documentos originales |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | según features | canal de alertas primario |
| `REDIS_URL`, `QDRANT_URL` | según features | broker Dramatiq y vectores |
| `APP_ENV` | sí | `test` / `local` / `production` (valida secretos en prod) |