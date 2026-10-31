"""Pure own-formula radar, separated from tenant watchlist alerts.

No downloads, persistence, LLM, notifications or look-ahead. Public market
observations must be settled and comparable before a zone can be displayed.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from app.services.dca_signal_engine import DailyBar, evaluate_series

UNIVERSE_TARGET = 1000
PAGE_SIZE = 20


@dataclass(frozen=True)
class RadarPrice:
    day: date
    close: float
    adjusted_close: float | None
    currency: str | None
    source: str
    volume: float | None = None


def evaluate_candidate(
    rows: list[RadarPrice], *, as_of: date, settled_through: date,
    expected_currency: str, reference_close: float | None = None,
    reference_date: date | None = None, tolerance: float = 0.02,
) -> dict:
    """Use only explicitly settled, adjusted series; surface invalidity reasons.

    Independent same-session reference is optional for diagnostic zones but
    required to label a candidate price-verified. No provisional4X is clear.
    """
    if settled_through > as_of:
        return {"status": "invalid", "reason": "future_session"}
    usable = sorted((r for r in rows if r.day <= settled_through), key=lambda r: r.day)
    if not usable:
        return {"status": "invalid", "reason": "no_settled_prices"}
    if (as_of - usable[-1].day).days > 3:
        return {"status": "invalid", "reason": "stale"}
    if len({r.day for r in usable}) != len(usable):
        return {"status": "invalid", "reason": "duplicate_session"}
    if any(r.currency != expected_currency for r in usable):
        return {"status": "invalid", "reason": "currency_mismatch"}
    if any(not r.source or not math.isfinite(r.close) or r.close <= 0
           or r.adjusted_close is None or not math.isfinite(r.adjusted_close)
           or r.adjusted_close <= 0 for r in usable):
        return {"status": "invalid", "reason": "unverified_adjusted_series"}
    verified = (reference_date == usable[-1].day and reference_close is not None
                and math.isfinite(reference_close) and reference_close > 0)
    if verified and reference_close is not None and abs(usable[-1].close / reference_close - 1) > tolerance:
        return {"status": "invalid", "reason": "conflicting_same_session_price"}
    bars = [DailyBar(r.day, float(r.adjusted_close)) for r in usable if r.adjusted_close is not None]
    series = evaluate_series(bars, today=as_of)
    if not series:
        return {"status": "invalid", "reason": "insufficient_history"}
    confirmed = [v for v in series if v.status == "confirmed"]
    return {"status": "ok", "formula_version": "nico-v1", "price_verified": bool(verified),
            "price_date": usable[-1].day.isoformat(), "source": usable[-1].source,
            "current": series[-1].as_dict(),
            "confirmed": confirmed[-1].as_dict() if confirmed else None,
            # Separate context only: never feeds the nico-v1 level calculation.
            "daily_close_drawdown": 1 - bars[-1].close / max(
                r.adjusted_close for r in usable if r.adjusted_close is not None),
            "drawdown_basis": "maximum available adjusted daily close, not intraday high",
            "clear_price_signal": bool(verified and confirmed and confirmed[-1].level == 4 and series[-1].level == 4)}


def quality_checks(*, sector: str, funnel_passed: bool,
                   leverage: float | None, fcf_current: float | None,
                   fcf_previous: float | None, periods_comparable: bool,
                   fundamentals_age_days: int | None,
                   median_dollar_volume: float | None, volume_sessions: int,
                   market_cap_usd: float | None) -> dict:
    """Explicit conservative nonfinancial screen; missing inputs never pass.

    These are our screening thresholds, not a promise of investment return.
    Financials and REITs need a separate model, not imputed FCF criteria.
    """
    reasons = []
    if any(token in sector.casefold() for token in ('financial', 'bank', 'insurance', 'reit')):
        reasons.append('sector_model_required')
    if not funnel_passed:
        reasons.append('quality_funnel_not_passed')
    if leverage is None or not math.isfinite(leverage) or leverage >= 3:
        reasons.append('leverage_missing_or_high')
    if fundamentals_age_days is None or not 0 <= fundamentals_age_days <= 150:
        reasons.append('fundamentals_stale_or_missing')
    if not periods_comparable:
        reasons.append('fcf_periods_not_comparable')
    if (fcf_current is None or fcf_previous is None or not math.isfinite(fcf_current)
            or not math.isfinite(fcf_previous) or fcf_current <= 0 or fcf_previous <= 0
            or fcf_current <= fcf_previous):
        reasons.append('fcf_not_positive_and_growing')
    if (volume_sessions < 20 or median_dollar_volume is None
            or not math.isfinite(median_dollar_volume) or median_dollar_volume < 5_000_000):
        reasons.append('liquidity_missing_or_low')
    if market_cap_usd is None or not math.isfinite(market_cap_usd) or market_cap_usd < 1_000_000_000:
        reasons.append('market_cap_missing_or_low')
    return {'passed': not reasons, 'reasons': reasons,
            'policy': 'quality-v1: leverage<3x, comparable positive growingFCF, facts<=150d, 20sessions dollarvolume>=5MUSD, cap>=1BUSD'}


def page_candidates(candidates: list[dict], *, page: int = 1, level: int | None = None,
                    outside_tracked: set[str] | None = None) -> dict:
    """Deterministic20-row pages; tenant tracked symbols supplied by caller."""
    selected = [row for row in candidates if (level is None or row.get('level') == level)
                and (outside_tracked is None or row['ticker'] not in outside_tracked)]
    selected.sort(key=lambda r: (-int(r.get('level') or 0), str(r['ticker'])))
    page = max(1, page)
    return {'page': page, 'page_size': PAGE_SIZE, 'total': len(selected),
            'items': selected[(page - 1) * PAGE_SIZE:page * PAGE_SIZE],
            'has_more': page * PAGE_SIZE < len(selected)}


def explain_candidate(price: dict, quality: dict) -> dict:
    """Own transparent verdict; never equate a price zone with business quality."""
    if price.get('status') != 'ok':
        return {'clear_opportunity': False,
                'reasons': [price.get('reason', 'price_unavailable')]}
    current = price['current']
    confirmed = price.get('confirmed')
    reasons = []
    if not price.get('price_verified'):
        reasons.append('independent_price_reference_missing')
    if not confirmed or confirmed.get('level') != 4:
        reasons.append('last_confirmed_month_not_4x')
    if current.get('level') != 4:
        reasons.append('latest_settled_close_no_longer_4x')
    if not quality.get('passed'):
        reasons.extend(quality.get('reasons') or ['quality_unavailable'])
    return {'clear_opportunity': not reasons, 'reasons': reasons,
            'formula': 'nico-v1', 'confirmed': confirmed, 'current': current,
            'notice': 'Decision support, not an automatic purchase or investment advice.'}


def signal_change(current: dict, previous_snapshot: dict | None) -> dict:
    """Changes need a prior persisted scan, not a forming-vs-confirmed comparison."""
    if not previous_snapshot:
        return {'status': 'history_pending', 'changed': None}
    if (current.get('status') != 'ok' or previous_snapshot.get('status') != 'ok'
            or current.get('formula_version') != previous_snapshot.get('formula_version')
            or not current.get('formula_version')):
        return {'status': 'not_comparable', 'changed': None}
    if current['price_date'] <= previous_snapshot['price_date']:
        return {'status': 'not_newer', 'changed': None}
    before = previous_snapshot['current']['level']
    after = current['current']['level']
    return {'status': 'compared', 'changed': before != after,
            'from_level': before, 'to_level': after,
            'since_price_date': previous_snapshot['price_date']}
