# GerarAI v1.0 Mission: Agent Guidance

## Mission Boundaries (NEVER VIOLATE)

**Port Range:** 3100-3199. Never start services outside this range.

**Existing Services (DO NOT TOUCH):**
- Port 3000: User's main dev server
- Port 6379: Redis (belongs to another project)
- Port 5432: Postgres (use, but don't restart)
- Port 8000: Backend API (existing)

**Off-Limits:**
- `/data` directory - do not read or modify
- Production containers - no direct modification without backup
- Any service running on ports outside 3100-3199 range

**If Blocked:** Return to orchestrator. Never violate boundaries to complete work.

---

## Mission Directives

### Tools
**Backend:**
- `uv` - Python package manager (NOT pip)
- `pytest` - Test runner
- `ruff` - Linter
- `pyright` - Type checker
- `alembic` - Database migrations

**Frontend:**
- `npm` - Package manager
- `playwright` - E2E testing and screenshots
- `next` - Framework

**Database:**
- `psql` - Postgres client
- `pg_dump` - Backup utility

### Skills
Workers must invoke and follow these skills:
- **mission-worker-base** - Always invoked first for setup (reads mission.md, AGENTS.md, runs init, baseline tests)
- **Specialized worker skills** - Feature-specific skills (financial-accuracy-worker, frontend-worker, etc.)

### Dependencies

**Backend (Python):**
- Use existing packages in `pyproject.toml`
- No new paid services
- Free data sources only: World Bank, Alpha Vantage, Tiingo, Quandl, Google Trends, NewsAPI, Reddit API

**Frontend (TypeScript):**
- Use existing packages in `package.json`
- shadcn/ui components (already installed)
- TanStack Table for professional tables
- No new paid services

**External Services:**
- SEC EDGAR API (free)
- Yahoo Finance (free)
- Finnhub (free tier)
- FRED (free)
- ECB (free)
- GDELT (free)

### Other Rules

**Language:**
- All user-facing text in Spanish
- Code comments in English
- Error messages in Spanish with error codes

**Testing:**
- Every bug fix requires failing test first
- UI changes require before/after screenshots (375px + 1280px)
- Financial calculations require manual verification
- All gates must pass before completion

**Security:**
- Never commit secrets
- Use environment variables
- Follow OWASP Top 10 guidelines

**Quality:**
- No file >1500 lines (refactor if needed)
- Coverage: backend >=85%, frontend >=80%, financial >=95%
- No generic error messages ("Something went wrong")
- All empty states have actionable CTAs

**Budget:**
- EUR 0 except LLM API key
- No paid services
- Free data sources only

---

## Testing & Validation Guidance

### For Validators

**Manual Testing Requirements:**
1. **Financial Accuracy:** Manually verify tax calculations, FIFO lot matching, DCA signal consistency across all surfaces
2. **Thesis Quality:** Generate thesis for META, verify comprehensiveness (>10 pages, data tables, charts, full analysis)
3. **Professional Design:** Visual comparison to Bloomberg Terminal/TradingView - does it match that quality?
4. **Navigation Flows:** Complete investment research journey without hitting dead ends

**Screenshot Requirements:**
- Use Playwright for consistency
- Capture at 375px (iPhone) and 1280px (desktop)
- Include both Chromium and WebKit browsers
- Show full page context, not just component

**Performance Validation:**
- Portfolio page with 100 holdings must load <1s
- Measure with browser DevTools Performance tab
- Document metrics: FCP, LCP, CLS, TTI

**Security Validation:**
- Run security scans: `ruff check .`, `npm audit`
- Verify no hardcoded credentials: `rg "password.*=.*['"]" --type py`
- Test CSRF protection: attempt POST without token
- Verify rate limiting: exceed limits and confirm 429 response

**Coverage Validation:**
- Run `pytest --cov=app --cov-report=term-missing`
- Verify backend >=85%, financial files >=95%
- No uncovered critical paths (auth, payments, data integrity)

**Credentials for Testing:**
- LLM API key: From `.env` (user-provided)
- Database: Local Postgres on localhost:5432
- Test data: Use fixtures in `tests/fixtures/`

**Skip Manual QA If:**
- Feature is purely backend logic with comprehensive test coverage
- Feature is infrastructure (migrations, indexes) with verification queries
- No user-facing changes

Workers: If you cannot complete validation within boundaries or without required credentials, return to orchestrator with clear blocker description.
