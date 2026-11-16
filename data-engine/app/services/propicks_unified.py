"""Constructores deterministas del contrato propicks-unified-v1.

Sin red, BD ni LLM. No recalcula cifras: recibe valores ya normalizados y solo
fija estado, procedencia y elegibilidad. Ausencia = null (nunca 0 ni 50).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.schemas.propicks_unified import (
    SCHEMA_VERSION,
    Block,
    BlockError,
    Coverage,
    Datum,
    Dca,
    Eligibility,
    Listing,
    Quality,
    ResultCoverage,
    Tracking,
    UnifiedPick,
    UnifiedResult,
    Valuation,
)

# Mismo criterio que propicks_dca_radar.evaluate_candidate (> 3 días naturales).
PRICE_MAX_AGE_DAYS = 3
# Mismo criterio que deep_value_service.MAX_METRIC_AGE_DAYS (métricas valuation-v1).
VALUATION_MAX_AGE_DAYS = 7
_BLOCKS = ("quality", "valuation", "dca", "tracking")


@dataclass(frozen=True)
class PickInput:
    ticker: str
    name: str | None = None
    exchange: str | None = None
    currency: str | None = None
    instrument_id: str | None = None
    # Un id interno estable NO es identidad verificada: solo el resolver la fija.
    identity_status: str = "unverified"
    identity_evidence: tuple[str, ...] = ()
    identity_reason_codes: tuple[str, ...] = ()
    listing_id: str | None = None
    issuer_legal_status: str = "unknown"
    instrument_status: str = "unknown"
    trading_status: str = "unknown"
    company_id: int | None = None
    issuer_id: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    listing_status: str = "unknown"
    quality_passed: bool | None = None
    quality_score: float | None = None
    quality_policy_version: str | None = None  # overlay quality-v1 (passed)
    quality_score_policy_version: str | None = None  # política del score (embudo)
    quality_present: int = 0
    quality_required: int = 0
    quality_total: int = 0
    quality_reasons: tuple[str, ...] = ()
    price: float | None = None
    price_as_of: date | None = None
    price_to_book: float | None = None
    fcf_yield: float | None = None
    margin_of_safety: float | None = None
    valuation_as_of: date | None = None
    valuation_formula_version: str | None = None
    disputed_fields: tuple[str, ...] = ()
    # Estado persistido de la fuente por campo (p. ej. priceToBook): solo 'ok' acredita el dato.
    field_statuses: tuple[tuple[str, str], ...] = ()
    extreme_fields: tuple[str, ...] = ()
    dca_status: str | None = None
    dca_level: int | None = None
    dca_period_state: str | None = None
    dca_confirmed_level: int | None = None
    dca_price_verified: bool | None = None
    dca_scan_as_of: date | None = None
    dca_formula_version: str | None = None
    held: bool | None = None
    watched: bool | None = None
    evidence_flags: tuple[str, ...] = field(default_factory=tuple)
    review_reasons: tuple[str, ...] = field(default_factory=tuple)


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def make_datum(
    value: float | int | None,
    *,
    unit: str | None = None,
    as_of: date | None = None,
    source_as_of: date | None = None,
    formula_version: str | None = None,
    reasons: tuple[str, ...] = (),
    run_as_of: date | None = None,
    max_age_days: int | None = None,
    disputed: bool = False,
    source_status: str | None = None,
) -> Datum:
    common = dict(
        unit=unit, asOf=_iso(as_of), sourceAsOf=_iso(source_as_of),
        formulaVersion=formula_version,
    )
    if value is None:
        return Datum(value=None, status="missing", reasonCodes=[*reasons], **common)
    if isinstance(value, float) and not math.isfinite(value):
        return Datum(value=None, status="invalid", reasonCodes=[*reasons, "non_finite"], **common)
    if disputed:
        return Datum(value=value, status="disputed", reasonCodes=[*reasons], **common)
    if source_status in ("invalid", "missing"):
        return Datum(value=None, status=source_status,  # type: ignore[arg-type]
                     reasonCodes=[*reasons, "source_" + source_status], **common)
    if source_status not in (None, "ok"):
        return Datum(value=value, status="unverified",
                     reasonCodes=[*reasons, "source_status_unverified"], **common)
    if run_as_of and max_age_days is not None:
        if as_of is None:  # sin fecha no hay frescura acreditada
            return Datum(value=value, status="unverified",
                         reasonCodes=[*reasons, "as_of_missing"], **common)
        if as_of > run_as_of:  # fecha futura tampoco
            return Datum(value=value, status="unverified",
                         reasonCodes=[*reasons, "as_of_future"], **common)
        if (run_as_of - as_of).days > max_age_days:
            return Datum(value=value, status="stale", reasonCodes=[*reasons, "stale"], **common)
    return Datum(value=value, status="ok", reasonCodes=[*reasons], **common)


def _valuation_status(items: list[Datum], price: Datum) -> str:
    statuses = {d.status for d in items}
    for bad in ("disputed", "invalid"):
        if bad in statuses:
            return bad
    for weak in ("stale", "unverified"):  # cualquier cifra obsoleta o sin acreditar (precio, P/B...)
        if weak in statuses:
            return weak
    if price.status == "missing":
        return "missing"
    return "ok"


def _eligibility(inp: PickInput, quality: Quality, valuation: Valuation, identity: str) -> Eligibility:
    if inp.listing_status == "delisted":
        return Eligibility(state="excluded", reasonCodes=["delisted"])
    if inp.instrument_status == "cancelled":
        return Eligibility(state="excluded", reasonCodes=["instrument_cancelled"])
    if quality.passed is False:
        return Eligibility(state="excluded", reasonCodes=["quality_failed", *quality.reasonCodes])
    reasons: list[str] = []
    if identity in ("disputed", "invalid"):
        reasons.append("identity_" + identity)
    if valuation.status in ("disputed", "invalid", "stale", "unverified"):
        reasons.append("valuation_" + valuation.status)
    if quality.score.status in ("disputed", "invalid", "stale", "unverified"):
        reasons.append("quality_score_" + quality.score.status)
    if inp.trading_status == "suspended":
        reasons.append("trading_suspended")
    if quality.passed is None:
        reasons.append("quality_unknown")
    if reasons:
        return Eligibility(state="review_data", reasonCodes=reasons)
    if valuation.status == "missing":
        return Eligibility(state="quality_waiting_price", reasonCodes=["price_missing"])
    codes = ["identity_unverified"] if identity == "unverified" else []
    return Eligibility(state="investigate", reasonCodes=codes)


def _enum(value: str, allowed: tuple[str, ...]) -> str:
    return value if value in allowed else "unknown"


def build_pick(inp: PickInput, *, run_id: int | None, as_of: date) -> UnifiedPick:
    if inp.instrument_id:
        instrument_id, identity = inp.instrument_id, inp.identity_status
        if identity == "ok" and not inp.identity_evidence:
            raise ValueError("verified identity requires resolver evidence")
    elif inp.company_id is not None:
        instrument_id, identity = f"company:{inp.company_id}", "unverified"
    else:
        raise ValueError("instrument_id or company_id required")

    def val(name: str, v: float | None, unit: str) -> Datum:
        flagged = name in inp.disputed_fields or name in inp.extreme_fields
        reasons = ("extreme_value",) if name in inp.extreme_fields else ()
        return make_datum(
            v, unit=unit, as_of=inp.valuation_as_of, formula_version=inp.valuation_formula_version,
            reasons=reasons, disputed=flagged, run_as_of=as_of,
            source_status=dict(inp.field_statuses).get(name),
            max_age_days=VALUATION_MAX_AGE_DAYS,
        )

    price = make_datum(
        inp.price, unit=inp.currency, as_of=inp.price_as_of, run_as_of=as_of,
        max_age_days=PRICE_MAX_AGE_DAYS, disputed="price" in inp.disputed_fields,
        source_status=dict(inp.field_statuses).get("price"),
    )
    fcf = val("fcfYield", inp.fcf_yield, "ratio")
    pb = val("priceToBook", inp.price_to_book, "ratio")
    mos = val("marginOfSafety", inp.margin_of_safety, "ratio")
    valuation = Valuation(
        status=_valuation_status([price, fcf, pb, mos], price),
        price=price, fcfYield=fcf, priceToBook=pb, marginOfSafety=mos,
    )
    quality = Quality(
        passed=inp.quality_passed,
        score=make_datum(inp.quality_score, unit="score", formula_version=inp.quality_score_policy_version),
        policyVersion=inp.quality_policy_version,
        scorePolicyVersion=inp.quality_score_policy_version,
        coverage=Coverage(
            present=inp.quality_present, required=inp.quality_required, total=inp.quality_total
        ),
        reasonCodes=list(inp.quality_reasons),
    )
    dca_known = inp.dca_status is not None
    dca_kw = dict(
        unit="level", as_of=inp.dca_scan_as_of, formula_version=inp.dca_formula_version,
    )
    dca_ok = inp.dca_status == "ok"
    dca = Dca(
        status="ok" if dca_ok else (inp.dca_status if dca_known else "missing"),  # type: ignore[arg-type]
        level=make_datum(inp.dca_level if dca_ok else None, **dca_kw),  # type: ignore[arg-type]
        periodState=inp.dca_period_state if dca_ok else None,  # type: ignore[arg-type]
        confirmedLevel=make_datum(inp.dca_confirmed_level if dca_ok else None, **dca_kw),  # type: ignore[arg-type]
        priceVerified=inp.dca_price_verified if dca_ok else None,
        scanAsOf=_iso(inp.dca_scan_as_of),
        formulaVersion=inp.dca_formula_version,
    )
    listing = Listing(
        ticker=inp.ticker, name=inp.name, exchange=inp.exchange, currency=inp.currency,
        validFrom=_iso(inp.valid_from), validTo=_iso(inp.valid_to),
        status=inp.listing_status if inp.listing_status in ("active", "delisted") else "unknown",  # type: ignore[arg-type]
        identityStatus=identity,  # type: ignore[arg-type]
        identityEvidence=list(inp.identity_evidence),
        identityReasonCodes=list(inp.identity_reason_codes),
        listingId=inp.listing_id,
        tradingStatus=_enum(inp.trading_status, ("trading", "suspended")),  # type: ignore[arg-type]
        instrumentStatus=_enum(inp.instrument_status, ("active", "cancelled")),  # type: ignore[arg-type]
        issuerLegalStatus=_enum(  # type: ignore[arg-type]
            inp.issuer_legal_status, ("active", "liquidating", "dissolved")
        ),
    )
    return UnifiedPick(
        instrumentId=instrument_id, issuerId=inp.issuer_id, listing=listing, quality=quality,
        valuation=valuation, dca=dca, evidenceFlags=list(inp.evidence_flags),
        reviewReasons=list(inp.review_reasons),
        tracking=Tracking(held=inp.held, watched=inp.watched),
        eligibility=_eligibility(inp, quality, valuation, identity),
        runId=run_id, asOf=as_of.isoformat(),
    )


def classify_fetch(
    *, status_code: int | None = None, payload: Any = None, exc: BaseException | None = None,
    retry_after: int | None = None, as_of: date | None = None, reference: str | None = None,
) -> Block:
    """Un 200 [] es «empty»; un fallo es «error» con causa, nunca «empty»."""
    stamp = _iso(as_of)

    def err(kind: str, retry: int | None = None) -> Block:
        return Block(
            status="error", asOf=stamp,
            error=BlockError(kind=kind, retryAfterSeconds=retry, reference=reference),  # type: ignore[arg-type]
        )

    if exc is not None:
        timeout = isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower()
        return err("timeout" if timeout else "unavailable")
    code = status_code if status_code is not None else 200
    if code == 401:
        return err("unauthenticated")
    if code == 403:
        return err("forbidden")
    if code == 429:
        return err("rate_limited", retry_after)
    if code >= 500 or code in (408, 504):
        return err("timeout" if code in (408, 504) else "unavailable")
    if code >= 400 or not isinstance(payload, list):
        return err("invalid_response")
    return Block(status="ok" if payload else "empty", asOf=stamp)


def _sort_key(p: UnifiedPick) -> tuple:
    order = {"investigate": 0, "quality_waiting_price": 1, "review_data": 2, "excluded": 3}
    score = p.quality.score.value
    return (order[p.eligibility.state], score is None, -(score or 0),
            p.listing.identityStatus != "ok", p.listing.ticker, p.instrumentId)


def build_result(
    inputs: list[PickInput], *, run_id: int | None, as_of: date, universe: int | None,
    blocks: dict[str, Block] | None = None,
) -> UnifiedResult:
    seen: dict[str, UnifiedPick] = {}
    for inp in inputs:  # la identidad es el instrumento, nunca ticker ni nombre
        built = build_pick(inp, run_id=run_id, as_of=as_of)
        seen.setdefault(built.instrumentId, built)
    items = sorted(seen.values(), key=_sort_key)
    stamp = as_of.isoformat()
    out_blocks = {b: Block(status="ok" if items else "empty", asOf=stamp) for b in _BLOCKS}
    for name, blk in (blocks or {}).items():
        out_blocks[name] = blk
    if out_blocks["dca"].status == "error":
        items = [
            i.model_copy(update={"dca": Dca(
                status="missing", level=make_datum(None, reasons=("block_error",)),
                confirmedLevel=make_datum(None, reasons=("block_error",)),
            )})
            for i in items
        ]
    statuses = {b.status for b in out_blocks.values()}
    if statuses == {"error"}:
        overall = "error"
    elif statuses == {"empty"}:
        overall = "empty"
    elif statuses <= {"ok", "empty"}:
        overall = "ok"
    else:
        overall = "partial"
    quality_ok = out_blocks["quality"].status != "error"
    coverage = ResultCoverage(
        universe=universe,
        evaluated=len(items),
        identityVerified=sum(1 for i in items if i.listing.identityStatus == "ok"),
        qualityPassed=sum(1 for i in items if i.quality.passed is True) if quality_ok else None,
        rankable=sum(1 for i in items if i.eligibility.state == "investigate") if quality_ok else None,
        pendingReview=sum(1 for i in items if i.eligibility.state == "review_data") if quality_ok else None,
    )
    return UnifiedResult(
        schemaVersion=SCHEMA_VERSION, status=overall, asOf=stamp, runId=run_id,  # type: ignore[arg-type]
        coverage=coverage, blocks=out_blocks, items=items,  # type: ignore[arg-type]
    )


def _reject_constant(name: str) -> Any:
    raise ValueError(f"non-finite JSON constant: {name}")


def parse_unified_json(raw: str | bytes) -> UnifiedResult:
    """JSON inválido, NaN/Infinity o contrato roto => ValueError."""
    data = json.loads(raw, parse_constant=_reject_constant)
    return UnifiedResult.model_validate(data)


def tenant_cache_key(tenant_id: str | None, *parts: str) -> str:
    """El tenant viene de la identidad firmada en servidor, nunca opcional."""
    if tenant_id is None or not str(tenant_id).strip():
        raise ValueError("tenant_id required for cache key")
    return "|".join(["propicks-unified-v1", str(tenant_id).strip(), *parts])


class TenantScopedCache:
    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    def set(self, tenant_id: str | None, key: str, value: Any) -> None:
        self._data[tenant_cache_key(tenant_id, key)] = value

    def get(self, tenant_id: str | None, key: str) -> Any | None:
        return self._data.get(tenant_cache_key(tenant_id, key))
