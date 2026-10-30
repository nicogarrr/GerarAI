> Versión original en español del README (conservada por referencia). El README principal está en inglés: [../README.md](../README.md).

# GerarAI — Research OS de inversión personal

[![CI](https://github.com/nicogarrr/GerarAI/actions/workflows/ci.yml/badge.svg)](https://github.com/nicogarrr/GerarAI/actions/workflows/ci.yml)
[![Coverage](https://github.com/nicogarrr/GerarAI/actions/workflows/coverage.yml/badge.svg)](https://github.com/nicogarrr/GerarAI/actions/workflows/coverage.yml)
[![CodeQL](https://github.com/nicogarrr/GerarAI/actions/workflows/codeql.yml/badge.svg)](https://github.com/nicogarrr/GerarAI/actions/workflows/codeql.yml)
[![Release](https://img.shields.io/github/v/release/nicogarrr/GerarAI?include_prereleases&label=release&color=orange)](https://github.com/nicogarrr/GerarAI/releases)
[![License](https://img.shields.io/badge/license-AGPL--3.0-blue)](../LICENSE)

**GerarAI es tu memoria de inversor a largo plazo.** No es un terminal más ni una fábrica de DCF: es donde vive por qué sigues o posees cada empresa, qué evidencias sostienen tu tesis, qué la contradice y qué ha cambiado con el tiempo.

> Esto no es asesoramiento financiero. Los datos pueden llegar con retraso o estar incompletos según el proveedor.

**Estado:** v0.5.0 (pre-release), base de producción del 30 de octubre de 2026. Las mejoras y la revisión siguen en curso.

## Qué hace

- **Workspace por empresa** (`/research/[ticker]`): snapshot coherente, tesis versionada con auditoría, claims con evidencia a favor/en contra, memoria y chat con fuentes.
- **Tesis con abogado del diablo**: debate bull/bear automático con veredicto persistido en la tesis.
- **Valoración determinista**: DCF, SOTP, pre-revenue, bancos, aseguradoras, REITs, holdings y materias primas — con traza de cálculo. Anti-look-ahead: la serie histórica de múltiplos con `as_of` pasado solo usa precios hasta esa fecha y cifras SEC cuyo filing (`filed`) es anterior; sin `filed`, cierre del periodo + 120 días. Límite: de cada periodo se guarda solo la última cifra (reexpresada), así que antes de la reexpresión ese periodo sale «sin datos», no con la cifra original.
- **Señales insider**: compras de directivos desde SEC EDGAR (Form 4, gratis), con detección de cluster-buy y alerta en Telegram.
- **Alertas en Telegram**: reglas de precio/noticias/earnings + urgencia puntuada por IA; las tesis se aprueban desde el propio Telegram (Publicar / Revisar).
- **Biblioteca de conocimiento (RAG)**: sube PDFs/MDs, extrae principios, apruébalos y pregúntales con búsqueda semántica (Qdrant + embeddings locales).
- **Tesis en EPUB**: descarga cada tesis para leerla en tu e-reader/Kindle.
- **Screener real, portfolio con IBKR, calendario de earnings/dividendos, diario de decisión y fiscalidad.**

## De dónde vienen los datos (todo verificable)

| Fuente | Qué aporta | Coste |
|---|---|---|
| Yahoo Finance | Índices reales (^GSPC, ^IXIC, BTC-USD, GC=F, SI=F), fallback de quotes | Gratis |
| Finnhub | Quotes, perfiles, noticias, calendario (caché ~60 s) | Free tier |
| SEC EDGAR | Filings 10-K/10-Q y Form 4 de insiders | Gratis, sin key |
| FRED | Macro (IPC, paro, tipos) | Gratis (key gratuita) |
| Calendario NASDAQ | Earnings y dividendos | Gratis |
| FMP (opcional, con `FMP_API_KEY`) | Perfiles, dividendos, splits y contraste de cifras SEC | Free tier |
| OpenCode Go (DeepSeek v4.1 Flash) + Jev | Solo texto de análisis y micro-decisiones; **nunca inventa cifras** | Suscripción Go ya contratada; Jev opcional, factura por uso si se activa |

Si FMP no está configurado o el proveedor falla, esa cobertura se marca como no disponible en lugar de inventarse; no hay tickers ni nombres hardcodeados: todo nombre visible viene de una API real.

## Cerebro LLM

El primario es **OpenCode Go** (`https://opencode.ai/zen/go/v1`, modelo
`deepseek-v4.1-flash`, cubierto por la suscripción del dueño). El detalle vive
en [docs/AI_PROVIDER_STRATEGY.md](AI_PROVIDER_STRATEGY.md):

- `OPENCODE_GO_FALLBACK_MODEL` es opcional y se pasa al primario Go; si el
  modelo principal falla, se reintenta una vez con él. Debe ser un modelo
  aprobado (free verificado o el Go).
- `LLM_MODEL_OVERRIDES` es un JSON de overrides por tarea. En producción cada
  valor debe ser aprobado; `OPENCODE_GO_ALLOW_UNVERIFIED_MODEL=true` es solo
  para un piloto auditado.
- `LLM_PROVIDER=cascade` es opcional: Gemini (con `GEMINI_FREE_PLAN_CONFIRMED=true`),
  OpenRouter (`:free`) y el Go aprobado, solo miembros con clave.
- `LLM_PROVIDER=disabled` (o `LLM_ENABLED=false`) no construye proveedor; el
  chat queda deshabilitado y `/health/ready` devuelve 503.
- Groq/Gemini/OpenRouter son respaldos gratuitos en modo `auto` (por
  defecto): cada uno entra solo si tiene clave y las confirmaciones de plan
  gratuito (`GROQ_FREE_PLAN_CONFIRMED`+`GROQ_ZDR_CONFIRMED`,
  `GEMINI_FREE_PLAN_CONFIRMED`); sin clave se salta. `*_CHAT_FALLBACK_ENABLED=false`
  los apaga. Si todo falla, el chat responde en modo determinista marcado
  como fallback, sin inventar texto.
  La caché de respuestas Go es por tenant y nunca cachea un fallback.

## Arranque rápido (< 30 min)

**Opción rápida (Windows) — `arrancar_gerarai.bat`:**

Doble clic (o `arrancar_gerarai.bat /prod` para validar el build de producción).
El script levanta **solo la infraestructura** con Docker (PostgreSQL, MongoDB,
Redis, Qdrant, MinIO), libera los puertos 8000/3000 de procesos huérfanos de
sesiones anteriores, aplica las migraciones de Alembic (se detiene si fallan)
y arranca backend (uvicorn :8000) y frontend (next :3000) en local, abriendo
http://localhost:3000 en el navegador.

**Opción A — stack completo con Docker:**

```bash
cp docker.env.example .env
# edita .env con tus claves (Finnhub, Telegram, OpenCode Go…)
docker compose up --build
```

Abre http://localhost:3000. Servicios: PostgreSQL, MongoDB (auth), Qdrant (vectores), MinIO (documentos), Redis.

| Servicio | Puerto host |
|---|---|
| Frontend Next.js | 3000 |
| Backend FastAPI | 8000 |
| MongoDB (auth) | 27017 |
| PostgreSQL | 5432 |
| Redis | 6379 |
| Qdrant | 6333 (+6334 gRPC) |
| MinIO API / consola | 9002 / 9003 |

**Opción B — GitHub Codespaces (sin cargar tu portátil):**

El repo incluye `.devcontainer/`: al crear un codespace se levanta la pila completa
(PostgreSQL, MongoDB, Redis, Qdrant, MinIO, backend FastAPI y frontend Next.js) y
quedas editando dentro del contenedor con Node 22 y Python 3.

1. En GitHub: **Code -> Codespaces -> Create codespace on main**.
2. Espera a que termine el arranque y abre el puerto 3000 (se reenvía solo).
3. La cuenta personal gratuita incluye 120 core-hours/mes (~60 h con la máquina
   de 2 cores) y 15 GB de almacenamiento; configura el auto-stop a 15-30 min en
   tus ajustes de Codespaces para no gastar cuota.
4. En una máquina de 2 cores puedes ahorrar RAM parando lo que no uses:
   `docker compose stop worker scheduler`.

**Opción C — desarrollo por piezas:**

```bash
# Backend
cd data-engine
python -m venv .venv && ./.venv/Scripts/activate  # Windows
pip install -r requirements.txt
python -m alembic upgrade head
python -m uvicorn main:app --host 127.0.0.1 --port 8000

# Frontend (otra terminal, desde la raíz)
npm install
npm run dev
```

**Variables mínimas** (ver `docker.env.example` para la lista completa):

```env
MONGODB_URI=mongodb://root:***@localhost:27017/cavaai?authSource=admin
BETTER_AUTH_SECRET=secreto_de_32_caracteres_minimo
RESEARCH_AUTH_SECRET=otro_secreto_independiente_de_32
FINNHUB_API_KEY=
OPENCODE_GO_API_KEY=
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

Genera secretos con `openssl rand -base64 32`. **Nunca commitees el `.env`** (está en `.gitignore`: solo se versionan los `.example`).

## Verificación

```bash
# Frontend
./node_modules/.bin/tsc --noEmit
npm run lint
npm run build

# Backend (suite completa; ~10 min en CI con -n 2)
cd data-engine && ./.venv/Scripts/python.exe -m pytest tests/ -q

# El cliente OpenAPI no debe derivar (regenerar si tocas rutas)
npm run generate:openapi
git diff --exit-code -- data-engine/openapi.json lib/research/openapi.generated.ts
```

El CI ejecuta 13 jobs: paridad de dependencias, calidad frontend, auth-store,
lint backend (ruff + pyright), tests backend, evals de calidad (RAG, valoración,
capas LLM e ingesta), drift OpenAPI, migraciones Postgres, smoke ARM64,
auditoría supply-chain, e2e de API, e2e de navegador y la puerta final
`CI gate (single required check)`, más un workflow aparte de cobertura.

### Evals de calidad (FASE C)

Cuatro suites con dataset congelado y puertas deterministas. Los números, sus
umbrales y el workflow que los ejecuta están en
[docs/QUALITY_GATES.md](QUALITY_GATES.md); el detalle de cobertura, en
[docs/COVERAGE.md](COVERAGE.md).

```bash
cd data-engine

# RAG (C1): necesita Qdrant vivo. refuse-to-skip: sin Qdrant sale con 1, no con un stub.
docker compose up -d qdrant
python scripts/run_rag_evals.py

# Motores de valoración (C2), capas LLM (C3) e ingesta (C4): offline y deterministas
python scripts/run_valuation_evals.py
python scripts/run_llm_evals.py
python scripts/run_ingest_evals.py

# Cobertura: mide y gatea. Sin pytest-cov instalado esto falla con "unrecognized arguments".
python -m pip install "pytest-cov>=5.0"
python scripts/run_coverage_gate.py

# Suite completa sin servicios externos (el marker `services` está registrado)
python -m pytest tests -m "not services"
```

Todos aceptan `--json` para volcar el informe. El eval del RAG indexa en
`rag_eval_v1_documents`, no en el índice del producto.

## Arquitectura en 30 segundos

Next.js (App Router, server actions firmadas HMAC) habla con FastAPI
(`/api/*`, firma X-CavaAI-*): Postgres como canónico, Qdrant como índice
semántico reconstruible, MinIO para originales y Redis/Dramatiq para jobs.
OpenCode Go es el LLM por defecto, con respaldos gratuitos (Groq/Gemini)
que entran solos cuando hay clave y plan gratuito confirmado, y Jev hace las
micro-decisiones.

Autenticación doble: sesiones Better Auth en MongoDB + firma HMAC con secreto
de 32 mínimo en la research API (ventana 300 s, tenant = tu userId).

## Estructura

```
app/(root)/          páginas: research, screener, watchlist, portfolio,
                     alerts, knowledge, propicks, metodologia…
components/          UI (shadcn/Radix + Tailwind oscuro)
lib/actions/         server actions · lib/research/  cliente firmado
data-engine/
  app/api/routes/    51 routers bajo /api
  app/services/      ingesta, tesis, debate, insider, RAG, alertas…
  app/valuation/     motores + guardia point-in-time
  app/llm/           factory de proveedores (OpenCode Go por defecto) + cliente Jev
  alembic/versions/  migraciones 0001→0080 (lineales, con downgrade)
  tests/             tests herméticos de pytest (la cifra actual, en el resumen del job «Backend quality» de CI) · evals/  evals financieras
e2e/                 specs Playwright del flujo inversor
docs/                PRODUCT_VISION, runbooks, privacidad
```

Ver [docs/PRODUCT_VISION.md](PRODUCT_VISION.md) y la propia app en
`/metodologia` (fuentes, límites y costes).

## Producción

- **Camino oficial para la 1.0**: frontend en Vercel + backend con
  `docker-compose.prod.yml` en Oracle Cloud. Es el único despliegue probado de
  punta a punta (healthchecks, reinicio automático y restore drill en CI).
- **Oracle Cloud (Always Free)**: `docker-compose.prod.yml` levanta el stack 24/7
  en una VM Ampere ARM (Caddy + PostgreSQL + Redis + Qdrant + MinIO + backend +
  worker + scheduler), con healthchecks y reinicio automático; ver
  [oracle-setup.md](oracle-setup.md) para la cuenta y el `.env.production`.
- **Autoarranque local (Windows)**: `arrancar_gerarai.bat` para uso personal en el PC.
- **Render (experimental, no soportado)**: `render.yaml` (raíz del repo) solo
  describe el backend con `data-engine/Dockerfile.prod`. **No despliega tal
  cual**: `/health/ready` exige Postgres, Redis, Qdrant y MinIO externos que hay
  que configurar a mano en el dashboard, el tier free hiberna a los ~15 min y los
  workers van apagados (`WORKERS_ENABLED=false`).
- Migraciones siempre explícitas (`alembic upgrade head`); el seed solo instala taxonomía pública, nunca tu cartera.
- Puertos de BD cerrados al exterior; secretos solo en el dashboard de deploy.
- Qdrant se reconstruye desde Postgres (`RAGIndex().rebuild_tenant`).

## Licencia

Copyright 2025 Nicolás Iglesias García. Publicado bajo la licencia GNU AGPL-3.0; ver [LICENSE](../LICENSE).
