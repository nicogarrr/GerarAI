"""ProPicks funnel v1 (big-data stage): deterministic ranking of the whole
research universe from persisted metrics and facts.

Design (2026-09-25):
- Universe: every company in the tenant (US SEC + EUR ESEF).
- Hard gates: metric coverage, earnings consistency, leverage (when the
  metric exists), and a sector-aware quality gate (financials use ROE vs
  cost-of-equity proxy because ROIC is not meaningful for banks/insurers —
  same reason Greenblatt excludes them from the Magic Formula).
- Ranking: percentile-ranked composite of quality/growth components with
  declared weights; missing components are excluded and weights renormalized
  (declared in the per-company coverage map, never imputed).
- One entry per issuer: when several share classes of the same company pass
  the gates (GOOG/GOOGL), only the class with the highest average volume in
  market_prices (last 90 days) is ranked; the others fail with the gate
  ``clase_duplicada:<canonical ticker>`` (explicit class map plus a
  conservative name/exchange/ticker-root fallback).
- Valuation and momentum are NOT part of v1: they need price series
  (phase F2). Everything here is reproducible from the DB.

Methodology is documented in the frontend /metodologia page.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    CalculatedMetric,
    Company,
    FinancialFact,
    MarketPrice,
    ProPickCandidate,
    ProPickRun,
)

# --- Funnel constants (declared; tune only with an explicit decision) -------

# Quality metrics whose presence counts towards coverage (wacc excluded: it
# is the hurdle, not a quality signal).
COVERAGE_METRICS = (
    "roic",
    "cfroi_approx",
    "fcf_margin_5y",
    "owner_earnings_5y",
    "net_margin_5y",
    "roe_5y",
    "roa_5y",
    "capex_to_da_5y",
    "quality_moat_score_v2",
)
MIN_COVERAGE = 6  # of 9 coverage metrics

CONSISTENCY_YEARS = 5          # last N fiscal years with net_income facts
CONSISTENCY_MIN_POSITIVE = 4   # of those N years (Graham/Buffett stability)
CONSISTENCY_MIN_YEARS_DATA = 4  # fewer years -> not enough evidence

LEVERAGE_METRIC = "net_debt_to_ebitda"  # US coverage today; EUR declared missing
LEVERAGE_MAX = 3.0

MIN_GROWTH_YEARS = 3  # revenue CAGR needs at least this span of fiscal years

# Composite score weights (renormalized when a component is missing).
# Spreads dominate: long-run return tracks return on invested capital
# (Munger/Fundsmith) minus the cost of that capital.
SCORE_WEIGHTS: dict[str, float] = {
    "spread_roic_wacc": 0.25,
    "spread_cfroi_wacc": 0.15,
    "quality_moat_score_v2": 0.20,
    "roe_5y": 0.10,
    "fcf_margin_5y": 0.10,
    "owner_earnings_5y": 0.05,
    "revenue_cagr": 0.10,
    "fcf_conversion": 0.05,
}
# Components that do not apply to financials (ROIC/CFROI meaningless there).
FINANCIALS_EXCLUDED_COMPONENTS = ("spread_roic_wacc", "spread_cfroi_wacc")

FUNNEL_VERSION = "propicks-funnel-v1"

# One entry per company: several share classes of the same issuer (GOOG and
# GOOGL) must not take several slots of the ranking. Explicit map first; for
# anything not listed, classes are linked only when name AND exchange are
# identical and the tickers share a root of 3+ characters (so "FWONA"/"LLYVA",
# which carry the same name in the data, are never merged by accident).
SHARE_CLASS_GROUPS: tuple[frozenset[str], ...] = tuple(
    frozenset(group)
    for group in (
        ("GOOG", "GOOGL"),
        ("BRK.A", "BRK.B", "BRK-A", "BRK-B"),
        ("FOX", "FOXA"),
        ("NWS", "NWSA"),
        ("LEN", "LEN.B"),
        ("BF.A", "BF.B", "BF-A", "BF-B"),
        ("HEI", "HEI.A"),
        ("LBRDA", "LBRDK"),
        ("LBTYA", "LBTYB", "LBTYK"),
        ("FWONA", "FWONK"),
        ("LLYVA", "LLYVK"),
        ("Z", "ZG"),
        ("UA", "UAA"),
        ("DISCA", "DISCK"),
        ("CMCSA", "CMCSK"),
        ("MOG.A", "MOG.B"),
        ("RDS.A", "RDS.B"),
        ("PARA", "PARAA"),
        ("LSXMA", "LSXMK"),
        ("QRTEA", "QRTEB"),
    )
)
VOLUME_LOOKBACK_DAYS = 90


@dataclass
class FunnelResult:
    company_id: int
    passed: bool
    score: float | None
    failed_gates: list[str] = field(default_factory=list)
    metrics: dict[str, float | None] = field(default_factory=dict)
    coverage: dict[str, str] = field(default_factory=dict)  # ok | missing | approx
    components: dict[str, float | None] = field(default_factory=dict)


def _latest_metrics(db: Session) -> dict[tuple[int, str], float]:
    """Latest stored value per (company, metric) across the metrics we read."""
    wanted = set(COVERAGE_METRICS) | {"wacc", LEVERAGE_METRIC, "fcf_conversion"}
    latest_period = (
        select(
            CalculatedMetric.company_id.label("company_id"),
            CalculatedMetric.metric.label("metric"),
            func.max(CalculatedMetric.period).label("max_period"),
        )
        .where(CalculatedMetric.metric.in_(wanted))
        .group_by(CalculatedMetric.company_id, CalculatedMetric.metric)
        .execution_options(include_all_tenants=True)
        .subquery()
    )
    rows = db.execute(
        select(
            CalculatedMetric.company_id,
            CalculatedMetric.metric,
            CalculatedMetric.value,
        ).join(
            latest_period,
            (CalculatedMetric.company_id == latest_period.c.company_id)
            & (CalculatedMetric.metric == latest_period.c.metric)
            & (CalculatedMetric.period == latest_period.c.max_period),
        )
        .order_by(CalculatedMetric.tenant_id.desc().nulls_last())
        .execution_options(include_all_tenants=True)
    ).all()
    return {
        (cid, metric): float(value)
        for cid, metric, value in rows
        if value is not None
    }


def _earnings_consistency(db: Session) -> dict[int, tuple[int, int]]:
    """Positive-net-income years out of the last CONSISTENCY_YEARS fiscal years.

    Returns company_id -> (positive_years, years_with_data).
    """
    fy_rows = db.execute(
        select(
            FinancialFact.company_id,
            FinancialFact.fiscal_year,
            FinancialFact.value,
        )
        .where(FinancialFact.metric == "net_income")
        .where(FinancialFact.fiscal_quarter.in_(["FY", ""]))
        .where(FinancialFact.fiscal_year.isnot(None))
        .order_by(
            FinancialFact.company_id,
            FinancialFact.fiscal_year.desc(),
            FinancialFact.created_at.desc(),
        )
        .execution_options(include_all_tenants=True)
    ).all()
    by_company: dict[int, list[tuple[int, float]]] = {}
    seen: set[tuple[int, int]] = set()
    for cid, fy, value in fy_rows:
        if (cid, fy) in seen:  # keep newest-created row per fiscal year
            continue
        seen.add((cid, fy))
        by_company.setdefault(cid, []).append((fy, float(value)))
    out: dict[int, tuple[int, int]] = {}
    for cid, years in by_company.items():
        window = years[:CONSISTENCY_YEARS]
        positive = sum(1 for _, v in window if v > 0)
        out[cid] = (positive, len(window))
    return out


def _revenue_cagr(db: Session) -> dict[int, float]:
    """Revenue CAGR over the available FY span (needs >= MIN_GROWTH_YEARS)."""
    rows = db.execute(
        select(
            FinancialFact.company_id,
            FinancialFact.fiscal_year,
            FinancialFact.value,
        )
        .where(FinancialFact.metric == "revenue")
        .where(FinancialFact.fiscal_quarter.in_(["FY", ""]))
        .where(FinancialFact.fiscal_year.isnot(None))
        .order_by(
            FinancialFact.company_id,
            FinancialFact.fiscal_year.asc(),
            FinancialFact.created_at.desc(),
        )
        .execution_options(include_all_tenants=True)
    ).all()
    by_company: dict[int, list[tuple[int, float]]] = {}
    seen: set[tuple[int, int]] = set()
    for cid, fy, value in rows:
        if (cid, fy) in seen:
            continue
        seen.add((cid, fy))
        by_company.setdefault(cid, []).append((fy, float(value)))
    out: dict[int, float] = {}
    for cid, years in by_company.items():
        if len(years) < MIN_GROWTH_YEARS:
            continue
        first_fy, first_val = years[0]
        last_fy, last_val = years[-1]
        span = int(last_fy) - int(first_fy)
        if span < 1 or first_val <= 0 or last_val <= 0:
            continue
        out[cid] = (last_val / first_val) ** (1.0 / span) - 1.0
    return out


def _percentile_ranks(values: dict[int, float]) -> dict[int, float]:
    """Rank-based percentiles in [0, 1]; robust to outliers and skew."""
    if not values:
        return {}
    ordered = sorted(values.items(), key=lambda kv: kv[1])
    n = len(ordered)
    ranks: dict[int, float] = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and ordered[j + 1][1] == ordered[i][1]:
            j += 1
        mid = (i + j) / 2.0
        pct = mid / (n - 1) if n > 1 else 0.5
        for k in range(i, j + 1):
            ranks[ordered[k][0]] = pct
        i = j + 1
    return ranks


def _is_financial(company: Company) -> bool:
    return (company.sector or "").strip().lower() == "financials"


def _common_root(a: str, b: str) -> int:
    root = 0
    while root < min(len(a), len(b)) and a[root] == b[root]:
        root += 1
    return root


def _group_share_classes(companies: list[Company]) -> dict[int, str]:
    """company_id -> group key, only for companies that have a sibling class.

    Union-find over every link (explicit map and name fallback), so a chain
    like ABCDA-ABCDB-ABCDC is ONE component whatever the order of ``companies``.
    """
    parent: dict[int, int] = {c.id: c.id for c in companies}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[max(rx, ry)] = min(rx, ry)  # deterministic root: lowest id

    mapped: dict[int, list[int]] = {}
    by_name: dict[tuple[str, str], list[Company]] = {}
    for company in companies:
        index = next(
            (i for i, group in enumerate(SHARE_CLASS_GROUPS) if (company.ticker or "").upper() in group),
            None,
        )
        if index is not None:
            mapped.setdefault(index, []).append(company.id)
        name = (company.name or "").strip().lower()
        if name:
            by_name.setdefault((name, (company.exchange or "").strip().lower()), []).append(company)
    for ids in mapped.values():
        for other in ids[1:]:
            union(ids[0], other)
    for same in by_name.values():
        for i, first in enumerate(same):
            for other in same[i + 1 :]:
                if _common_root(first.ticker.upper(), other.ticker.upper()) >= 3:
                    union(first.id, other.id)
    components: dict[int, list[int]] = {}
    for company in companies:
        components.setdefault(find(company.id), []).append(company.id)
    return {
        cid: f"group:{root}"
        for root, ids in components.items()
        if len(ids) > 1
        for cid in ids
    }


def _average_volumes(db: Session, company_ids: list[int]) -> dict[int, float]:
    """Mean positive volume over the lookback window; missing volume is absent
    (N/D), never 0."""
    if not company_ids:
        return {}
    since = date.today() - timedelta(days=VOLUME_LOOKBACK_DAYS)
    rows = db.execute(
        select(MarketPrice.company_id, func.avg(MarketPrice.volume))
        .where(
            MarketPrice.company_id.in_(company_ids),
            MarketPrice.date >= since,
            MarketPrice.volume.is_not(None),
            MarketPrice.volume > 0,
        )
        .group_by(MarketPrice.company_id)
        .execution_options(include_all_tenants=True)
    ).all()
    return {int(cid): float(avg) for cid, avg in rows if avg is not None}


def apply_share_class_dedupe(
    db: Session, companies: list[Company], results: list[FunnelResult]
) -> dict[int, str]:
    """Keep ONE passing share class per issuer: the one with the highest average
    volume in market_prices (tie or no volume data: lowest company id).

    Only classes that passed every gate compete, so a class that fails its own
    gates never hides a sibling that qualifies. The others are marked
    passed=False with the gate ``clase_duplicada:<canonical ticker>``. Returns
    {dropped company_id: canonical ticker}.
    """
    groups = _group_share_classes(companies)
    if not groups:
        return {}
    by_id = {r.company_id: r for r in results}
    ticker_of = {c.id: c.ticker for c in companies}
    members: dict[str, list[int]] = {}
    for company_id, key in groups.items():
        result = by_id.get(company_id)
        if result is not None and result.passed:
            members.setdefault(key, []).append(company_id)
    volumes = _average_volumes(db, [cid for ids in members.values() for cid in ids])
    dropped: dict[int, str] = {}
    for ids in members.values():
        if len(ids) < 2:
            continue
        canonical = min(ids, key=lambda cid: (-volumes.get(cid, 0.0), cid))
        for company_id in ids:
            if company_id == canonical:
                continue
            result = by_id[company_id]
            result.passed = False
            result.failed_gates.append(f"clase_duplicada:{ticker_of[canonical]}")
            dropped[company_id] = ticker_of[canonical]
    return dropped


def run_funnel(db: Session, *, top_n: int = 20) -> tuple[list[FunnelResult], dict[str, Any]]:
    """Evaluate every company; return ranked results (best first) + run stats."""
    started = time.monotonic()
    companies = list(db.scalars(select(Company).order_by(Company.id)).all())
    metrics = _latest_metrics(db)
    consistency = _earnings_consistency(db)
    growth = _revenue_cagr(db)

    # Raw component values per company (None when not applicable/missing).
    raw: dict[int, dict[str, float | None]] = {}
    results: list[FunnelResult] = []
    for company in companies:
        cid = company.id
        get = lambda m: metrics.get((cid, m))  # noqa: E731
        financial = _is_financial(company)

        coverage: dict[str, str] = {}
        for m in COVERAGE_METRICS:
            coverage[m] = "ok" if get(m) is not None else "missing"
        coverage["wacc"] = "ok" if get("wacc") is not None else "missing"
        coverage[LEVERAGE_METRIC] = (
            "ok" if get(LEVERAGE_METRIC) is not None else "missing"
        )
        coverage["fcf_conversion"] = (
            "ok" if get("fcf_conversion") is not None else "missing"
        )

        present = sum(1 for m in COVERAGE_METRICS if coverage[m] == "ok")
        failed: list[str] = []
        if present < MIN_COVERAGE:
            failed.append(f"coverage:{present}/{len(COVERAGE_METRICS)}")

        positive, years_data = consistency.get(cid, (0, 0))
        if years_data < CONSISTENCY_MIN_YEARS_DATA:
            failed.append(f"consistency_data:{years_data}y")
            coverage["earnings_consistency"] = "missing"
        else:
            coverage["earnings_consistency"] = "ok"
            if positive < CONSISTENCY_MIN_POSITIVE:
                failed.append(f"consistency:{positive}/{years_data}")

        leverage = get(LEVERAGE_METRIC)
        if leverage is not None and leverage >= LEVERAGE_MAX:
            failed.append(f"leverage:{leverage:.2f}")

        wacc = get("wacc")
        roic = get("roic")
        cfroi = get("cfroi_approx")
        roe = get("roe_5y")
        if financial:
            # ROIC/CFROI are not meaningful for banks/insurers (Greenblatt
            # excludes financials for the same reason). Declared approximation:
            # the stored wacc doubles as cost-of-equity proxy for the gate.
            coverage["quality_gate"] = "approx:financials_roe_vs_coe_proxy"
            if roe is None or wacc is None:
                failed.append("quality_gate:missing")
            elif roe <= wacc:
                failed.append(f"quality_gate:roe {roe:.3f}<=coe {wacc:.3f}")
        else:
            coverage["quality_gate"] = "ok"
            if roic is None or cfroi is None or wacc is None:
                failed.append("quality_gate:missing")
            else:
                if roic <= wacc:
                    failed.append(f"roic:{roic:.3f}<=wacc:{wacc:.3f}")
                if cfroi <= wacc:
                    failed.append(f"cfroi:{cfroi:.3f}<=wacc:{wacc:.3f}")

        cagr = growth.get(cid)
        coverage["revenue_cagr"] = "ok" if cagr is not None else "missing"

        spread_roic = (roic - wacc) if (roic is not None and wacc is not None) else None
        spread_cfroi = (cfroi - wacc) if (cfroi is not None and wacc is not None) else None
        components: dict[str, float | None] = {
            "spread_roic_wacc": None if financial else spread_roic,
            "spread_cfroi_wacc": None if financial else spread_cfroi,
            "quality_moat_score_v2": get("quality_moat_score_v2"),
            "roe_5y": roe,
            "fcf_margin_5y": get("fcf_margin_5y"),
                    "momentum_12m": get("momentum_12m"),
            "owner_earnings_5y": get("owner_earnings_5y"),
            "revenue_cagr": cagr,
            "fcf_conversion": get("fcf_conversion"),
        }
        raw[cid] = components
        results.append(
            FunnelResult(
                company_id=cid,
                passed=not failed,
                score=None,
                failed_gates=failed,
                metrics={
                    "roic": roic,
                    "cfroi_approx": cfroi,
                    "wacc": wacc,
                    "roe_5y": roe,
                    "net_debt_to_ebitda": leverage,
                    "revenue_cagr": cagr,
                    "fcf_margin_5y": get("fcf_margin_5y"),
                    "quality_moat_score_v2": get("quality_moat_score_v2"),
                },
                coverage=coverage,
                components=components,
            )
        )

    # One entry per issuer (GOOG/GOOGL): dropped classes leave the ranking AND
    # the percentile universe, so they do not weigh twice.
    for dropped_id in apply_share_class_dedupe(db, companies, results):
        raw.pop(dropped_id, None)

    # Percentile-rank each component across the universe, then weighted sum
    # with renormalization over available components per company.
    pct: dict[str, dict[int, float]] = {
        name: _percentile_ranks(
            {cid: v for cid, comp in raw.items() if (v := comp.get(name)) is not None}
        )
        for name in SCORE_WEIGHTS
    }
    for result in results:
        if not result.passed:
            continue
        total_w = 0.0
        acc = 0.0
        for name, weight in SCORE_WEIGHTS.items():
            value = raw[result.company_id].get(name)
            if value is None:
                continue
            acc += weight * pct[name][result.company_id]
            total_w += weight
        result.score = round(100.0 * acc / total_w, 4) if total_w > 0 else None

    ranked = sorted(
        (r for r in results if r.passed and r.score is not None),
        key=lambda r: (-(r.score or 0.0), r.company_id),
    )
    for idx, r in enumerate(ranked[:top_n], start=1):
        r.metrics["rank"] = float(idx)

    stats = {
        "version": FUNNEL_VERSION,
        "universe_size": len(companies),
        "passed_count": len(ranked),
        "duration_ms": int((time.monotonic() - started) * 1000),
        "params": {
            "top_n": top_n,
            "min_coverage": MIN_COVERAGE,
            "consistency": f"{CONSISTENCY_MIN_POSITIVE}/{CONSISTENCY_YEARS}",
            "leverage_max": LEVERAGE_MAX,
            "weights": SCORE_WEIGHTS,
        },
    }
    return results, stats


# --- Persistence ------------------------------------------------------------

def execute_run(db: Session, *, top_n: int = 20) -> ProPickRun:
    """Run the funnel over the whole universe and persist run + candidates."""
    from datetime import UTC, datetime

    results, stats = run_funnel(db, top_n=top_n)
    run = ProPickRun(
        as_of=datetime.now(UTC),
        status="completed",
        funnel_version=stats["version"],
        universe_size=stats["universe_size"],
        passed_count=stats["passed_count"],
        top_n=top_n,
        duration_ms=stats["duration_ms"],
        params=stats["params"],
    )
    db.add(run)
    db.flush()
    ordered = sorted(
        (x for x in results if x.passed and x.score is not None),
        key=lambda x: (-(x.score or 0.0), x.company_id),
    )
    rank_of = {x.company_id: i + 1 for i, x in enumerate(ordered[:top_n])}
    for r in results:
        db.add(
            ProPickCandidate(
                run_id=run.id,
                company_id=r.company_id,
                passed=r.passed,
                rank=rank_of.get(r.company_id),
                score=r.score,
                failed_gates=r.failed_gates,
                metrics={k: v for k, v in r.metrics.items() if k != "rank"},
                coverage=r.coverage,
            )
        )
    db.commit()
    db.refresh(run)
    return run
