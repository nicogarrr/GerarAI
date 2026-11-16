# Bound Joyas fundamentals to genuinely price-eligible companies

Base 8a13f11432fdd8394b899eb98cfa3aac3cbfd824. No deploy or database changes.

Historical production evidence (15 Nov 23:50 CET) shows latest_metrics SQL5.933s,
net-income facts2.284s, revenue facts1.804s and FCF/shares facts2.607s, out of
13.7s HTTP. This patch addresses unnecessary scope of the last query only.
The three facts projections in #5710 are already in main, but were not served
by production8dfde929. Do not count that earlier work again as this patch.

Find_gems now applies currency and its existing7day price eligibility before
facts. The company predicate is inside the SQL window, not Python trimming.
Empty eligible sets skip facts, insiders and13F. Valid companies still use the
same fiscal cutoff, revisions, FCF/shares same-FY policy and score. The optional
helper filter defaults to None for compatibility with other internal readers.
No metric-version tie policy, indexes, caches or timeouts change.

Measured first local A/B: SQLite,500companies,40000facts,10revisions per metric
per FY,1candidate with fresh price,20warm samples each. Exact dataclass fields
match. Unscoped facts p50/p95 31.693/32.299ms; scoped1.857/2.055ms. Samples in
`evidence/joyas-eligible-work-20261116.json`. SQLite is not PostgreSQL or HTTP.

Reproduce from data-engine (Python3.12):

    PYTHONPATH=.:tests python scripts/benchmark_joyas_eligible_work.py
    PYTHONPATH=.:tests python -m pytest tests/test_propicks_gems_eligible_work.py tests/test_propicks_gems.py tests/test_propicks_fact_projection_parity.py tests/test_propicks_fact_work_budget.py tests/test_propicks_gems_price_bound.py tests/test_propicks_funnel.py -q -o addopts='' --cov=app.services.propicks_gems_service --cov-branch

34tests pass. Full gems module149/155lines96.13%,56/64branches87.5%. Added
product lines9/9, no new branch uncovered. Red first: absence of early exit and
missing company_id SQL predicate failed both new tests. Exact output parity,
empty optional filter and stale/USD exclusions covered. Ruff/diff clean.
Full propicks suite not run: current isolated environment lacks qdrant_client
for collection of two HTTP-route files. CI and independent auditor required.

No claim this solves historical13.7s, latest_metrics5.933s or production503.
Current Audit5 serial HTTP samples were fast/empty, not a reproduction of the
historical slow SQL and not evidence for Nico's tenant. A one-pass metric-window
candidate was rejected because local latency worsened34.747→58.395ms.
