# Arquitectura del Sistema GerarAI

Fulfills: VAL-DOC-001 (document-architecture)

GerarAI es una plataforma integral de análisis fundamental, gestión de carteras y ejecución sistemática DCA, orientada a inversores particulares e institucionales. Cumple con estrictas premisas de seguridad multitenant, rendimiento en tiempo real y coste cero de infraestructura en modelos LLM (EUR0).

---

## 1. Diagrama de Componentes y Flujo de Datos

```mermaid
flowchart TD
    subgraph Client["Cliente / Navegador"]
        UI["Next.js Web UI\n(App Router + Tailwind)"]
    end

    subgraph Edge["Capa Frontend & Auth (Next.js Node.js Server)"]
        NextServer["Next.js Server Actions\n& API Routes"]
        BetterAuth["Better-Auth Engine\n(Sesiones de Usuario)"]
        MongoAuth["MongoDB\n(Colección Sesiones/Usuarios)"]
        HMACSigner["Firma Criptográfica HMAC-SHA256\n(RESEARCH_AUTH_SECRET)"]
    end

    subgraph CoreBackend["Motor de Datos: FastAPI Data-Engine"]
        FastAPI["FastAPI REST API\n(/api/v1 y endpoints de salud)"]
        AuthMiddleware["Tenant Scope & HMAC Verifier\n(Isolation db.info['tenant_id'])"]
        
        subgraph EngineServices["Servicios Especializados"]
            PortfolioSvc["Portfolio & Ledger Service\n(FIFO Contable LIRPF)"]
            TaxSvc["Tax Report Service\n(Modelo 100 / Casillas / Retenciones)"]
            DCASvc["DCA Signal Engine\n(1X-4X / Zonas / Recortes)"]
            CerebroRAG["Cerebro RAG & HyDE\n(Qdrant Client Pool + FastEmbed)"]
            PDFGen["Thesis & Portfolio PDF Generator\n(Matplotlib + PyPDF EUR0)"]
            ImportSvc["Transaction Multi-Format Importer\n(CSV / Excel XLSX)"]
        end

        subgraph Caching["Capa de Rendimiento"]
            RedisCache["Redis 7 (LRU Caching)\nTTL 5m-10m / Claves SHA256"]
        end
    end

    subgraph DataPersistence["Almacenamiento Persistente"]
        Postgres[("PostgreSQL 17\n(Esquema Relacional + Alembic)")]
        Qdrant[("Qdrant Vector DB\n(Embeddings de Tesis y Documentos)")]
        MinIO[("MinIO / Garage Object Storage\n(Informes, PDFs, Archivos)")]
    end

    subgraph ExternalSources["Fuentes Externas (EUR0)"]
        FMP["Financial Modeling Prep API"]
        AlphaVantage["Alpha Vantage Connector\n(Rate-Limited Free Tier)"]
        ECB["BCE (Banco Central Europeo)\nHistórico FX Diario Oficial"]
        SEC["SEC EDGAR / CNMV\n(Filings 10-K, 10-Q, Hechos Relevantes)"]
    end

    UI -->|"HTTPS / JSON"| NextServer
    NextServer --> BetterAuth
    BetterAuth <--> MongoAuth
    NextServer --> HMACSigner
    HMACSigner -->|"X-CavaAI-Signature / Headers"| FastAPI

    FastAPI --> AuthMiddleware
    AuthMiddleware --> EngineServices
    EngineServices <--> RedisCache
    EngineServices <--> Postgres
    CerebroRAG <--> Qdrant
    PDFGen --> MinIO
    ImportSvc --> Postgres
    EngineServices <--> ExternalSources
```

---

## 2. Aislamiento Multitenant y Seguridad Criptográfica

1. **Identidad Unificada**: Cada usuario autenticado en Next.js posee un `user.id`. El servidor Next.js firma las peticiones hacia el backend FastAPI mediante HMAC-SHA256 utilizando la clave simétrica `RESEARCH_AUTH_SECRET` con ventana temporal de validez (300 segundos para prevenir replay attacks).
2. **Contexto de Sesión en Base de Datos**: FastAPI valida la firma en `app/core/auth.py`. Al validarse, se inyecta el `tenant_id` en `db.info["tenant_id"]`.
3. **Filtros Estrictos de Aislamiento**: Cada consulta y mutación sobre entidades sensibles (`Portfolio`, `Transaction`, `Position`, `InvestmentPlan`, `TaxReport`) aplica obligatoriamente los predicados `*tenant_filters(db, Entity)` impidiendo cualquier fuga cross-tenant.

---

## 3. Esquema Relacional de Base de Datos (PostgreSQL)

```mermaid
erDiagram
    TENANTS ||--o{ PORTFOLIOS : owns
    PORTFOLIOS ||--o{ TRANSACTIONS : records
    PORTFOLIOS ||--o{ POSITIONS : aggregates
    PORTFOLIOS ||--o{ INVESTMENT_PLANS : guides
    PORTFOLIOS ||--o{ TAX_REPORTS : generates
    COMPANIES ||--o{ TRANSACTIONS : referenced_by
    COMPANIES ||--o{ POSITIONS : targets
    COMPANIES ||--o{ THESIS_VERSIONS : documented_in
    COMPANIES ||--o{ DCA_SIGNALS : evaluated_by

    TENANTS {
        string id PK
        string email
        string plan_tier
        datetime created_at
    }

    PORTFOLIOS {
        uuid id PK
        string tenant_id FK
        string name
        string base_currency
        boolean is_default
        datetime created_at
    }

    COMPANIES {
        int id PK
        string ticker UK
        string name
        string exchange
        string currency
        string sector
        string industry
        string company_type
        string valuation_model
    }

    TRANSACTIONS {
        uuid id PK
        string tenant_id FK
        uuid portfolio_id FK
        int company_id FK
        date trade_date
        string action
        decimal quantity
        decimal price
        decimal fees
        string currency
    }

    POSITIONS {
        uuid id PK
        string tenant_id FK
        uuid portfolio_id FK
        int company_id FK
        decimal quantity
        decimal average_cost
        decimal market_price
        decimal market_value
        decimal unrealized_pnl
        decimal realized_pnl
    }
```

---

## 4. Puntos de Integración del API

| Módulo | Endpoint Principal | Propósito | Autenticación |
|---|---|---|---|
| **Salud** | `GET /api/health` | Estado del motor, Postgres, Scheduler y versión | Pública |
| **Fuentes de Datos** | `GET /api/health/data-sources` | Circuit breaker y latencia de APIs externas | Requiere HMAC |
| **Cartera** | `GET /api/portfolio/summary` | Resumen contable, valor de mercado y rentabilidad | Requiere HMAC (Tenant) |
| **Transacciones** | `POST /api/portfolio/transactions` | Registro y replay contable FIFO de transacciones | Requiere HMAC (Tenant) |
| **Importación** | `POST /api/portfolio/import/preview` | Validación y parseo multiformato (CSV/Excel) | Requiere HMAC (Tenant) |
| **Exportación PDF** | `GET /api/portfolio/{portfolio_id}/pdf` | Generación de informe PDF institucional | Requiere HMAC (Tenant) |
| **Fiscalidad** | `GET /api/taxes/report/{fiscal_year}` | Cálculo de casillas Modelo 100 y compensación IRPF | Requiere HMAC (Tenant) |
| **DCA Engine** | `GET /api/watchlist/dca-signals` | Niveles 1X-4X, zonas de compra y recortes de la watchlist | Requiere HMAC |
| **Cerebro RAG** | `POST /api/chat` | Búsqueda semántica híbrida con pool Qdrant | Requiere HMAC |
| **Caché** | `GET /api/cache/stats` | Métricas de acierto/fallo y latencia de Redis | Requiere HMAC |

---

## 5. Estrategia de Rendimiento y Escalabilidad

- **Pool de Conexiones**: SQLAlchemy gestiona un pool con reciclaje automático (`pool_pre_ping=True`, tamaño 10, overflow 20).
- **Qdrant Client Pool**: Los clientes Qdrant se reutilizan de forma thread-safe evitando desconexiones y re-aperturas de sockets gRPC/HTTP.
- **Redis Multi-Layer Caching**: Claves deterministas SHA256 para cotizaciones (TTL 5 min), valoraciones de cartera (TTL 10 min) y señales DCA (TTL 5 min), con invalidación reactiva mediante eventos SQLAlchemy.
- **Generación PDF Zero-Cost**: Procesamiento asíncrono y en memoria de PDFs mediante matplotlib y pypdf, sin dependencias externas pesadas como Chromium/Puppeteer.
