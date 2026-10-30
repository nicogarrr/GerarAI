# Validation Contract: GerarAI v1.0 Mission

This document defines the testable behavioral assertions that validate completion of the GerarAI v1.0 mission. Each assertion has a stable ID, clear pass/fail criteria, and specifies the tool and evidence required.

---

## Area: Security

### VAL-SEC-001: CSRF protection on state-changing endpoints
POST /api/portfolio/add without CSRF token returns 403 Forbidden.
Tool: curl
Evidence: terminal(curl response with 403 status code)

### VAL-SEC-002: No hardcoded credentials in codebase
Search for hardcoded admin credentials, API keys, and passwords returns zero results.
Tool: ripgrep
Evidence: terminal(rg output showing no matches for common credential patterns)

### VAL-SEC-003: SQL injection protection on search endpoints
Portfolio search with SQL injection payloads returns sanitized results without DB errors.
Tool: curl
Evidence: terminal(curl response with 200 status, no error stack traces)

### VAL-SEC-004: SSRF protection on external data fetching
Attempt to fetch internal network resources (localhost, 169.254.x.x) via data sources returns 400 Bad Request.
Tool: curl
Evidence: terminal(curl response with 400 status and error message)

### VAL-SEC-005: Command injection protection on file operations
Thesis export with shell metacharacters in filename returns sanitized filename without command execution.
Tool: curl
Evidence: terminal(curl response showing sanitized filename, no unexpected process output)

### VAL-SEC-006: Security headers present on all routes
All HTML responses include CSP, X-Frame-Options, X-Content-Type-Options headers.
Tool: curl
Evidence: terminal(curl -I output showing security headers on /, /dashboard, /portfolio)

### VAL-SEC-007: Foreign key cascades prevent orphaned records
Deleting a portfolio cascades to holdings, transactions, and alerts.
Tool: pytest
Evidence: terminal(pytest output showing test_cascade_delete_portfolio passes)

### VAL-SEC-008: No sensitive data in error responses
500 errors return generic message without stack traces or DB schema details.
Tool: agent-browser
Evidence: screenshot(error page showing generic message, no stack trace)

---

## Area: Performance

### VAL-PERF-001: Portfolio page loads under 1s with 100 holdings
Dashboard with 100 holdings loads fully (LCP) in <1000ms on simulated Fast 3G.
Tool: agent-browser
Evidence: devtools(performance tab showing LCP < 1000ms)

### VAL-PERF-002: No N+1 queries on holdings list
Loading portfolio with 50 holdings executes ≤5 SQL queries.
Tool: pytest + SQLAlchemy query counter
Evidence: terminal(pytest output showing query count ≤5)

### VAL-PERF-003: Cache hit rate >80% for market data
After initial load, 80%+ of market data requests hit Redis cache (status 304 or X-Cache: HIT).
Tool: curl + curl timing
Evidence: terminal(curl responses showing cache headers)

### VAL-PERF-004: Main bundle size <200KB gzipped
Next.js main bundle is <200KB after gzip compression.
Tool: Execute
Evidence: terminal(du -h .next/static/chunks/main-*.js output)

### VAL-PERF-005: Images served in modern formats
Portfolio images use WebP or AVIF with fallbacks, not raw PNG/JPG.
Tool: agent-browser
Evidence: devtools(network tab showing image/* with modern Content-Type)

### VAL-PERF-006: API response time <200ms p95
95th percentile API response time for /api/portfolio/list is <200ms under normal load.
Tool: Execute (load test script)
Evidence: terminal(load test summary showing p95 < 200ms)

### VAL-PERF-007: Database indexes on foreign keys
All 20 planned indexes exist on foreign key columns and frequently queried fields.
Tool: pytest
Evidence: terminal(pytest output showing test_database_indexes_present passes)

### VAL-PERF-008: Static assets have cache headers
JS/CSS/image assets return Cache-Control: public, max-age=31536000, immutable.
Tool: curl
Evidence: terminal(curl -I output showing cache headers on static assets)

---

## Area: UI/UX

### VAL-UX-001: Navigation completeness
All top-level routes (/dashboard, /portfolio, /research, /alerts, /settings) are reachable from global nav.
Tool: agent-browser
Evidence: screenshot(global nav showing all routes)

### VAL-UX-002: No dead-end pages
Every page has at least one actionable CTA or navigation option to continue user journey.
Tool: agent-browser
Evidence: screenshots(sample pages showing CTAs or nav)

### VAL-UX-003: Responsive design 320px-2560px
All pages render without horizontal scroll on 320px, 768px, 1920px viewports.
Tool: agent-browser
Evidence: screenshots(same page at 3 viewport widths)

### VAL-UX-004: Touch targets ≥44px
All interactive elements (buttons, links, inputs) have minimum 44×44px touch area.
Tool: agent-browser + devtools
Evidence: devtools(computed dimensions of interactive elements)

### VAL-UX-005: Cumulative Layout Shift <0.1
CLS score is <0.1 on portfolio page load with skeleton loaders preventing reflow.
Tool: agent-browser
Evidence: devtools(performance insights showing CLS < 0.1)

### VAL-UX-006: Professional design quality
Dashboard matches Bloomberg-quality standards: professional typography, consistent spacing, no Comic Sans.
Tool: agent-browser
Evidence: screenshot(dashboard showing professional design)

### VAL-UX-007: Unified navigation pattern
Navigation is consistent across all pages (same position, same structure).
Tool: agent-browser
Evidence: screenshots(nav from 3 different pages showing consistency)

### VAL-UX-008: Loading states present
Long operations show skeleton loaders or progress indicators, not blank screens.
Tool: agent-browser
Evidence: screenshot(portfolio loading state with skeleton)

### VAL-UX-009: Error recovery pathways
Error pages include "Return to Dashboard" and "Try Again" CTAs.
Tool: agent-browser
Evidence: screenshot(error page with recovery CTAs)

### VAL-UX-010: Keyboard navigation support
All interactive elements are keyboard-accessible (Tab, Enter, Space navigation).
Tool: agent-browser
Evidence: devtools(accessibility tree showing focusable elements)

---

## Area: Content Quality

### VAL-CONTENT-001: No generic error messages
All error messages are specific (e.g., "Portfolio 'Tech Growth' not found" not "Error occurred").
Tool: agent-browser
Evidence: screenshot(specific error message)

### VAL-CONTENT-002: Empty states have CTAs
Empty portfolio state shows "Add Your First Holding" CTA, not just "No data".
Tool: agent-browser
Evidence: screenshot(empty state with CTA)

### VAL-CONTENT-003: Error codes present
All error responses include error codes (e.g., ERR_PORTFOLIO_NOT_FOUND).
Tool: curl
Evidence: terminal(curl response showing error code in JSON)

### VAL-CONTENT-004: Specific validation messages
Form validation shows field-specific messages (e.g., "Ticker must be 1-5 uppercase letters" not "Invalid input").
Tool: agent-browser
Evidence: screenshot(form validation with specific message)

### VAL-CONTENT-005: AI slop elimination progress
Search for 485 generic placeholder texts returns <10% remaining.
Tool: ripgrep
Evidence: terminal(rg output showing <49 matches for generic patterns)

### VAL-CONTENT-006: Spanish text consistency
All user-facing text is in Spanish with correct es-ES number/date formatting.
Tool: agent-browser + ripgrep
Evidence: screenshot(UI in Spanish) + terminal(rg confirming no mixed-language strings)

### VAL-CONTENT-007: Contextual help text
Complex forms include help text explaining field purpose and format.
Tool: agent-browser
Evidence: screenshot(form with help text)

### VAL-CONTENT-008: Meaningful page titles
All pages have descriptive <title> tags (e.g., "Cartera Tech Growth - GerarAI" not "Page").
Tool: agent-browser
Evidence: devtools(HTML showing specific title tags)

---

## Area: Data Integration

### VAL-DATA-001: Thesis PDF export works end-to-end
Generate thesis for portfolio → export to PDF → verify PDF contains portfolio name, holdings, analysis.
Tool: agent-browser + Execute
Evidence: screenshot(export dialog) + terminal(pdfinfo output showing metadata)

### VAL-DATA-002: Top 5 data sources integrated
Yahoo Finance, FRED, Investing.com, TradingView, Alpha Vantage are integrated and return data.
Tool: pytest
Evidence: terminal(pytest output showing test_data_source_integration passes for 5 sources)

### VAL-DATA-003: External API failure handling
When data source returns 500, app shows cached data or "Data temporarily unavailable", not 500 error.
Tool: pytest + mock
Evidence: terminal(pytest output showing graceful degradation test passes)

### VAL-DATA-004: Data source attribution
Charts and data tables show source attribution (e.g., "Fuente: Yahoo Finance").
Tool: agent-browser
Evidence: screenshot(chart with attribution text)

### VAL-DATA-005: Rate limit handling
Exceeding data source rate limit triggers backoff and queues request, not immediate 429 to user.
Tool: pytest
Evidence: terminal(pytest output showing rate limit handling test passes)

### VAL-DATA-006: Data freshness indicators
Market data shows last update timestamp (e.g., "Actualizado hace 5 min").
Tool: agent-browser
Evidence: screenshot(data with freshness indicator)

### VAL-DATA-007: Qdrant RAG integration
RAG search returns relevant results from vector store for financial queries.
Tool: pytest
Evidence: terminal(pytest output showing test_qdrant_rag_search passes)

### VAL-DATA-008: MinIO file storage
Thesis PDF files are stored in MinIO and retrievable via signed URLs.
Tool: Execute
Evidence: terminal(mc ls output showing uploaded PDFs)

---

## Area: Database

### VAL-DB-001: Foreign key cascades present
All 58 planned FK cascade constraints exist in production schema.
Tool: Execute (psql)
Evidence: terminal(psql output showing 58 cascade constraints)

### VAL-DB-002: Indexes on query-heavy columns
20 planned indexes exist on portfolio_id, user_id, ticker, created_at, etc.
Tool: Execute (psql)
Evidence: terminal(psql \di output showing 20+ indexes)

### VAL-DB-003: No orphaned records after cascade delete
Deleting user cascades to portfolios → holdings → transactions with zero orphans.
Tool: pytest
Evidence: terminal(pytest output showing orphan detection test passes)

### VAL-DB-004: Backup and restore works
Database backup completes successfully and restores to clean instance without data loss.
Tool: Execute
Evidence: terminal(pg_dump success + pg_restore verification query output)

### VAL-DB-005: Migration rollback safety
Alembic downgrade migrations complete without errors.
Tool: Execute
Evidence: terminal(alembic downgrade -1 output showing success)

### VAL-DB-006: Connection pool efficiency
Database connection pool maintains 5-20 connections under normal load, not exhausting max.
Tool: Execute (psql)
Evidence: terminal(psql query showing active connection count)

### VAL-DB-007: Unique constraint on portfolio name per user
Creating duplicate portfolio name for same user returns 409 Conflict.
Tool: curl
Evidence: terminal(curl response with 409 status)

### VAL-DB-008: Database schema documentation
Alembic migrations include descriptive comments explaining purpose.
Tool: ripgrep
Evidence: terminal(rg output showing migration docstrings)

---

## Area: Coverage

### VAL-COV-001: Backend coverage ≥85%
pytest --cov shows ≥85% line coverage for data-engine/ excluding tests.
Tool: pytest
Evidence: terminal(pytest --cov output showing ≥85%)

### VAL-COV-002: Frontend coverage ≥80%
Jest/Vitest shows ≥80% line coverage for app/, components/, lib/ excluding tests.
Tool: Execute (npm test)
Evidence: terminal(coverage summary showing ≥80%)

### VAL-COV-003: Financial calculation coverage ≥95%
Core financial calculation modules (portfolio valuation, returns, risk) have ≥95% coverage.
Tool: pytest
Evidence: terminal(pytest --cov=data_engine/finance output showing ≥95%)

### VAL-COV-004: Critical path tests exist
Tests cover portfolio creation, holding addition, thesis generation, PDF export.
Tool: pytest
Evidence: terminal(pytest output showing 4 critical path tests pass)

### VAL-COV-005: Edge case tests exist
Tests cover boundary conditions (empty portfolio, single holding, 1000 holdings, zero price).
Tool: pytest
Evidence: terminal(pytest output showing edge case tests pass)

### VAL-COV-006: Error path tests exist
Tests verify error handling (network failure, invalid ticker, database timeout).
Tool: pytest
Evidence: terminal(pytest output showing error path tests pass)

---

## Area: Documentation

### VAL-DOC-001: Runbooks exist for critical operations
Runbooks exist for deployment, database migration, backup/restore, incident response.
Tool: ripgrep
Evidence: terminal(rg output showing 4 runbook files in docs/)

### VAL-DOC-002: Onboarding completes in <2h
New developer can clone repo, run setup script, start local environment in <2h following CONTRIBUTING.md.
Tool: tuistory (manual validation)
Evidence: terminal(time log showing setup completion < 2h)

### VAL-DOC-003: No file >1500 lines
All source files are ≤1500 lines (excluding generated openapi.json).
Tool: Execute
Evidence: terminal(find + wc -l output showing no files >1500 lines)

### VAL-DOC-004: API documentation current
openapi.json matches current API endpoints (regenerated via scripts/export_openapi.py).
Tool: Execute
Evidence: terminal(diff showing openapi.json matches current routes)

### VAL-DOC-005: Environment variables documented
.env.production.example includes all required variables with descriptions.
Tool: ripgrep
Evidence: terminal(rg output showing documented env vars match actual usage)

### VAL-DOC-006: Architecture decision records exist
docs/architecture/ contains ADRs for major design decisions (database choice, caching strategy, etc.).
Tool: Execute
Evidence: terminal(ls docs/architecture/ showing ADR files)

### VAL-DOC-007: Troubleshooting guide exists
docs/troubleshooting.md covers common issues and solutions.
Tool: ripgrep
Evidence: terminal(cat docs/troubleshooting.md showing content)

---

## Cross-Area Flows

### VAL-CROSS-001: Complete investment research journey
User searches ticker → views research page → adds to portfolio → monitors alerts without dead ends or errors.
Tool: agent-browser
Evidence: screenshot(search results) + screenshot(research page) + screenshot(portfolio page) + screenshot(alerts page)

### VAL-CROSS-002: Thesis generation end-to-end with performance
Request thesis → generate (completes <10s) → export PDF (file <2MB) → open PDF (contains portfolio name, 5+ holdings, analysis sections) → PDF passes validation.
Tool: agent-browser + Execute
Evidence: screenshot(thesis page) + screenshot(export dialog) + terminal(pdfinfo + file size) + screenshot(opened PDF)

### VAL-CROSS-003: Alert notification to action
Receive alert (price change) → click notification → navigate to specific portfolio section → view holding details → take action (sell/adjust).
Tool: agent-browser
Evidence: screenshot(alert list) + screenshot(portfolio section) + screenshot(holding details) + screenshot(action dialog)

### VAL-CROSS-004: Data source integration flow with caching
Fetch market data (initial = slow) → display chart → refresh (cache hit = fast <100ms) → handle data source failure (show cached data + warning).
Tool: agent-browser + devtools
Evidence: devtools(network showing initial 500ms, cached 50ms) + screenshot(chart) + screenshot(cached data with warning)

### VAL-CROSS-005: Error recovery across boundaries
Trigger error in backend → frontend shows specific error + recovery CTAs → click "Try Again" → successful retry → data displays.
Tool: agent-browser
Evidence: screenshot(error state) + screenshot(retry action) + screenshot(success state)

### VAL-CROSS-006: Responsive research workflow
Search ticker on mobile (320px) → add to portfolio → view portfolio on tablet (768px) → export thesis on desktop (1920px) all without layout breaks.
Tool: agent-browser
Evidence: screenshot(mobile search) + screenshot(tablet portfolio) + screenshot(desktop thesis)

### VAL-CROSS-007: Multi-user data isolation
User A creates portfolio → User B cannot see/edit User A's portfolio → User A deletes portfolio → User B's data unaffected.
Tool: pytest
Evidence: terminal(pytest output showing multi-user isolation test passes)

### VAL-CROSS-008: End-to-end security validation
Unauthenticated user → redirected to login → authenticate → access dashboard → CSRF token present in forms → logout → session invalidated.
Tool: agent-browser
Evidence: screenshot(redirect to login) + screenshot(dashboard) + devtools(showing CSRF token) + screenshot(logout)

---

## Assertion Summary

**Total Assertions:** 77

**Count by Area:**
- Security: 8
- Performance: 8
- UI/UX: 10
- Content Quality: 8
- Data Integration: 8
- Database: 8
- Coverage: 6
- Documentation: 7
- Cross-Area Flows: 8

**Stability Tracking:**
Each assertion ID is stable and will be tracked in `validation-state.json` with status: pending | passed | failed | skipped.
