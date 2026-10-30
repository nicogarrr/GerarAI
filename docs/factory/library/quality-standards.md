# Quality Standards

Coding standards, patterns, and anti-patterns for this mission.

---

## Code Quality Rules

### File Size Limits
- **Maximum:** 1500 lines per file
- **Action:** Refactor if exceeded
- **Current violations:** 
  - `financial_ingestion_service.py`: 3123 lines
  - `chat_service.py`: 2954 lines
  - `entities.py`: 2572 lines

### Function Complexity
- **Maximum:** 100 lines per function
- **Current violations:** 110 functions over limit
- **Action:** Extract sub-functions

### Nesting Depth
- **Maximum:** 4 levels
- **Current violations:** 1,049 deeply nested blocks
- **Action:** Early returns, guard clauses, extraction

## Testing Standards

### Coverage Targets
- **Backend overall:** >=85%
- **Frontend overall:** >=80%
- **Financial calculations:** >=95%
- **Critical paths:** 100% (auth, payments, data integrity)

### Test Quality
- **Bug fixes:** Failing test first, then fix, then passing test
- **Financial tests:** Property-based testing with Hypothesis
- **UI tests:** Screenshots at 375px + 1280px (Chromium + WebKit)

## Content Quality

### Error Messages
- ❌ **Bad:** "Something went wrong"
- ✅ **Good:** "Failed to calculate DCF: missing revenue data (ERR-VAL-001)"

### Empty States
- ❌ **Bad:** "No stocks in watchlist"
- ✅ **Good:** "No stocks in watchlist. [Search for stocks to add]"

### Form Validation
- ❌ **Bad:** "Invalid input"
- ✅ **Good:** "Email must be in format: user@example.com"

## Spanish Language

All user-facing text must be in Spanish:
- UI labels and buttons
- Error messages
- Empty states
- Notifications
- Email content

Code and technical docs remain in English.
