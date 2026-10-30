# GerarAI v1.0: Complete App Closure & Production Readiness

# GerarAI v1.0: Complete App Closure & Production Readiness

## Plan Overview

Transform GerarAI from functional v0.5.0 into a production-ready, professional-grade investment analysis platform with **zero bugs**, **unified UX**, **85%+ test coverage**, and **Bloomberg/TradingView-level polish** - all within EUR 0 budget constraint.

**Current State:** v0.5.0 with 980+ merges, strong technical foundation, but 9 critical production blockers and 485+ quality issues across security, performance, UX, and coherence.

**Target State:** Production-ready v1.0 with all critical vulnerabilities fixed, professional UI, unified navigation, comprehensive testing, 15 new free data sources integrated, and complete feature interconnection.

## Expected Functionality

### Milestone 1: Critical Security & Data Integrity (3-4 weeks) - **BLOCKING**
**Objective:** Fix production-blocking security vulnerabilities and database integrity issues.

**Features:**
- Fix 3 CRITICAL security vulnerabilities (hardcoded credentials, SQL injection, weak sessions)
- Implement CSRF protection across all state-changing endpoints
- Add 58 missing database FK CASCADE rules for data integrity
- Add 20 critical missing indexes (10x performance improvement on hot paths)
- Fix SSRF vulnerability in image optimization
- Implement command injection protection in OCR service
- Add security headers (CSP, HSTS, X-Frame-Options)
- Rotate leaked API keys following documented procedure

**Acceptance Criteria:**
- Zero CRITICAL or HIGH security vulnerabilities
- All FK constraints have proper CASCADE/SET NULL behavior
- All foreign key columns indexed
- Security scan (Semgrep, CodeQL) passes with zero critical findings
- Backup/restore procedure tested and documented

### Milestone 2: Performance & Scalability (2-3 weeks)
**Objective:** Eliminate N+1 queries, add caching, optimize assets for fast load times.

**Features:**
- Fix 7 N+1 query patterns in core services (chat, thesis, ingestion)
- Implement LLM response caching (80% cost reduction)
- Optimize images to WebP (600KB reduction)
- Add eager loading with selectinload/joinedload
- Implement Redis caching for expensive operations
- Add dynamic imports for heavy frontend components
- Remove unused dependencies (mongoose from frontend)
- Add database query monitoring with pg_stat_statements

**Acceptance Criteria:**
- Portfolio page loads <1s with 100 holdings
- Chat responses use cache 80%+ of the time
- No N+1 queries in hot paths (detected by query logging)
- Bundle size reduced by 20%+
- Images optimized to WebP format

### Milestone 3: Professional UI & Coherence (4-5 weeks)
**Objective:** Transform to Bloomberg-quality design with unified navigation and complete feature interconnection.

**Features:**
- **Quick Wins (12 UI improvements, <2h each):** Reduce CardTitle size, add button shadows, speed up transitions, hover lift on cards, chart export buttons
- **Navigation Unification:** Complete navigation graph, fix alert→action flow, surface hidden features (Knowledge Graph, Insider Trading, Paper Trading)
- **Route Consolidation:** Merge `/screener` + `/screeners`, remove `/export`, unified calendar navigation
- **Component Standardization:** Single loading pattern, single error pattern, unified empty states, consolidated DCA badge
- **Professional Features:** TanStack Table integration, advanced filter system, global density toggle, keyboard shortcuts
- **Responsive Excellence:** Fix all mobile issues, ensure 44px touch targets, eliminate CLS
- **Chart Enhancements:** Comparison mode, more indicators, export to PNG, full-screen mode

**Acceptance Criteria:**
- Zero orphaned routes or dead-end pages
- All alerts link to specific sections (not generic overview)
- All interactive elements have hover states
- CLS < 0.1 on all pages
- Design matches Bloomberg/TradingView professional quality
- Navigation feels unified as single app

### Milestone 4: AI Slop Elimination & Content Quality (1-2 weeks)
**Objective:** Replace 485 generic/low-value text instances with specific, actionable content.

**Features:**
- Replace 20 HIGH severity user-facing errors with specific messages + error codes
- Add CTAs to all empty states (watchlist, portfolio, screener, search)
- Replace backend generic errors with specific reasons
- Implement error message standards with codes
- Add form validation feedback (specific reasons, not "invalid")
- Remove all "Coming soon" without timeline
- Add actionable guidance to all "No data" states

**Acceptance Criteria:**
- Zero "Something went wrong" messages
- All errors include error code and suggested action
- All empty states have clear next step
- All form errors explain what's wrong and how to fix

### Milestone 5: Data Source Integration & Features (3-4 weeks)
**Objective:** Integrate 15 free data sources and implement missing critical features.

**Features:**
- **Thesis PDF Export Service:** Implement comprehensive PDF generation (missing critical feature)
- **Free Data Sources (Top 5):** World Bank Open Data, Alpha Vantage, Tiingo, Quandl fundamentals, Google Trends
- **Additional Sources:** NewsAPI, Reddit sentiment, IMF Data, OECD indicators
- **Thesis Enhancement:** Comprehensive thesis generation using all RAG context, SEC filings, news, fundamentals
- **Thesis Summary:** Executive summary with key points extraction
- **Cross-References:** Link thesis mentions to source data (Q3 revenue → financial statement)

**Acceptance Criteria:**
- Thesis PDF exports with >10 pages, data tables, charts, full analysis
- All 5 top data sources integrated with proper rate limiting
- Thesis includes RAG context, news, filings, market data
- No connector returns HTTP 500 on external failure

### Milestone 6: Test Coverage & Documentation (2-3 weeks)
**Objective:** Achieve 85%+ coverage, refactor giant files, add operational runbooks.

**Features:**
- Increase backend coverage from 81% to 85%+
- Add reproduction tests for all discovered bugs
- Refactor 3 giant service files (financial_ingestion 3123 lines, chat 2954 lines, entities 2572 lines)
- Create 5 operational runbooks (incident response, rollback, common failures, backup/restore, scaling)
- Document complex subsystems (Chat/LLM, RAG, Financial Ingestion, Valuation engines)
- Add "How It Works" guides for key algorithms
- Create developer FAQ and onboarding guide

**Acceptance Criteria:**
- Backend coverage >= 85%
- Frontend coverage >= 80%
- All financial calculation files >= 95% coverage
- No file >1500 lines
- 5 operational runbooks complete
- Onboarding time documented and <2 hours

## Architecture

### System Overview
GerarAI is a full-stack investment analysis platform with:
- **Frontend:** Next.js 16 (App Router) + React 19 + TypeScript 5
- **Backend:** FastAPI + Python 3.12 + SQLAlchemy + Alembic
- **Databases:** PostgreSQL (primary), Redis (cache/queue), Qdrant (RAG vectors), MinIO (object storage)
- **AI/Brain:** LLM-powered "Cerebro" with hybrid architecture (deterministic tools + RAG + direct DB queries)
- **Deployment:** Docker Compose on Oracle Cloud Always Free (EUR 0/month)

### Key Architectural Decisions

**1. Unified Navigation Architecture:**
- Single source of truth for navigation state
- Contextual breadcrumbs everywhere
- Cross-page action links (screener → research → portfolio)
- Alert → specific section deep links

**2. Component Standardization:**
- Single loading pattern (skeletons with <200ms threshold)
- Single error pattern (ErrorState component everywhere)
- Unified empty states (EmptyState component with CTA)
- Consolidated data display (DCABadge, PriceDisplay, ValuationChip)

**3. Data Pipeline Consolidation:**
- All DCA signals from single service
- Valuation always labeled with source
- Thesis status propagated to watchlist/portfolio
- News unified timeline across all sections

**4. Testing Strategy:**
- Property-based testing for financial calculations
- Mutation testing for critical paths
- E2E tests for complete user journeys
- Visual regression tests for UI

### Cerebro Interconnection (Already Complete ✓)
Cerebro has full access to all app data:
- Company DCF valuations ✓
- Latest news ✓
- RAG ingested documents ✓
- SEC/ESEF filings ✓
- DCA signals ✓
- Portfolio holdings ✓
- Thesis content ✓
- Market data ✓

No critical gaps exist. Architecture uses direct service imports for reliability.

## Environment Setup

### Prerequisites
- **Node.js:** 20+ (frontend)
- **Python:** 3.12 (backend)
- **uv:** Package manager (backend)
- **Docker:** For services (Postgres, Redis, Qdrant, MinIO)
- **Git:** For version control

### Local Development Setup
```bash
# Clone repo
git clone https://github.com/nicogarrr/GerarAI
cd GerarAI

# Frontend setup
npm install

# Backend setup
cd data-engine
uv sync --frozen --extra test --extra dev

# Start services
docker compose up -d postgres redis qdrant minio

# Run migrations
cd data-engine
APP_ENV=development alembic upgrade head

# Start dev servers
npm run dev          # Frontend on :3000
cd data-engine && uvicorn app.main:app --reload  # Backend on :8000
```

### Environment Variables
See `.env.production.example` for complete list. Critical vars:
- `DATABASE_URL`: Postgres connection
- `REDIS_URL`: Redis connection
- `QDRANT_URL`: Vector DB connection
- `OPENCODE_GO_API_KEY`: LLM provider (only paid service)
- `LLM_SETTINGS_ENCRYPTION_KEY`: For secure API key storage
- `NEXT_PUBLIC_SITE_URL`: Frontend URL

## Infrastructure

### Services (docker-compose.prod.yml)
- **caddy:** Reverse proxy with HTTPS
- **postgres:** Primary database (12 GB allocated)
- **redis:** Cache and job queue
- **qdrant:** Vector store for RAG
- **minio:** Object storage
- **backend:** FastAPI application (2 CPU limit)
- **worker:** Background job processor (1 CPU limit)
- **worker-kpis:** KPI computation
- **worker-thesis:** Thesis generation
- **worker-docling:** Document processing
- **scheduler:** Scheduled tasks

### Port Ranges
- **3000-3099:** Reserved (existing services)
- **3100-3199:** Mission workers allowed (defined in AGENTS.md)

### Off-Limits Resources
- **Production containers:** No direct modification without backup
- **Port 3000:** User's main dev server
- **`/data` directory:** Do not read or modify
- **Port 6379 Redis:** Belongs to another project

### Boundaries
All workers MUST stay within allocated port range and never touch off-limits resources. If blocked, return to orchestrator rather than violate boundaries.

## Testing Strategy

### Verification Requirements (Mandatory)
1. **Bug Reproduction:** Every bug fix requires failing test on `main` first, then fix, then passing test
2. **UI Changes:** Before/after screenshots at 375px and 1280px using Playwright (Chromium + WebKit)
3. **Financial Calculations:** Manual verification with sample data, compare against known-good baseline
4. **Numerical Claims:** Measured output (command + result), not estimates
5. **Database Operations:** Backup before any non-ephemeral writes

### Test Levels
- **Unit Tests:** Pure functions, business logic, calculations (pytest, vitest)
- **Integration Tests:** Service interactions, API contracts, database operations
- **E2E Tests:** Complete user journeys (Playwright)
- **Property Tests:** Financial calculation invariants (Hypothesis)
- **Mutation Tests:** Test quality verification

### Gates (Must Pass)
**Backend (from data-engine/):**
```bash
uv sync --frozen --extra test --extra dev --no-install-project
ruff check .
pyright  # 0 errors
scripts/export_openapi.py  # Regenerate OpenAPI
APP_ENV=test pytest -q -p no:warnings
```

**Frontend:**
```bash
npm run lint
npm run typecheck
npm run test:e2e
npm run test:coverage
```

### Known Test Exceptions
- 4 tests fail in slim Docker image without `git` (test_repo_and_image_hygiene.py) - expected behavior
- Any other failures are bugs

## User Testing Strategy

### Testing Surfaces
1. **Desktop Browser (1280px):** Chrome, Safari, Firefox
2. **Mobile Browser (375px):** iOS Safari, Chrome Android
3. **Real User Flows:** Investment research → portfolio management → monitoring
4. **Data Integrity:** Tax calculations, FIFO, DCA signals, valuations

### Testing Tools
- **Playwright:** E2E automation, screenshot capture
- **Browser DevTools:** Network, performance, accessibility audits
- **Manual Testing:** Financial accuracy verification with real data samples

### Manual Validation Required For
- **Financial Calculations:** Tax reports, FIFO lot matching, DCA levels
- **Thesis Quality:** Read generated thesis for META, verify comprehensiveness
- **Professional Design:** Visual comparison to Bloomberg Terminal/TradingView
- **Navigation Flows:** Complete user journeys without dead ends

## Mission Readiness

### Verified Dependencies
- ✅ Next.js 16, React 19, TypeScript 5
- ✅ FastAPI 0.115.6, Python 3.12
- ✅ PostgreSQL, Redis, Qdrant, MinIO
- ✅ uv (Python package manager)
- ✅ Docker & Docker Compose
- ✅ CI/CD: 20 GitHub Actions workflows

### Validation Path Executable
- ✅ Test suites run successfully (1083 backend tests, 73 frontend tests)
- ✅ Gates configured (lint, typecheck, coverage)
- ✅ Security scanning (Semgrep, CodeQL, Gitleaks)
- ✅ Migration system healthy (103 migrations, no branches)

### Deployment Infrastructure
- ✅ Oracle Cloud Always Free (EUR 0/month)
- ✅ Automated daily backups with verification
- ✅ Health endpoints implemented
- ✅ Rollback procedure documented
- ✅ Resource limits configured (2 CPU backend, 1 CPU workers)

## Non-Functional Requirements

### Performance
- **Portfolio page load:** <1s with 100 holdings
- **Chat response:** <3s (first token) with streaming
- **API p95 latency:** <500ms
- **Bundle size:** <500 KB initial load

### Security
- **Zero CRITICAL vulnerabilities:** Before production
- **OWASP Top 10:** Full compliance
- **GDPR:** Data export + deletion implemented
- **Rate limiting:** All public endpoints
- **CSRF protection:** All state-changing operations

### Availability
- **Target uptime:** 99%+ (acceptable brief downtime for personal use)
- **RTO (Recovery Time):** 30 minutes
- **RPO (Recovery Point):** 24 hours (daily backups)
- **Graceful degradation:** External API failures return 200 with limited data, not 500

### Scalability
- **Current capacity:** ~100 concurrent users (CPU bound)
- **Database connections:** 150 concurrent (pool limit)
- **Architecture:** Ready to scale horizontally when needed

### Maintainability
- **Code coverage:** 85%+ backend, 80%+ frontend
- **No file >1500 lines:** After refactoring
- **Documentation score:** 90%+
- **Onboarding time:** <2 hours

### Quality
- **Zero bugs:** Complete bug elimination
- **Zero AI slop:** All generic text replaced
- **Professional design:** Bloomberg/TradingView quality
- **Unified UX:** Single coherent app experience

---

**Timeline:** 13-18 weeks to v1.0 production-ready
**Budget:** EUR 0 (LLM API key only)
**Risk:** MEDIUM (well-defined scope, mature codebase, clear critical path)