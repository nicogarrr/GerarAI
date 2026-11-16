"""Contrato unificado de ProPicks (propicks-unified-v1): 15 invariantes.

Solo contrato puro (sin red, sin BD, sin LLM): constructores deterministas a
partir de entradas ya normalizadas. Ninguna cifra se recalcula aquí.
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from pydantic import ValidationError

from app.schemas.propicks_unified import SCHEMA_VERSION, Datum, UnifiedPick, UnifiedResult
from app.services.propicks_unified import (
    PickInput,
    TenantScopedCache,
    build_pick,
    build_result,
    classify_fetch,
    parse_unified_json,
    tenant_cache_key,
)

RUN_DAY = date(2026, 11, 16)


def pick(**kw) -> PickInput:
    base = dict(
        ticker="AAA", name="Alpha Inc", exchange="NYSE", currency="USD",
        instrument_id="inst:aaa-nyse", quality_passed=True, quality_score=71.234,
        quality_policy_version="quality-v1",
        quality_score_policy_version="propicks-funnel-v1", price=10.0, price_as_of=date(2026, 11, 14),
        price_to_book=0.9, fcf_yield=0.08, margin_of_safety=0.2,
        valuation_as_of=date(2026, 11, 14), listing_status="active",
    )
    base.update(kw)
    return PickInput(**base)


def build(**kw) -> UnifiedPick:
    return build_pick(pick(**kw), run_id=7, as_of=RUN_DAY)


def test_01_score_exact_and_schema_version() -> None:
    p = build()
    assert p.quality.score.value == 71.234  # sin redondear ni recalcular
    assert p.quality.score.status == "ok"
    assert p.quality.policyVersion == "quality-v1"
    res = build_result([pick()], run_id=7, as_of=RUN_DAY, universe=10)
    assert res.schemaVersion == SCHEMA_VERSION == "propicks-unified-v1"


def test_02_missing_is_null_not_zero_or_fifty() -> None:
    p = build(quality_score=None, price=None, price_to_book=None, margin_of_safety=None)
    assert p.quality.score.value is None and p.quality.score.status == "missing"
    assert p.valuation.price.value is None and p.valuation.price.status == "missing"
    assert p.valuation.marginOfSafety.value is None
    with pytest.raises(ValidationError):
        Datum(value=0, status="missing", unit=None, asOf=None, sourceAsOf=None,
              formulaVersion=None, reasonCodes=[])


def test_03_extreme_or_disputed_valuation_goes_to_review_not_ranking() -> None:
    p = build(extreme_fields=("priceToBook",))
    assert p.valuation.priceToBook.status == "disputed"
    assert p.eligibility.state == "review_data"
    d = build(disputed_fields=("fcfYield",))
    assert d.valuation.fcfYield.status == "disputed"
    assert d.eligibility.state == "review_data"
    res = build_result([pick(extreme_fields=("priceToBook",))], run_id=7, as_of=RUN_DAY, universe=1)
    assert res.coverage.rankable == 0


def test_04_dca_4x_confirmed_does_not_change_unknown_quality() -> None:
    p = build(quality_passed=None, quality_score=None, dca_status="ok", dca_level=4,
              dca_period_state="confirmed", dca_confirmed_level=4,
              dca_price_verified=True, dca_formula_version="nico-v2")
    assert p.quality.passed is None
    assert p.eligibility.state != "investigate"
    f = build(quality_passed=False, dca_status="ok", dca_level=4,
              dca_period_state="confirmed", dca_confirmed_level=4, dca_formula_version="nico-v2")
    assert f.quality.passed is False and f.eligibility.state == "excluded"


def test_05_confirmed_and_forming_are_separate() -> None:
    p = build(dca_status="ok", dca_level=3, dca_period_state="forming", dca_confirmed_level=4,
              dca_price_verified=False, dca_scan_as_of=date(2026, 11, 14),
              dca_formula_version="nico-v2")
    assert p.dca.level.value == 3 and p.dca.periodState == "forming"
    assert p.dca.confirmedLevel.value == 4
    assert p.dca.priceVerified is False


def test_06_old_price_with_new_envelope_stays_stale() -> None:
    p = build(price_as_of=date(2026, 10, 1), valuation_as_of=date(2026, 10, 1))
    assert p.valuation.price.status == "stale"
    assert p.valuation.price.value == 10.0  # se conserva, marcado
    assert p.valuation.price.asOf == "2026-10-01"
    assert p.asOf == "2026-11-16"  # fecha de la respuesta, distinta de la del dato
    assert p.eligibility.state != "investigate"


def test_07_dca_failure_keeps_quality_and_valuation_and_marks_partial() -> None:
    res = build_result(
        [pick()], run_id=7, as_of=RUN_DAY, universe=1,
        blocks={"dca": classify_fetch(exc=TimeoutError("dca"))},
    )
    assert res.blocks["dca"].status == "error" and res.blocks["dca"].error.kind == "timeout"
    assert res.blocks["quality"].status == "ok" and res.blocks["valuation"].status == "ok"
    assert res.status == "partial"
    assert res.items[0].quality.passed is True
    assert res.items[0].valuation.price.value == 10.0
    assert res.items[0].dca.status == "missing"


def test_08_empty_200_vs_timeout_error() -> None:
    empty = classify_fetch(status_code=200, payload=[])
    assert empty.status == "empty" and empty.error is None
    assert classify_fetch(exc=TimeoutError()).error.kind == "timeout"
    assert classify_fetch(status_code=401).error.kind == "unauthenticated"
    assert classify_fetch(status_code=403).error.kind == "forbidden"
    r = classify_fetch(status_code=429, retry_after=30)
    assert r.error.kind == "rate_limited" and r.error.retryAfterSeconds == 30
    assert classify_fetch(status_code=503).error.kind == "unavailable"
    assert classify_fetch(status_code=200, payload="no-json-list").error.kind == "invalid_response"


def test_09_delisted_excluded_even_with_low_pb() -> None:
    p = build(ticker="ELME", listing_status="delisted", price_to_book=0.3)
    assert p.listing.status == "delisted" and p.eligibility.state == "excluded"
    assert "delisted" in p.eligibility.reasonCodes


def test_10_same_ticker_different_instrument_not_merged() -> None:
    a = pick(instrument_id="inst:x-nyse", exchange="NYSE")
    b = pick(instrument_id="inst:x-lse", exchange="LSE", currency="GBP")
    res = build_result([a, b], run_id=7, as_of=RUN_DAY, universe=2)
    assert {i.instrumentId for i in res.items} == {"inst:x-nyse", "inst:x-lse"}


def test_11_multiple_share_classes_survive_without_name_heuristic() -> None:
    a = pick(ticker="BRK.A", name="Berkshire Hathaway", instrument_id="inst:brka")
    b = pick(ticker="BRK.B", name="Berkshire Hathaway", instrument_id="inst:brkb")
    res = build_result([a, b], run_id=7, as_of=RUN_DAY, universe=2)
    assert len(res.items) == 2
    c = build_result([a, a], run_id=7, as_of=RUN_DAY, universe=2)  # mismo instrumento
    assert len(c.items) == 1


def test_12_tenant_isolation_in_cache_key_and_store() -> None:
    assert tenant_cache_key("A", "propicks", "v1") != tenant_cache_key("B", "propicks", "v1")
    for bad in (None, "", "  "):
        with pytest.raises(ValueError):
            tenant_cache_key(bad, "propicks")
    cache = TenantScopedCache()
    cache.set("A", "propicks", {"x": 1})
    assert cache.get("A", "propicks") == {"x": 1}
    assert cache.get("B", "propicks") is None


@pytest.mark.parametrize("raw", [
    "not json", '{"a": NaN}', '{"a": Infinity}', '{"a": -Infinity}',
])
def test_13a_invalid_json_and_nonfinite_rejected(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_unified_json(raw)


def test_13b_score_over_100_rejected() -> None:
    res = build_result([pick()], run_id=7, as_of=RUN_DAY, universe=1)
    data = json.loads(res.model_dump_json())
    data["items"][0]["quality"]["score"]["value"] = 100.5
    with pytest.raises(ValueError):
        parse_unified_json(json.dumps(data))
    data["items"][0]["quality"]["score"]["value"] = 71.234
    assert parse_unified_json(json.dumps(data)).items[0].quality.score.value == 71.234


def test_14_unknown_universe_is_null() -> None:
    res = build_result([pick()], run_id=7, as_of=RUN_DAY, universe=None)
    assert res.coverage.universe is None
    assert res.coverage.evaluated == 1


def test_15_history_and_simulations_outside_contract() -> None:
    p = build()
    data = json.loads(p.model_dump_json())
    for extra in ("backtest", "simulation", "history"):
        with pytest.raises(ValidationError):
            UnifiedPick.model_validate({**data, extra: []})
    with pytest.raises(ValidationError):
        UnifiedResult.model_validate({"schemaVersion": "propicks-unified-v1", "extra": 1})


def test_provisional_identity_when_only_company_id() -> None:
    p = build(instrument_id=None, company_id=42)
    assert p.instrumentId == "company:42"
    assert p.listing.identityStatus == "unverified"
    with pytest.raises(ValueError):
        build(instrument_id=None, company_id=None)


def test_margin_of_safety_is_passthrough_never_computed() -> None:
    p = build(margin_of_safety=None, price=10.0)
    assert p.valuation.marginOfSafety.status == "missing"
    assert p.valuation.marginOfSafety.value is None


def test_stable_internal_id_is_not_verified_identity() -> None:
    p = build()  # instrument_id presente, sin identity_status
    assert p.listing.identityStatus == "unverified"
    assert p.eligibility.state == "investigate"
    assert "identity_unverified" in p.eligibility.reasonCodes


def test_verified_identity_requires_explicit_status_and_evidence() -> None:
    v = build(identity_status="ok", identity_evidence=("resolver:isin+mic",))
    assert v.listing.identityStatus == "ok"
    assert v.listing.identityEvidence == ["resolver:isin+mic"]
    assert "identity_unverified" not in v.eligibility.reasonCodes
    with pytest.raises(ValueError):  # 'ok' sin evidencia del resolver no vale
        build(identity_status="ok")


def test_disputed_identity_goes_to_review() -> None:
    p = build(identity_status="disputed", identity_evidence=("resolver:conflict",))
    assert p.eligibility.state == "review_data"
    assert "identity_disputed" in p.eligibility.reasonCodes


def test_unverified_identity_sorts_after_verified_same_score() -> None:
    a = pick(instrument_id="inst:a", ticker="AAA")
    b = pick(instrument_id="inst:b", ticker="BBB", identity_status="ok",
             identity_evidence=("resolver:isin+mic",))
    res = build_result([a, b], run_id=7, as_of=RUN_DAY, universe=2)
    assert [i.listing.ticker for i in res.items] == ["BBB", "AAA"]


def test_cancelled_instrument_excluded_even_with_null_legacy_delisted() -> None:
    p = build(ticker="ELME", listing_status="unknown", instrument_status="cancelled",
              price_to_book=0.3)
    assert p.listing.status == "unknown"  # NULL legacy no prueba activo ni baja
    assert p.listing.instrumentStatus == "cancelled"
    assert p.eligibility.state == "excluded"
    assert "instrument_cancelled" in p.eligibility.reasonCodes


def test_suspension_is_not_delisting_and_not_rankable() -> None:
    p = build(trading_status="suspended", listing_status="unknown")
    assert p.listing.tradingStatus == "suspended"
    assert p.listing.status != "delisted"
    assert p.eligibility.state == "review_data"
    assert "trading_suspended" in p.eligibility.reasonCodes
    assert "delisted" not in p.eligibility.reasonCodes
    res = build_result([pick(trading_status="suspended")], run_id=7, as_of=RUN_DAY, universe=1)
    assert res.coverage.rankable == 0


def test_identity_context_fields_pass_through() -> None:
    p = build(identity_reason_codes=("cusip_changed",), listing_id="listing:1",
              issuer_legal_status="liquidating")
    assert p.listing.listingId == "listing:1"
    assert p.listing.identityReasonCodes == ["cusip_changed"]
    assert p.listing.issuerLegalStatus == "liquidating"
    d = build()
    assert d.listing.tradingStatus == "unknown" and d.listing.instrumentStatus == "unknown"
    assert d.listing.issuerLegalStatus == "unknown"


def test_coverage_identity_verified_counts_only_resolver_verified() -> None:
    a = pick(instrument_id="inst:a", ticker="AAA")
    b = pick(instrument_id="inst:b", ticker="BBB", identity_status="ok",
             identity_evidence=("resolver:isin+mic",))
    c = pick(instrument_id=None, company_id=9, ticker="CCC")
    res = build_result([a, b, c], run_id=7, as_of=RUN_DAY, universe=3)
    assert res.coverage.evaluated == 3
    assert res.coverage.identityVerified == 1
    empty = build_result([], run_id=None, as_of=RUN_DAY, universe=None)
    assert empty.coverage.identityVerified == 0


def test_score_policy_is_separate_from_quality_overlay_policy() -> None:
    p = build()
    assert p.quality.scorePolicyVersion == "propicks-funnel-v1"
    assert p.quality.score.formulaVersion == "propicks-funnel-v1"
    assert p.quality.policyVersion == "quality-v1"  # overlay por fila, otro campo
    assert p.quality.score.value == 71.234


def test_score_without_score_policy_version_rejected() -> None:
    with pytest.raises(ValueError):
        build(quality_score_policy_version=None)
    nulo = build(quality_score=None, quality_score_policy_version=None)
    assert nulo.quality.score.status == "missing"


def test_stale_pb_with_fresh_price_makes_valuation_stale_and_not_investigable() -> None:
    p = build(price_as_of=date(2026, 11, 15), valuation_as_of=date(2026, 1, 15))
    assert p.valuation.price.status == "ok"
    assert p.valuation.priceToBook.status == "stale"
    assert p.valuation.status == "stale"
    assert p.eligibility.state == "review_data"
    assert "valuation_stale" in p.eligibility.reasonCodes
    res = build_result(
        [pick(price_as_of=date(2026, 11, 15), valuation_as_of=date(2026, 1, 15))],
        run_id=7, as_of=RUN_DAY, universe=1,
    )
    assert res.coverage.rankable == 0 and res.coverage.pendingReview == 1


def test_stale_fcf_or_margin_also_propagates() -> None:
    for field in ("fcf_yield", "margin_of_safety"):
        p = build(valuation_as_of=date(2026, 1, 15), **{field: 0.1})
        assert p.valuation.status == "stale"
        assert p.eligibility.state == "review_data"
    # un dato ausente no es obsoleto: no contamina el estado
    q = build(fcf_yield=None, margin_of_safety=None)
    assert q.valuation.status == "ok" and q.eligibility.state == "investigate"


def test_wire_datums_reject_nonfinite_and_missing_ok_value() -> None:
    for value in [float('nan'), float('inf'), float('-inf')]:
        with pytest.raises(ValidationError, match='finite'):
            Datum(value=value, status='ok')
    with pytest.raises(ValidationError, match='requires a value'):
        Datum(value=None, status='ok')


def test_wire_delisted_pick_cannot_claim_investigate() -> None:
    payload = build(listing_status='delisted').model_dump()
    payload['eligibility'] = {'state': 'investigate', 'reasonCodes': []}
    with pytest.raises(ValidationError, match='delisted listing must be excluded'):
        UnifiedPick.model_validate(payload)


from app.services.propicks_unified import make_datum  # noqa: E402


def test_datum_without_date_or_with_future_date_is_not_fresh() -> None:
    sin = make_datum(10.0, as_of=None, run_as_of=RUN_DAY, max_age_days=3)
    assert sin.status == "unverified" and "as_of_missing" in sin.reasonCodes
    fut = make_datum(10.0, as_of=date(2027, 1, 1), run_as_of=RUN_DAY, max_age_days=3)
    assert fut.status == "unverified" and "as_of_future" in fut.reasonCodes
    assert fut.value == 10.0  # se conserva marcado, no se inventa frescura
    hoy = make_datum(10.0, as_of=RUN_DAY, run_as_of=RUN_DAY, max_age_days=3)
    assert hoy.status == "ok"


def test_unverified_valuation_is_not_investigable() -> None:
    p = build(valuation_as_of=None)  # P/B sin fecha
    assert p.valuation.priceToBook.status == "unverified"
    assert p.valuation.status == "unverified"
    assert p.eligibility.state == "review_data"
    assert "valuation_unverified" in p.eligibility.reasonCodes
    q = build(price_as_of=date(2027, 1, 1))
    assert q.valuation.price.status == "unverified" and q.eligibility.state == "review_data"


def test_persisted_field_status_other_than_ok_is_not_ok() -> None:
    inv = build(field_statuses=(("priceToBook", "invalid"),))
    assert inv.valuation.priceToBook.status == "invalid"
    assert inv.valuation.priceToBook.value is None
    mis = build(field_statuses=(("priceToBook", "missing"),))
    assert mis.valuation.priceToBook.status == "missing" and mis.valuation.priceToBook.value is None
    unv = build(field_statuses=(("priceToBook", "lo_que_sea"),))
    assert unv.valuation.priceToBook.status == "unverified" and unv.valuation.priceToBook.value == 0.9
    for p in (inv, unv):
        assert p.eligibility.state == "review_data"
