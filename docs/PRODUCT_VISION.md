# GerarAI Product Vision

## Non-negotiable Principle

GerarAI must treat the thesis and memory as the core of the product. Quantitative valuation is an additional tool, not the center of the system. No framework, metric, score, or model should be forced onto a company when it is not appropriate.

## Product Direction

GerarAI is a private Personal Investment Research OS. It should help the investor preserve memory, contrast evidence, monitor thesis changes, and think better over time.

It should not become a generic stock screener, a DCF factory, an auto-trading bot, or a thin LLM wrapper without durable memory.

### Global-first sourcing

GerarAI is not centered on any single market. Source weighting follows the issuer's market: the owning regulator and exchange (SEC/EDGAR for US issuers, CNMV for Spanish issuers, FCA, BaFin, AMF, CONSOB, ASIC, JFSA, SEDAR and equivalents elsewhere), issuer IR materials, and reputable global media/data providers. Most filings, news and source documents will be in English; content is preserved in its original language with its source link, and optional Spanish summaries never replace source truth. Spanish coverage (CNMV filings, OIR) is additive for Spanish issuers, not the product axis. The UI remains comfortable in Spanish while research data keeps its original language.

## Core Objects

- Company workspace
- Thesis and thesis versions
- Thesis sections
- Claims and claim evidence
- Documents and chunks
- Source lineage
- Financial facts and calculated metrics
- News items and thesis impact
- Research sessions
- Conversation memory
- Portfolio positions and alerts

## Target Company Workspace

Each company should evolve into a living workspace with:

- Overview
- Current thesis
- Thesis history
- What changed
- Key claims
- Metrics and financials
- Documents, filings, calls, and letters
- News and catalysts
- Risks and invalidation conditions
- Moat and competitors
- Peer comparison
- Valuation and scenarios
- Portfolio context
- Sources
- Company chat

## Memory Model

The LLM should not "learn" by changing model weights. It should improve through external persistent memory:

- Structured memory in PostgreSQL
- Document memory in Qdrant and MinIO
- Thesis history
- Claim memory
- Conversation memory
- Evidence graph

Every important answer should distinguish facts, calculations, user assumptions, LLM inference, and unverified claims.

The current backend implements the first production-shaped memory loop:

`chat/query -> retrieve company/portfolio memories -> rank by relevance/importance/recency -> inject into answer context -> optionally write back user-directed memories -> dedupe exact repeats`

This is intentionally lightweight and compatible with Mem0/Graphiti-style evolution. It should remain provider-agnostic until the core product workflows are stable.

## Evidence Rules

Missing data is not an estimated fact. When evidence is insufficient, the system must return `unknown`, `missing`, or `insufficient_data`.

Important claims should link back through:

`Source -> Document -> Chunk -> Fact / Claim -> Thesis Section -> Thesis Version`

## Analysis Rules

Different companies require different frameworks:

- PayPal: FCF, margins, buybacks, branded checkout, take rate, TPV.
- AST SpaceMobile: satellites, launch cadence, MNO agreements, coverage, capex, runway, dilution.
- Brookfield: SOTP, fee-related earnings, carry, holdco debt, insurance, holding discount.
- Rocket Lab: launch, space systems, Neutron, backlog, defense, segment margins.

GerarAI must support configurable frameworks, qualitative reasoning, manual assumptions, and source-tagged metrics.

## Long-Term Fundamental Modeling Engine

The company workspace now has a source-aware v2 engine for the full 5–10 year thesis workflow. The framework selects company-specific drivers and formulas, while the persisted model separates the operating forecast from market-price valuation snapshots:

- 10-year annual financial history with reported-versus-calculated labels.
- Bear / Base / Bull driver-based operating forecasts for revenue, segments, margins, EBITDA, net income, cash flow, capex, working capital, net debt, shares and FCF per share.
- Funding roll-forward for opening cash, operating cash generation, capex, debt, equity issuance, closing cash, dilution and future invested capital / ROIC. Unknown acquisitions remain unknown rather than being coerced to zero.
- Revenue and FCF bridges, reverse DCF, quality of growth, owner earnings, capital allocation and “what must be true”.
- Market-share and maintenance-versus-growth-capex outputs that remain `insufficient_data` until the required facts are sourced.
- Reproducibility through algorithm version, code SHA and separate input, forecast, market and valuation fingerprints.

Every modelled value carries its input fact IDs and calculation basis. Historical facts carry period, source type, document ID when available, reported/adjusted state and confidence. The engine uses the traceable calculated WACC first; a policy default is preview-only and blocks publication. Scenario spreads and terminal growth remain explicit policy assumptions so the model cannot turn missing evidence into false precision.

### Canonical research flow

The modules are intentionally layered instead of producing parallel summaries:

`Evidence / documents -> normalized facts -> company framework -> forward operating model + Market Opportunity -> valuation / reverse DCF -> thesis -> monitoring`

- **Company framework** decides which drivers, KPIs, unit economics, segments, macro variables and constraints matter for this company.
- **Forward Operating Model** owns the forecast, scenarios, bridges, working capital, capex, shares, ROIC and FCF. Unit economics and segment models are inputs to that model, not separate competing forecasts.
- **Market Opportunity Engine** owns TAM, SAM, SOM, top-down, bottom-up, penetration, market share, valuation-implied share and binding constraints. For mature asset-heavy companies it becomes a reinvestment-runway review.
- **Thesis** stores the conclusion and its versioned claims; **Evidence** stores why a claim is allowed; **Memory** stores investor hypotheses and research context.
- **News Impact / What Changed** updates the assumptions and claims that an event touches. **Decision Journal** records the decision made against the thesis. **Expectation vs Reality** compares subsequent facts with the model's explicit forecast and turns misses into review items.

The long-term engine is therefore the quantitative spine of the thesis, not a second thesis generator. A company may activate the same module names with different drivers and different missing-data requirements; a holding company can receive a reinvestment-runway review while a network business receives a mandatory TAM plus capacity analysis.

## LLM Routing

GerarAI uses OpenCode Go as its primary LLM provider (see docs/AI_PROVIDER_STRATEGY.md). The default model is deepseek-v4.1-flash, covered by the owner's subscription (opencode_go_model in data-engine/app/core/config.py). OPENCODE_GO_FALLBACK_MODEL and task-level LLM_MODEL_OVERRIDES are validated against the owner-approved models in production; the optional LLM_PROVIDER=cascade path (Gemini free plan confirmed, OpenRouter :free, approved Go) and the opt-in Groq/Gemini/OpenRouter chat backups are documented there.

Company chat keeps the deterministic context contract, then performs source-aware JSON synthesis, verifies citation IDs, calculates confidence / insufficient-data state and falls back safely when validation fails.

Langfuse records workflow, provider, model, prompt version, retrieval set, tools, tokens and cache tokens, estimated cost, latency, citations, JSON validity, fallback, escalation and evaluation score. Native Microsoft Agent Framework runs only EarningsWorkflow and RedTeamWorkflow (`MAF_WORKFLOWS` in `app/workflows/maf_runtime.py`); Deep Research and Thesis Review are retired from the executable catalog (`RETIRED_WORKFLOWS`), and the thesis lifecycle is governed by the LangGraph control plane with `ThesisService` as the only LLM/write executor. Ingestion, SQL, metrics and DCF remain deterministic services.

Vector-backed chat retrieval is opt-in through `CAVAAI_ENABLE_VECTOR_CHAT=1`. The default company chat uses the canonical SQL store first so local development and tests do not depend on Qdrant or embedding downloads.

## External OSS Integration Map

- Mem0: use the architecture pattern of extract, retrieve, consolidate and write memory. Do not make it a hard dependency until tenant scoping, cost controls and observability are stable.
- Graphiti: use as the reference pattern for future temporal knowledge graph work, especially facts that change over time and require provenance.
- EdgarTools: preferred P0 candidate for SEC filings, XBRL statements and filing metadata because it provides a focused Python API around EDGAR data.
- Docling: preferred P0 candidate for PDF/DOCX/XLSX/HTML document parsing, table extraction and layout-aware chunks.
- OpenEDGAR: use patterns for bulk EDGAR archive construction; do not adopt the whole stack unless GerarAI needs a self-hosted SEC archive.
- SEC EDGAR AgentKit/MCP: useful adapter/tool patterns over EDGAR; avoid coupling the app to MCP-only runtime paths.
- FinNLP/FinGPT: mine for financial news/data connector ideas and sentiment datasets; do not make fine-tuning frameworks part of the P0 product.

## Development Priorities

### P0

- Persistent company memory: backend model, API and company page read/write path are in place.
- Memory retrieval and write-back: company/portfolio chat now retrieves relevant memories and stores user-directed chat memories with dedupe.
- Thesis versions: backend generation, history and frontend display are in place.
- Claim memory: unified claim/evidence model, API, migration and company page capture are in place.
- Source lineage: documents, chunks, facts, audits and claim evidence links are in place, including claim evidence linked from the company workspace.
- Source hierarchy: source quality is now classified through formal tiers from regulatory filings to user input, with trust scores and source policy text reused by chat and news.
- Document ingestion: manual Quartr/text import, generic file upload and URL ingestion are in place. Native parsers cover TXT/MD/HTML/PDF/DOCX/XLSX/CSV/TSV with checksum, raw storage, chunk metadata and duplicate detection. Docling can be used as an opt-in parser with `CAVAAI_USE_DOCLING=1`.
- Source evidence workflow: the company workspace shows source chunk previews and supports one-click creation of source-derived claims or support/contradiction evidence linked to existing claims.
- Traceable metrics: normalized facts, valuation trace and calculated metric records are in place. Current canonical calculated metrics include FCF margin, gross/operating/net margin, ROE, ROA, ROIC, FCF conversion and net debt / EBITDA, each with definition version, formula, numerator, denominator, source fact ids, calculation trace, confidence and unavailable status when inputs are missing.
- Company and portfolio chat: backend chat is now source-aware and returns facts, calculations, memory/user assumptions, unverified claims, inference and typed sources.
- News relevance and thesis impact: manual news analyzer, batch feed ingestion, event storage, dedupe, source-tier policy, portfolio-aware materiality and automatic thesis-change creation for material updates are in place.
- What Changed: thesis change records, manual capture, automatic claim-contradiction changes and material-news changes are in place.
- Peer comparison: company workspace comparison now uses same-industry/sector peers and traceable calculated metrics with peer median/average benchmarks.
- Company-specific long-term modelling: the workspace resolves a company framework and exposes the source-aware Long-Term Fundamental Modeling Engine.
- Market Opportunity: TAM/SAM/SOM, top-down and bottom-up opportunity, valuation-implied market share and binding-constraint detection are unified in one contract; mature asset-heavy companies use reinvestment runway instead of forced TAM.

### P1 foundations implemented

- Moat assessment, peer selection, thesis dependency graph and red-team persistence.
- Earnings workflow, contradiction/review records and material What Changed automation.
- Decision Journal linked to the latest thesis, fundamental model and observed price.
- Expectation vs Reality reviews choose the last forecast made before the actual, support reported and calculated actuals, and apply metric-specific direction and tolerance semantics.
- Dedicated fact-driven bank, insurer and REIT valuation engines.
- Read-only typed compact snapshot plus explicit refresh commands and paginated detail endpoints, consumed through a generated OpenAPI TypeScript client.
- Company KPI Registry and automatic structured extraction from documents with exact chunk locator validation, normalization, period reconciliation and human approval before canonical facts are created.
- Company-specific driver formulas, funding / dilution roll-forward, traceable WACC and reproducible operating-model / valuation snapshots.
- Persistent evaluated alert rules with cooldowns and scheduled workers.
- Portfolio base-currency accounting with historical FX, native/base cost basis and realized P&L.
- Full AI task routing, citation checking, cost budgets, Langfuse instrumentation and a financial evaluation dataset.

### Post-v1 expansion

- Promote Docling from optional parser only after validating deployment size, OCR quality and table accuracy.
- Expand traceable metrics to CFROI, ROCE and incremental ROIC.
- Extend automatic filing contradictions beyond the current claim, news and earnings triggers.
- Expand browser coverage to authenticated mutations in a disposable containerized stack.
- Add a portfolio risk graph, management credibility tracker, capital-allocation ledger, forecast calibration and mistake taxonomy.
- Continue typing and removing lint debt from legacy market-data and presentation adapters; the canonical Research workspace and generated OpenAPI client are already strict.
- Produce a reproducible Python lockfile for deployments instead of resolving only from bounded direct dependencies.

These are additive capabilities, not alternate persistence paths or prerequisites for the core Research OS workflow.

## Production Release Gate

GerarAI is functionally ready for a private staging / beta round, but it must not be described as 100% production-ready until all of these conditions hold on the exact release commit:

- GitHub CI is green for frontend, backend, PostgreSQL migrations, dependency audits, API E2E, browser E2E and OpenAPI drift; `main` is protected and those checks are required.
- PostgreSQL, Redis, Qdrant, MinIO, workers and Langfuse run together in staging with production-shaped secrets, tenant isolation and real provider credentials.
- A Docker-volume migration dry run, encrypted backup and full restore drill have been completed and reconciled against tenant, document and portfolio counts.
- Representative companies have been calibrated against real filings and subsequent actuals; WACC, funding, dilution, future ROIC and valuation outputs have received human financial review.
- Data retention, deletion/export, privacy notice and incident ownership have been completed for the intended deployment jurisdiction and audience.

Passing local tests proves implementation integrity; it does not replace operational, financial, security or legal validation in staging.

## Success Criterion

GerarAI is working when the user can add a company, upload filings/results/letters, create a thesis, ask source-aware questions, inspect traceable metrics, compare competitors, analyze moat, save hypotheses, receive material news, see whether the thesis changed, inspect sources, and improve the accumulated knowledge over months.


## Estado de implementacion (2026-08-23)

### Completado (verificable en main)
- produccion viva: gerarai.vercel.app (Vercel build READY, env vars configuradas) — auth (better-auth/Mongo), home, portfolio, research, watchlist. Backend FastAPI local en :8000 con scheduler de workers (autoarranque en login).
- Watchlist unificada al backend (tabla watch_items, ruta /api/watchlist) — fuera el acceso directo a Mongo.
- Indices reales en la home: ^GSPC, ^IXIC, BTC-USD, GC=F, SI=F (Yahoo Finance, cache 60s).
- Screener real: /api/screeners/real (Finnhub free, 35 large caps, precios y market caps del dia).
- Empresa real: /api/valuation/{ticker} (valoracion determinista: bear/base/bull, margin of safety).
- Informes anuales y valoracion con trazabilidad (chat synthesis con contrato de 8 secciones incl. UNVERIFIED CLAIM).
- Finanzas personales: taxes (IRPF FIFO), plan de inversion, corporate actions (apply), export anual, risk dashboard — con UI y paginas.
- Alertas: UI (AlertsManager) + scheduler backend + Telegram como canal primario.
- Limpieza profesional: FMP retirado del frontend, API legacy borrada, empresas de test purgadas, dead code eliminado, /api/health, docs/ARCHITECTURE.md.

### Pendiente prioritario (depende de credenciales/decisiones)
1. IBKR: IBKR_FLEX_TOKEN + IBKR_FLEX_QUERY_ID para el import real de cartera (UI y pipeline listos).
2. Rotar password de la cuenta de usuario (expuesto en logs de dev) y revocar token Vercel temporal.
3. Hosting cloud del FastAPI: elegida la opcion Oracle Cloud Always Free (guia en docs/oracle-setup.md); despliegue en curso. render.yaml queda como experimental y no soportado en la 1.0 (free tier hiberna y exige Postgres/Redis/Qdrant/MinIO externos para pasar /health/ready).
4. E2E playwright en CI (specs existentes; ampliar cobertura de finanzas).
5. Legal/privacidad (privacidad) y backup drills (Postgres + Mongo).

## Cierre del programa de mejora (2026-09-23)

Desde la instantanea de 2026-08-23 se han mergeado 145 PRs de endurecimiento: tests de contrato sobre los invariantes de honestidad (valoracion, insiders, corporate actions, import IBKR, terminal financiero, fiscalidad, refresh de mercado), correccion de los bugs reales que esos tests destaparon (matematicas de drift, FX a par en fiscalidad, pesos cero silenciosos, fechas fabricadas en import IBKR, valoraciones absurdas con WACC <= g) y batching de consultas N+1 en refresh de mercado, insiders, SEC e IBKR. Auditorias completas y limpias en todos los servicios principales.

Pendiente conocido:
1. Despliegue del backend en Oracle Always Free: en curso, bloqueado por capacidad A1 en la home region (reintento horario). El barrido visual de produccion (desktop + movil 390px) queda pendiente hasta que el despliegue este vivo; es el unico item abierto del programa.
2. Regla de los dos meses (wash sale, IRPF): decision de producto pendiente del propietario; no implementada a proposito hasta que la confirme.
3. Credenciales pendientes del propietario (IBKR Flex) sin cambios.
