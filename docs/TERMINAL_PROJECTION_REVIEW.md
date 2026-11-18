# Terminal document projection: review evidence

Patch: 0c89a154303d8fcfa5d283782bb2a2e20113bed2.
Original base: db79294ac4e93bb4f63be95372255386cd0ac6e2.

## Callers and tenant context

Repository-wide Python search finds one application caller:
`app/api/routes/companies.py:financial_terminal`, which depends on
`app.core.database.get_db`. All other callers are tests.

`get_db` rejects an absent principal in production or when research auth is
required. For an accepted principal it resolves an active Tenant and assigns
`db.info['tenant_id']` before yielding. The new route test locks that exact
FastAPI dependency, calls the real get_db generator with production guards,
and executes the real route and service with a real SQLite session.
It does not test signed-header authentication itself.

Behavior change: directly invoking build with a source document but without
session tenant context now raises RuntimeError in production/auth-required
mode at the document projection. The old document entity query could read
unscoped in such a direct call. This is intentional fail-closed behavior,
consistent with tenancy.py. It is not a guarantee about future callers;
new background callers must explicitly supply tenant context.

## Explicit-filter mutation

The added isolation test temporarily removes the global Session query
listener, restores it in finally, and verifies that the explicit Document
predicate alone suppresses a foreign source's title, URL and segment.
A separate mutation run removes ONLY `*tenant_filters(db, Document)` from
the production statement. That run must fail on the leaked title. Restoring
the original statement must make the same test pass. The ordinary original
isolation test still checks the normal loader-criteria configuration.

## PostgreSQL segment semantics

The integration test creates actual Document rows in a disposable PostgreSQL
schema, compares the service output to the prior hydrated JSON conversion,
and asserts the executed SQL uses `->`, not `->>`.
Cases: segment null, empty string, Europe, 0, 12, 1.5, nonempty list,
nonempty object, false, string 0, missing key and metadata null, plus empty
list, empty object and true. Every case uses the actual mapped JSON column.

Run with TERMINAL_TEST_POSTGRES_URL set to a disposable PostgreSQL database.
Without it these tests explicitly skip and do not establish Postgres parity.
The schema is removed in finally. No production database is involved.

Additional behavior change: non-object metadata such as a JSON list or JSON
string previously caused AttributeError in `(metadata_ or {}).get(...)`.
PostgreSQL `-> 'segment'` yields null and the new path reports consolidated.
The equivalence claim covers object/null metadata only, not malformed or
non-object metadata. SQLite handling of scalar JSON can differ from Postgres.

## Scope of the green test claim

The evidence covers the focused terminal suite, window/deduplication tests,
get_db dependency tests, financial-intelligence integration and these review
gates. It is not a claim that the complete 2,400+ test-file repository suite,
external services or production HTTP p95 have been validated.
