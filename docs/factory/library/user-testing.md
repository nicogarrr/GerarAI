# User Testing

Testing surface information, required testing skills/tools, and resource cost classification.

**What belongs here:** Testing approaches, tools, surfaces to test, resource requirements, constraints discovered during testing.

---

## Testing Surfaces

### Desktop Web (1280px+)
- **Primary surface:** Investment research, portfolio management, analysis
- **Browsers:** Chrome, Safari, Firefox
- **Tools:** Playwright (agent-browser), manual testing
- **Resource cost:** LOW (automated tests fast)

### Mobile Web (375px)
- **Primary surface:** Monitoring alerts, quick portfolio check, news reading
- **Browsers:** iOS Safari, Chrome Android
- **Tools:** Playwright mobile emulation, manual device testing
- **Resource cost:** LOW (automated tests fast)
- **Constraints:** Touch targets must be >=44px, no horizontal scroll

### Terminal UI
- **Not applicable:** GerarAI is web-only

## Required Testing Tools

### agent-browser
- **When:** UI flows, navigation testing, visual validation
- **What:** Automated browser testing with Chromium/WebKit
- **Evidence:** Screenshots (375px + 1280px), console errors, network calls

### tuistory
- **When:** N/A (no terminal UI)

### curl
- **When:** API endpoint testing, CSRF verification, rate limiting
- **Evidence:** HTTP status codes, response bodies, headers

### ripgrep (rg)
- **When:** Security checks (hardcoded creds), dead code detection
- **Evidence:** Search results, match counts

### pytest
- **When:** Backend logic validation, coverage verification
- **Evidence:** Test output, coverage reports

### Execute
- **When:** Database queries, performance measurements, service health checks
- **Evidence:** Command output, timing data

## Resource Cost Classification

### LOW Cost (<5 minutes execution time)
- Security scans (hardcoded credentials, SQL injection patterns)
- Database integrity checks (FK cascades, indexes existence)
- Coverage reports
- Unit/integration tests
- Quick UI flows (login, navigation)

### MEDIUM Cost (5-15 minutes)
- Full E2E user journeys
- Performance benchmarks (load times, N+1 detection)
- Complete regression suites
- Visual screenshot comparisons (multiple resolutions)

### HIGH Cost (>15 minutes)
- Load testing with realistic data volumes
- Thesis generation end-to-end (LLM calls)
- Full data source integration testing
- Manual financial accuracy verification

## Testing Constraints

### Financial Accuracy
- **Cannot automate fully:** Requires manual verification with real data samples
- **Approach:** Automated tests for logic, manual spot-checks for accuracy
- **Who:** Domain expert (accountant/tax professional ideally)

### LLM/Thesis Quality
- **Cannot automate quality:** Thesis comprehensiveness is subjective
- **Approach:** Automated structure checks, manual content review
- **Constraint:** LLM API key required, costs EUR per generation

### External APIs
- **Rate limits:** Many free sources have daily limits (500 req/day)
- **Approach:** Mock for bulk testing, real calls for integration validation
- **Constraint:** Tests must not exhaust daily quotas

## Isolation Approach

### Database
- **Strategy:** Separate test database (APP_ENV=test)
- **Isolation:** Transaction rollback after each test
- **Cleanup:** Automated via pytest fixtures

### External APIs
- **Strategy:** VCR.py for recording/replaying HTTP interactions
- **Isolation:** Per-test cassettes
- **Constraint:** First run requires real API access

### LLM Calls
- **Strategy:** Mock responses for unit tests, real calls for integration
- **Isolation:** Separate LLM test tenant
- **Cost:** Integration tests budget EUR X per run (track spending)
