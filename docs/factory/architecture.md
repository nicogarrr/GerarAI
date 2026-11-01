# GerarAI v1.0 — Architecture Document

> **Audiencia:** Ingenieros contribuyendo al proyecto. Asume familiaridad con Next.js, FastAPI y Docker Compose.
> **Estado:** Autoritativo para v1.0 (octubre 2026). Actualizar junto a los cambios de arquitectura, no después.

---

## 1. Visión general del sistema

GerarAI es un Research OS de inversión personal. Combina un frontend en Next.js desplegado en Vercel con un backend FastAPI en Oracle Cloud (Always Free ARM64). La autenticación usa MongoDB Atlas (M0 gratuito). Todo el procesamiento pesado ocurre en el servidor; el cliente recibe datos ya preparados.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Usuario (navegador)                             │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ HTTPS
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│              Vercel (frontend — Next.js 16 App Router)                  │
│  Server Components · Server Actions · API Routes proxy                  │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ HTTPS (Bearer token)
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                   Oracle Cloud ARM64 (4 OCPU / 24 GB)                   │
│                                                                         │
│  ┌──────────┐   ┌────────────┐   ┌──────────┐   ┌──────────────────┐   │
│  │  Caddy   │──▶│  Backend   │──▶│ Postgres │   │  Dramatiq        │   │
│  │ (TLS/RP) │   │ (FastAPI)  │   │   17     │   │  Workers (×6)    │   │
│  └──────────┘   └─────┬──────┘   └──────────┘   └──────────────────┘   │
│                        │                                                │
│            ┌───────────┼───────────────────────┐                        │
│            ▼           ▼                       ▼                        │
│         Redis 7    Qdrant 1.19.2           MinIO / Garage               │
│         (cola +    (vectores RAG)           (objetos S3)                │
│          caché)                                                         │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │ APScheduler (scheduler container) — cron de jobs diarios/hourly │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
              ┌─────────────────────────────────────┐
              │   MongoDB Atlas M0 (autenticación)   │
              │   better-auth · sesiones · usuarios  │
              └─────────────────────────────────────┘
```

### Stack tecnológico

| Capa | Tecnología | Versión |
|---|---|---|
| Frontend framework | Next.js (App Router) | ^16.3.6 |
| UI runtime | React | 19.3.0 |
| Lenguaje frontend | TypeScript | ^5 |
| Componentes UI | Radix UI + shadcn/ui | — |
| Gráficos | Recharts, lightweight-charts | — |
| Autenticación frontend | better-auth | ^1.7.7 |
| Backend framework | FastAPI + Uvicorn | >=0.139.0 |
| Lenguaje backend | Python | 3.12 |
| ORM | SQLAlchemy 2 + Alembic | >=2.0.32 |
| Base de datos principal | PostgreSQL | 17 |
| Cola de mensajes / caché | Redis | 7 |
| Almacén vectorial | Qdrant | 1.19.2 |
| Almacén de objetos | MinIO (prod); Garage (migración) | — |
| Cola de tareas | Dramatiq | >=1.17.0 |
| Scheduler | APScheduler | >=3.10.4 |
| Reverse proxy / TLS | Caddy | 2 |
| Despliegue | Docker Compose | — |
| CI | GitHub Actions | — |

---

## 2. Arquitectura de componentes

### 2.1 Capa frontend (Next.js)

El frontend usa el **App Router** de Next.js con una estructura de grupos de rutas:

```
app/
├── (auth)/          — Páginas de login, registro, recuperación
├── (public)/        — Landing page pública, sin autenticación
├── (root)/          — Aplicación autenticada principal
│   ├── inicio/      — Dashboard
│   ├── portfolio/   — Portafolio y posiciones
│   ├── stocks/      — Ficha de empresa / tesis
│   ├── research/    — Research assistant
│   ├── screener/    — Screener de mercado
│   ├── watchlist/   — Lista de seguimiento
│   ├── alerts/      — Centro de alertas
│   ├── knowledge/   — RAG de conocimiento propio
│   ├── plan/        — Plan de inversión
│   ├── taxes/       — Informe fiscal
│   └── settings/    — Configuración de cuenta y LLM
├── api/             — API Routes propias de Next.js
│   ├── auth/        — Handler de better-auth
│   ├── [...rest]/   — Proxy transparente hacia FastAPI
│   └── thesis/[ticker]/ — Generación de PDF/EPUB/audio
fonts/
manifest.ts
robots.ts
sitemap.ts
```

**Componentes compartidos** (`components/`):

| Grupo | Contenido |
|---|---|
| `layout/` | Shell, sidebar, topbar, breadcrumbs, navegación global |
| `common/` | LoadingSpinner, ErrorBoundary, EmptyState, DataLabel |
| `chat/` | Interfaz de Cerebro (chat con el portfolio) |
| `brain/` | Contexto de página para Cerebro |
| `alerts/` | Tarjetas y centros de alertas |
| `thesis/` | Editor de tesis, timeline de versiones |
| `market/` | Cotizaciones, gráficos, screener |
| `knowledge/` | Biblioteca RAG, subida de documentos |
| `knowledge-graph/` | Visualización del grafo de conocimiento |

**Gestión de estado:**
- Estado del servidor: Server Components + server actions (`lib/actions/`)
- Estado de UI local: `useState`/`useReducer` de React
- Formularios: `react-hook-form` + validación Zod
- Sin capa de estado global (Redux/Zustand): datos llegan del servidor vía RSC o fetch directo

**Routing navigation:**
La navegación usa un único sistema de rutas en `lib/nav/` como fuente de verdad. Los breadcrumbs son contextuales y los enlaces entre páginas usan deep links canónicos, eliminando URLs hardcodeadas dispersas.

### 2.2 Capa backend (FastAPI)

```
data-engine/
├── app/
│   ├── api/routes/      — 50+ módulos de endpoints REST
│   ├── core/            — config.py, database.py, auth.py, seguridad
│   ├── models/          — Entidades SQLAlchemy (entities.py + módulos)
│   ├── schemas/         — Modelos Pydantic (request/response)
│   ├── services/        — Lógica de negocio (100+ servicios)
│   ├── llm/             — Capa de abstracción LLM (Cerebro)
│   ├── workers/         — Actores Dramatiq + scheduler APScheduler
│   ├── workflows/       — LangGraph workflows (ciclo de vida de tesis)
│   └── valuation/       — Motor de valoración fundamental
├── alembic/             — Migraciones de esquema Postgres
├── tests/               — Suite pytest
├── scripts/             — Utilidades: export_openapi.py, sync_requirements.py
└── Dockerfile.prod      — Imagen de producción Python 3.12 slim ARM64
```

**Módulos de API** (`app/api/routes/`): cada fichero corresponde a un dominio funcional. Los más relevantes:

| Módulo | Función |
|---|---|
| `portfolio.py` | Posiciones, valoración, snapshots |
| `thesis.py` | Tesis de inversión y versiones |
| `chat.py` | Interfaz de Cerebro (streaming LLM) |
| `companies.py` | Ficha, perfil y datos de empresa |
| `dca_settings.py` | Configuración y señales DCA |
| `alerts.py` | Reglas y entregas de alertas |
| `valuation.py` | Modelos de valoración |
| `knowledge_rag.py` | Consultas al RAG de conocimiento |
| `screeners.py` | Screener multi-criterio |
| `watchlist.py` | Lista de seguimiento |
| `portfolio.py` | Portfolio y posiciones |
| `health.py` | Estado del sistema |

### 2.3 Capa de datos

#### PostgreSQL 17
Base de datos relacional principal. Configuración: `max_connections=200`, `shared_buffers=256MB`. Solo accesible dentro de la red Docker interna (sin puerto público).

Pool de conexiones:
- Backend: 20 conexiones + 10 overflow = 30 máximo
- Cada worker: 4 conexiones + 2 overflow
- Total máximo en operación: ~84 conexiones (muy por debajo de max_connections=200)

#### Redis 7
Doble rol:
1. **Cola de mensajes:** broker de Dramatiq para las colas `default`, `thesis`, `kpis`, `alerts`, `computed`, `gdelt`, `knowledge`
2. **Caché:** respuestas LLM, datos de mercado frecuentes, sesiones de chat

Configuración: `maxmemory 768mb`, `maxmemory-policy noeviction` (presión se convierte en QueueCapacityError, no en pérdida silenciosa), AOF activado (durabilidad de jobs).

#### Qdrant 1.19.2
Almacén vectorial para dos usos:
1. **RAG de empresa:** chunks de documentos SEC, ESEF, earnings — búsqueda semántica sobre el corpus por empresa
2. **RAG de conocimiento profesional:** colección `knowledge_rag_v2` con embeddings e5-large (1024 dims) para documentos PDF/DOCX del usuario

Solo expuesto en loopback (`127.0.0.1:6333`).

#### MinIO / Garage (S3)
Almacenamiento de objetos:
- Documentos originales (PDFs de earnings, filings, documentos de conocimiento)
- Exportaciones generadas (PDF de tesis, EPUB, audio)
- Imágenes de portfolio

Bucket único `research`. La migración de MinIO a Garage es transparente: cambiar las variables `OBJECT_STORAGE_*` en `.env.production` sin tocar código.

### 2.4 Capa AI/LLM — Cerebro

```
data-engine/app/llm/
├── base.py              — Contrato de proveedor abstracto
├── adapters.py          — Adaptadores por proveedor (OpenCode Go, Groq, Gemini, OpenRouter)
├── cascade.py           — Lógica de cascada/fallback entre proveedores
├── factory.py           — Construcción de instancias por tenant
├── routing.py           — Selección de modelo según tipo de tarea
├── tenant_config.py     — API keys por tenant (cifradas en reposo con Fernet/AES-GCM)
├── response_cache.py    — Caché de respuestas LLM en Redis
├── egress_guard.py      — Control de salida: evita filtración de datos sensibles
├── run_guard.py         — Límites de ejecución y presupuesto
└── model_aliases.py     — Tabla de alias internos → modelo real del proveedor
```

**Arquitectura de Cerebro (híbrida):**

```
Usuario
  │
  ▼
chat.py (API route)
  │
  ├─── Contexto determinista ──▶ brain_context_tools.py
  │    (datos de la BD)           (posiciones, tesis, KPIs, DCA, alertas)
  │
  ├─── Búsqueda RAG ──────────▶ hybrid_retrieval.py
  │    (documentos y              (Qdrant dense + BM25 sparse)
  │     conocimiento)
  │
  ├─── Herramientas directas ─▶ brain_data_tools.py
  │    (DB queries en tiempo      (métricas en tiempo real)
  │     real)
  │
  └─── LLM (proveedor) ───────▶ cascade.py → adapters.py
       Proveedor primario: OpenCode Go (deepseek-v4.1-flash)
       Fallbacks: Groq → Gemini → OpenRouter :free
```

**Pipeline RAG:**
1. El documento ingresa por `document_ingestion_service.py` (MarkItDown rápido + Docling para PDFs complejos)
2. Se chunkea en `DocumentChunk` (Postgres) + embedding via fastembed (ONNX CPU-only)
3. Los vectores se almacenan en Qdrant
4. En tiempo de consulta: `hybrid_retrieval.py` combina búsqueda densa (e5-large) + dispersa (BM25)
5. Los chunks recuperados se pasan al LLM como contexto

---

## 3. Responsabilidades de componentes

### Frontend
- Renderizar la UI en español con Server Components donde sea posible
- Validar entradas del usuario con Zod antes de enviar al backend
- Mostrar etiquetas de procedencia (OFICIAL / INFERIDO / SIN_DATOS) en todos los datos
- Delegar toda lógica de negocio y cálculo al backend; el frontend no calcula ni infiere
- Gestionar el estado de autenticación a través de better-auth
- Actuar como proxy hacia FastAPI para rutas `/api/[...rest]`

### Backend (FastAPI)
- Autenticar y autorizar cada petición via `ResearchPrincipal` + tenant_id
- Servir todos los datos con sus etiquetas de procedencia
- Invocar servicios de negocio; nunca duplicar lógica entre servicios
- Enqueue jobs a Dramatiq para trabajo pesado (no bloquear peticiones HTTP)
- Exportar el contrato OpenAPI de forma aditiva (`data-engine/openapi.json`)

### Workers (Dramatiq)
Cada worker tiene una o más colas dedicadas para evitar inanición:

| Contenedor | Colas | Procesos/Hilos | Responsabilidad |
|---|---|---|---|
| `worker-default` | `default` | 1p/3h | Ingesta general, precios, scraping |
| `worker-thesis` | `thesis` | 1p/2h | Jobs interactivos de tesis (LLM habilitado) |
| `worker-kpis` | `kpis` | 1p/4h | Extracción y actualización de KPIs |
| `worker-alerts` | `alerts`, `computed` | 1p/2h | Evaluación de reglas, entregas, ProPicks |
| `worker-gdelt` | `gdelt` | 1p/2h | Ingesta GDELT (pacing global por IP) |
| `worker-knowledge` | `knowledge` | 1p/1h | RAG de conocimiento (Docling pesado) |

### Scheduler (APScheduler)
Único proceso. Encola jobs a Dramatiq según cron configurado. No ejecuta lógica de negocio directamente. Responsable de: ingesta periódica de precios, refresh de noticias, evaluación DCA, briefs diarios, retención de datos de privacidad.

### Servicios de dominio
Cada fichero en `app/services/` es responsable de una capacidad atómica. Los servicios no se llaman entre sí en cadena profunda; los actores Dramatiq orquestan secuencias complejas.

---

## 4. Interacciones entre componentes

### Flujo de petición HTTP (sincrónico)

```
Usuario → Next.js → /api/[...rest]/route.ts (proxy)
  → Caddy (TLS termination)
  → FastAPI (auth middleware → ResearchPrincipal)
  → API route (validación Pydantic)
  → Service (lógica de negocio)
  → SQLAlchemy (Postgres)
  → Respuesta JSON al cliente
```

### Flujo de trabajo en background (asincrónico)

```
Scheduler (APScheduler cron)
  → dramatiq.send(actor, args)
  → Redis (cola HSET)
  → Worker dedica a esa cola
  → Service (lógica de negocio)
  → Postgres / Qdrant / MinIO
  → (opcional) Notificación in-app / email / Telegram
```

### Consulta a Cerebro (LLM)

```
Usuario → /api/chat → chat.py (FastAPI route, streaming SSE)
  → brain_context_tools.py (datos deterministas del portfolio del tenant)
  → hybrid_retrieval.py (RAG: Qdrant dense + BM25 sparse)
  → brain_data_tools.py (métricas en tiempo real desde Postgres)
  → cascade.py → adaptador LLM → proveedor externo
  → response_cache.py (escribir caché Redis si aplica)
  → Stream de tokens al cliente vía SSE
```

### Ingesta de API externas

```
Scheduler / petición de usuario
  → Conector (FMP / Finnhub / Yahoo / SEC / GDELT / FRED / EIA)
  → Service de ingesta (normalización, deduplicación)
  → Postgres (datos estructurados) + MinIO (documentos originales)
  → (si aplica) Qdrant (chunks vectorizados)
  → Invalidar caché Redis pertinente
```

### Autenticación

```
Usuario → better-auth (Next.js API route /api/auth/[...all])
  → MongoDB Atlas M0 (sesiones y usuarios)
  → JWT / cookie de sesión → cliente
  
Petición autenticada al backend:
  → Header Authorization: Bearer <token>
  → FastAPI middleware: get_research_principal()
  → Verificar firma con RESEARCH_AUTH_SECRET
  → Extraer tenant_id
  → with_loader_criteria(TenantOwnedMixin, tenant_id == ...) en SQLAlchemy
    (aislamiento automático a nivel ORM)
```

---

## 5. Decisiones de diseño clave

### 5.1 Navegación unificada

**Qué:** Existe una única fuente de verdad para todas las rutas de la aplicación en `lib/nav/`. Los componentes de navegación, breadcrumbs y deep links desde alertas referencian este módulo. No hay strings de URL hardcodeados en componentes.

**Por qué:** Con >25 secciones en la aplicación, las URLs duplicadas en múltiples componentes causaban inconsistencias silenciosas. Un cambio de ruta requería búsqueda manual. La fuente única garantiza que los deep links desde alertas y Cerebro siempre apunten a la URL correcta.

**Cómo:** El módulo `lib/nav/` exporta un mapa de rutas tipado. Los breadcrumbs se generan de forma contextual según la ruta activa. Las alertas y respuestas de Cerebro usan este mapa para construir links de navegación.

### 5.2 Estandarización de componentes

**Qué:** Patrones únicos para loading (`LoadingSpinner`), error (`ErrorBoundary`) y estado vacío (`EmptyState`) en `components/common/`. Displays de datos consolidan etiquetas, valores monetarios y porcentajes en una sola API de componente.

**Por qué:** Sin estandarización, cada sección implementaba su propio spinner, placeholder vacío y manejo de error, con comportamientos inconsistentes y mayor superficie de bugs visuales.

**Cómo:** Los componentes `common/` son los únicos puntos de entrada para esos patrones. Las páginas importan de `common/`, no implementan sus propios estados intermedios. Los porcentajes usan el formato es-ES (`Intl.NumberFormat`).

### 5.3 Consolidación del pipeline de datos

**Qué:** Una única fuente de verdad por tipo de dato:
- Valoraciones: servicio único `fair_value_service.py` con fuente etiquetada (OFICIAL/INFERIDO/SIN_DATOS)
- Señales DCA: `dca_signal_service.py` + `dca_signal_engine.py` como motor único
- Estado de tesis: propagado desde la tesis activa hacia posición, alertas y Cerebro
- Timeline de noticias: `NewsEvent` unificado (GDELT + SEC + RSS + earnings)

**Por qué:** Antes existían cálculos de valoración duplicados entre el frontend y el backend con resultados que diferían. Las señales DCA tenían lógica dispersa. El estado de tesis no se propagaba.

**Cómo:** El backend es la única fuente de datos calculados. El frontend solo renderiza lo que recibe. Los servicios de dominio tienen contratos claros; los duplicados se eliminaron.

### 5.4 Estrategia de testing

**Backend:**
- Unit + integración: pytest con `hypothesis` para tests basados en propiedades
- Tests de mutación para verificar que los tests realmente detectan cambios
- Gate de cobertura via `.coveragerc`
- 4 tests conocidos que fallan en imagen slim sin git (`test_market_data_paths_are_ignored`)

**Frontend:**
- Unit/componente: vitest + @testing-library/react
- E2E: Playwright (con axe-core para accesibilidad)
- Contract drift: `scripts/contract-drift.mjs` detecta desviaciones entre el cliente TypeScript generado y `openapi.json`
- Cobertura: `npm run test:coverage`

---

## 6. Modelos de datos

### Entidades principales

```
Tenant
  ├── external_id (FK → MongoDB usuario)
  ├── name, status
  └── metadata_

Portfolio (TenantOwned)
  ├── name, base_currency
  └── positions[] → Position

Position (TenantOwned)
  ├── ticker, company_id
  ├── shares, avg_cost, currency
  ├── thesis_id (FK → Thesis, nullable)
  └── dca_signal_state[] → DcaSignalState

Company
  ├── ticker, name, isin, exchange, sector
  ├── market_cap, currency
  └── kpis[] → CompanyKPI

Thesis (TenantOwned)
  ├── ticker
  ├── status (active|archived|watchlist)
  ├── versions[] → ThesisVersion (inmutable, append-only)
  ├── claims[] → Claim
  ├── catalysts[] → Catalyst
  └── moat_assessment → MoatAssessment

DcaSignalState (TenantOwned)
  ├── ticker, level (1-5), direction (buy|trim|hold)
  ├── triggered_at, last_evaluated_at
  └── override → DcaAlertOverride

NewsEvent
  ├── source (gdelt|sec|rss|earnings|corporate_action)
  ├── ticker[], published_at, headline
  ├── sentiment_score, relevance_score
  └── second_order_analysis (JSON, LLM-generated, nullable)

AlertRule (TenantOwned)
  ├── type (price|dca|earnings|insider|custom)
  ├── condition (JSON)
  └── deliveries[] → AlertDelivery

Document (TenantOwned)
  ├── source_type, ticker, published_at
  ├── minio_key (ruta en MinIO)
  └── chunks[] → DocumentChunk → Qdrant vectors

KnowledgeDocument (TenantOwned)
  ├── filename, mime_type, minio_key
  ├── collection → KnowledgeCollection
  └── chunks[] → KnowledgeChunk → Qdrant (knowledge_rag_v2)

TenantLLMSettings (TenantOwned)
  ├── provider
  ├── api_key (cifrada, Fernet/AES-GCM)
  └── model_overrides (JSON)
```

### Aislamiento de tenant

Todas las entidades que heredan `TenantOwnedMixin` tienen `tenant_id FK → tenants.id`. SQLAlchemy aplica `with_loader_criteria` automáticamente en cada sesión de BD para filtrar por el tenant activo extraído del JWT. Un tenant nunca puede leer datos de otro aunque construya queries manuales.

---

## 7. Arquitectura de seguridad

### Autenticación
- better-auth gestiona registro, login, OAuth y sesiones
- Las sesiones se almacenan en MongoDB Atlas M0
- El frontend recibe una cookie de sesión httpOnly
- Para peticiones al backend, el frontend incluye `Authorization: Bearer <token>` firmado con `RESEARCH_AUTH_SECRET`
- El backend valida la firma en cada petición via `get_research_principal()`

### Autorización y aislamiento de tenant
- `ResearchPrincipal` encapsula el `tenant_id` verificado
- SQLAlchemy aplica `with_loader_criteria` en todas las queries sobre modelos `TenantOwnedMixin`
- No existe ninguna ruta de acceso que permita a un tenant leer datos de otro
- `RESEARCH_AUTH_REQUIRED=true` en producción rechaza peticiones sin token

### Protección de secretos
- Ningún secreto en el repositorio ni en logs
- Variables de entorno validadas al arranque por `config.py`: credenciales débiles conocidas (`postgres:password`, `minioadmin`, etc.) provocan fallo de arranque en `APP_ENV=production`
- Tokens placeholder del `.env.production.example` son detectados y rechazan el arranque
- API keys LLM por tenant cifradas en reposo con Fernet/AES-GCM en Postgres

### Otras medidas
- CSRF: mejor-auth gestiona tokens CSRF para Server Actions
- Rate limiting: Caddy puede aplicar rate limiting por IP a nivel de reverse proxy
- SSRF: `egress_guard.py` + httpcore con IP pinning controlan las peticiones de salida del backend
- Contenido: `egress_guard.py` verifica que las respuestas del LLM no filtren datos sensibles del tenant
- Auditoría: `PrivacyAuditEvent` registra accesos a datos personales; job de retención configurable via `RETENTION_JOB_ENABLED`

---

## 8. Arquitectura de rendimiento

### Estrategia de caché (Redis, capas)

| Capa | Qué se cachea | TTL aproximado |
|---|---|---|
| Respuestas LLM | Respuestas de Cerebro idénticas (hash de prompt+contexto) | Configurable |
| Datos de mercado | Cotizaciones, precios, screener | Minutos |
| Snapshots de portfolio | Valoración calculada del día | Hasta próximo precio |
| Sesiones de chat | Historial de conversación activa | Duración de sesión |

### Optimización de queries Postgres
- Índices declarados en `entities.py` para los campos de filtro más frecuentes (`ticker`, `tenant_id`, `published_at`, `status`)
- `UniqueConstraint` sobre las combinaciones más usadas para forzar deduplicación en BD, no en aplicación
- Pool de conexiones separado por proceso (backend vs. workers) para evitar contención
- Queries de snapshots diarios separadas de queries en tiempo real

### Frontend
- Server Components para datos sin interactividad: no hidratación en el cliente
- Lazy loading de componentes pesados (gráficos, editor de tesis)
- `lightweight-charts` en lugar de Recharts para las series temporales de mayor volumen
- Bundle separado por ruta gracias al App Router

### Workers
- Prefetch limitado por worker (`dramatiq_queue_prefetch`) para evitar que un worker acapare jobs que no puede procesar rápido
- Colas dedicadas por tipo de trabajo para evitar inanición entre jobs rápidos (alertas) y lentos (GDELT)

---

## 9. Consideraciones de escalabilidad

### Configuración actual (un usuario, VM Always Free)
- 4 OCPU / 24 GB RAM en Oracle ARM64
- Suma de límites de memoria de todos los servicios Docker: ~12 GB (deja ~12 GB para kernel, page cache y swap)
- Saturación de CPU esperada alrededor de ~100 usuarios concurrentes activos

### Bottlenecks conocidos
- **CPU:** Single VM. Los workers de ingesta (especialmente GDELT, ~3h de procesado por ciclo) y Docling (OCR/tablas) son los consumidores más pesados. No hay escalado horizontal hoy.
- **Conexiones Postgres:** max_connections=200, con pools definidos por proceso. Añadir workers sin ajustar pools puede agotar conexiones.
- **Redis maxmemory:** 768 MB. Presión excesiva convierte en QueueCapacityError (diseñado) pero bloquea ingesta.
- **Qdrant:** Memoria limitada a 768 MB. Colecciones grandes de RAG deben monitorizar uso con `GET /collections/{name}`.

### Preparación para escalado horizontal
- El backend FastAPI es stateless: puede desplegarse en múltiples réplicas detrás de Caddy
- Los workers Dramatiq consumen de Redis: escalar horizontalmente añadiendo réplicas de cada worker service
- Postgres es el cuello de botella en escalado horizontal; la migración a una BD gestionada (p.ej. Supabase) es la ruta natural
- El almacén de objetos (MinIO → Garage → S3) es ya nativamente horizontal
- Qdrant soporta clústeres; la configuración actual es nodo único

---

## 10. Arquitectura de despliegue

### Servicios Docker Compose (producción)

| Contenedor | Imagen | CPU límite | Memoria límite | Puertos |
|---|---|---|---|---|
| `cavaai-caddy` | caddy:2-alpine | 0.10 | 64 MB | 80, 443 (BIND_IP) |
| `cavaai-postgres` | postgres:17 | 0.75 | 896 MB | interno |
| `cavaai-redis` | redis:7-alpine | 0.25 | 896 MB | interno |
| `cavaai-qdrant` | qdrant/qdrant:v1.19.2 | 0.50 | 768 MB | 127.0.0.1:6333 |
| `cavaai-minio` | cavaai-minio (local) | 0.25 | 256 MB | interno |
| `cavaai-garage` | dxflrs/garage:v2.4.1 | 0.10 | 192 MB | interno |
| `cavaai-backend` | cavaai-backend:prod | 1.00 | 3072 MB | interno |
| `cavaai-worker-default` | cavaai-backend:prod | 0.75 | 3072 MB | — |
| `cavaai-worker-thesis` | cavaai-backend:prod | 0.50 | 1024 MB | — |
| `cavaai-worker-kpis` | cavaai-backend:prod | 0.40 | 448 MB | — |
| `cavaai-worker-alerts` | cavaai-backend:prod | 0.20 | 320 MB | — |
| `cavaai-worker-gdelt` | cavaai-backend:prod | 0.30 | 640 MB | — |
| `cavaai-worker-knowledge` | cavaai-backend:prod | 0.50 | 512 MB | — |
| `cavaai-scheduler` | cavaai-backend:prod | 0.10 | 128 MB | — |

**Total memoria límite declarada:** ~12.032 GB de 24 GB disponibles.

### Health checks
Todos los servicios declaran `healthcheck`. Postgres y Redis usan comandos nativos (`pg_isready`, `redis-cli ping`). Los workers y el scheduler verifican que su proceso principal esté vivo y que Redis responda, sin exponer puerto HTTP. Qdrant usa `/dev/tcp` desde bash (la imagen no incluye curl).

### Arranque y dependencias
El backend espera a que Postgres y Redis estén `healthy`. Los workers esperan a que el backend esté `healthy` (lo que implica que la BD está migrada). El scheduler depende solo de Redis.

### Dominio y TLS
- TLS terminado en Caddy con un subdominio DuckDNS (gratuito)
- `BACKEND_DOMAIN` configurable; soporta IP pública si no hay dominio
- `BIND_IP` configurable para entornos con Tailscale u otras configuraciones de red
- El frontend (Vercel) accede al backend por su dominio público con HTTPS

### Variables de entorno
Todas las variables secretas van en `.env.production` (no en el repositorio). El `.env.production.example` documenta cada variable con su descripción. `config.py` valida al arranque que no haya placeholders ni credenciales débiles conocidas en producción.

---

*Documento generado el 30 de octubre de 2026. Actualizar cuando cambien los límites de memoria declarados en docker-compose.prod.yml, se añadan nuevas colas de workers, o cambien los contratos de autenticación.*
