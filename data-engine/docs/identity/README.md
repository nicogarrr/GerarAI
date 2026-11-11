# Offline identity handoff

Run from `data-engine` with an explicit read-only export (not committed here):

```sh
PYTHONPATH=. .venv/bin/python scripts/identity_dry_run.py \
  --manifest docs/identity/europe-mexico-20261111.json \
  --snapshot /path/to/companies-readonly.json
```

The program reads those two files and prints JSON. It has no database, network,
broker or account client and deliberately has no apply option. Source metadata
is supplied, not authenticated by this script. Check the evidence before taking
any action. A complete row is for operator review, not authority to write it.
Listing currency and reporting currency are different fields; no financial facts
or prices are created here. Preserve quote subunits (GBX/GBp are pence, not GBP).
Provider ticker suffixes are not exchange trading symbols or legal jurisdictions.

The 2026-11-11 manifest has three complete review records (ERF.PA, WOSG.L,
MICC.AS). ERF currency evidence is historical primary evidence and must be checked
against the provider's actual returned quote unit before ingestion. GCC.MX is
BLOCKED: the full ISIN is known only from secondary sources in this investigation.
The BIVA annual PDF truncates its ISIN to MX01GC2M0 and the GLEIF ISIN query returns
no records. A valid check digit does not prove a security's identity. Obtain a
primary source containing the full ISIN before promoting this record.

## CGEO operational diagnosis, code only

The read-only export at 2026-11-11 10:58:40 UTC contains CGEO.L with
ISIN GB00BF4HYV08, quote unit GBX and a 2026-11-09 close in GBp, but zero facts
and zero documents. ERF.PA, WOSG.L, MICC.AS and GCC.MX are not in that export's
Company master. Public ESEF/IR availability is not evidence of an actual import.

In the inspected code:

- `app/api/routes/watchlist.py::upsert_watch_item` calls the seed enqueue only
  when `created` is true. Reposting an existing watchlist item is NOT a refresh.
- `fundamentals_seed_service.enqueue_fundamentals_seed` returns false without
  tenant/user context or if broker send fails. The latter logs the exception;
  the normal watchlist add is intentionally not rolled back.
- The worker `dramatiq_app.seed_company_fundamentals` returns `sin_company` if
  it cannot find Company. This cannot by itself explain the current CGEO row,
  which now exists, but can explain a seed racing an earlier missing identity.
- With Company present and no facts, `seed_company_fundamentals` attempts primary
  sources, then `refresh_full_from_yahoo` only when
  `NON_SEC_FUNDAMENTALS_FALLBACK_ENABLED` is enabled. That function explicitly
  routes reviewed CGEO.L to `refresh_from_yahoo` and its GEL metric whitelist.
- The first lane for a bare LSE/.L company without a local snapshot is currently
  SEC, but no CIK skips it and ESEF is still tried next. That ordering alone does
  NOT prevent Yahoo fallback. Neither does GBX versus GEL.

No runtime cause is proven without logs. The export omits the non-SEC flag and
actor attempt/error history. The pilot should inspect the worker's seed job for
CGEO.L, tenant context, enqueue errors and the effective non-SEC flag. Only then
choose a normal refresh. Do not infer that a successful watchlist add proves
seed delivery or financial completeness. Do not claim the fallback was executed
or disabled merely from the zero-fact export.
