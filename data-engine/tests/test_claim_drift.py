"""Deriva claim -> hecho vivo: persistencia, deteccion, avisos y casos no comparables."""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import (
    Base,
    Claim,
    Company,
    FinancialFact,
    Tenant,
    ThesisVersion,
)
from app.services.claim_drift import (
    DRIFT_WARNING_ES,
    claim_drift,
    claim_drift_metadata,
    drift_notice_es,
    live_fact_map,
    thesis_claim_drift,
    thesis_drift,
)

USD = "USD"
PERIOD = "2025-12-31:FY"
KO_DEBT = {
    "claim_value": 42_120_000_000.0,
    "claim_metric": "total_debt",
    "claim_period": PERIOD,
    "claim_unit": USD,
}
KEY = ("total_debt", PERIOD, USD)


# ---- metadatos que se guardan al generar -------------------------------------
def test_metadata_keeps_value_metric_period_and_unit():
    payload = {"object": 31_850_000_000, "predicate": "net_debt", "period": PERIOD, "unit": USD}
    assert claim_drift_metadata(payload) == {
        "claim_value": 31_850_000_000.0,
        "claim_metric": "net_debt",
        "claim_period": PERIOD,
        "claim_unit": USD,
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"object": "31,85", "predicate": "net_debt", "period": "p", "unit": USD},
        {"object": True, "predicate": "net_debt", "period": "p", "unit": USD},
        {"object": float("nan"), "predicate": "net_debt", "period": "p", "unit": USD},
        {"object": float("inf"), "predicate": "net_debt", "period": "p", "unit": USD},
        {"object": None, "predicate": "net_debt", "period": "p", "unit": USD},
        {"object": 5, "predicate": "", "period": "p", "unit": USD},
        {"object": 5, "predicate": "net_debt", "period": None, "unit": USD},
        {"object": 5, "predicate": "net_debt", "period": "p", "unit": ""},
        {"object": 5, "predicate": "net_debt", "period": "p"},
        {},
    ],
)
def test_metadata_is_empty_without_a_comparable_key(payload):
    assert claim_drift_metadata(payload) == {}


# ---- deteccion pura ------------------------------------------------------------
def test_ko_stale_total_debt_is_flagged_not_hidden():
    [item] = claim_drift([KO_DEBT], {KEY: 45_436_000_000.0})
    assert item["stored_value"] == 42_120_000_000.0
    assert item["live_value"] == 45_436_000_000.0
    assert item["relative_difference"] == 0.073
    assert item["unit"] == USD
    assert item["warning"] == DRIFT_WARNING_ES == "cifra desactualizada, regenerar"


def test_tolerance_boundary_and_custom_tolerance():
    assert claim_drift([KO_DEBT], {KEY: 42_120_000_000.0 * 1.004}) == []
    live = {KEY: 42_120_000_000.0 * 1.02}
    assert len(claim_drift([KO_DEBT], live)) == 1
    assert claim_drift([KO_DEBT], live, tolerance=0.05) == []


def test_non_comparable_cases_never_claim_drift():
    assert claim_drift([KO_DEBT], {}) == []
    assert claim_drift([KO_DEBT], {("total_debt", "2024-12-31:FY", USD): 1.0}) == []
    assert claim_drift([KO_DEBT], {("total_debt", PERIOD, "EUR"): 1.0}) == []  # otra moneda
    assert claim_drift([KO_DEBT], {("net_debt", PERIOD, USD): 1.0}) == []  # otra metrica
    assert claim_drift([KO_DEBT], {KEY: None}) == []  # ambiguo
    assert claim_drift([KO_DEBT], {KEY: "45"}) == []
    no_unit = {k: v for k, v in KO_DEBT.items() if k != "claim_unit"}
    assert claim_drift([no_unit], {("total_debt", PERIOD, ""): 9.0}) == []
    no_value = {k: v for k, v in KO_DEBT.items() if k != "claim_value"}
    assert claim_drift([no_value], {KEY: 9.0}) == []


def test_zero_negative_and_duplicate_claims():
    zero = {"claim_value": 0.0, "claim_metric": "m", "claim_period": "p", "claim_unit": USD}
    assert claim_drift([zero], {("m", "p", USD): 0.0}) == []
    neg = {**zero, "claim_value": -100.0}
    assert len(claim_drift([neg], {("m", "p", USD): -150.0})) == 1
    assert claim_drift([neg], {("m", "p", USD): -100.0}) == []
    assert len(claim_drift([neg], {("m", "p", USD): 0.0})) == 1
    assert len(claim_drift([KO_DEBT, dict(KO_DEBT)], {KEY: 1.0})) == 1


def fact(metric="total_debt", value=45_436_000_000, period=PERIOD, unit=USD):
    return SimpleNamespace(metric=metric, value=None if value is None else Decimal(value), period=period, unit=unit)


def test_live_fact_map_marks_conflicting_values_as_ambiguous():
    live = live_fact_map(
        [fact(), fact(value=1), fact(metric="net_debt"), fact(value=None), fact(unit=""), fact(period="")]
    )
    assert live[KEY] is None
    assert live[("net_debt", PERIOD, USD)] == 45_436_000_000.0
    assert len(live) == 2
    assert live_fact_map([fact(), fact()])[KEY] == 45_436_000_000.0


def test_thesis_drift_only_uses_claims_of_that_thesis_and_skips_superseded():
    def claim(thesis_id, status="supported", meta=KO_DEBT):
        return SimpleNamespace(thesis_version_id=thesis_id, status=status, metadata_=meta)

    claims = [claim(1), claim(2), claim(1, "superseded"), claim(1, meta=None), claim(1, meta="x")]
    assert len(thesis_drift(claims, [fact()], 1)) == 1
    assert thesis_drift(claims, [fact()], 3) == []
    assert thesis_drift(claims, [fact()], None) == []
    assert thesis_drift([claim(1, "superseded")], [fact()], 1) == []


def test_notice_is_spanish_names_the_metric_and_keeps_the_warning():
    assert drift_notice_es([]) == ""
    one = drift_notice_es([{"metric": "total_debt"}], {"total_debt": "la deuda total"})
    assert one == (
        "Aviso: la deuda total de esta tesis ya no coincide con los datos actuales "
        "(cifra desactualizada, regenerar la tesis)."
    )
    many = drift_notice_es([{"metric": "net_debt"}, {"metric": "total_debt"}])
    assert "net_debt, total_debt" in many and "ya no coinciden" in many


# ---- lectura real de hechos vivos (BD) -------------------------------------------
@pytest.fixture
def saved():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        tenant = Tenant(external_id="t1", name="T1", status="active", metadata_={})
        other = Tenant(external_id="t2", name="T2", status="active", metadata_={})
        company = Company(ticker="KO", name="Coca-Cola", exchange="NYSE", currency="USD",
                          company_type="mature", valuation_model="dcf")
        rival = Company(ticker="PEP", name="Pepsi", exchange="NASDAQ", currency="USD",
                        company_type="mature", valuation_model="dcf")
        db.add_all([tenant, other, company, rival])
        db.flush()
        db.info["tenant_id"] = tenant.id
        thesis = ThesisVersion(tenant_id=tenant.id, company_id=company.id, version=1, status="draft",
                               rating="hold", thesis_markdown="memo", executive_summary="resumen",
                               created_at=datetime(2026, 10, 19, tzinfo=UTC))
        db.add(thesis)
        db.flush()
        db.add(Claim(tenant_id=tenant.id, company_id=company.id, thesis_version_id=thesis.id,
                     statement="Deuda total 42,12 mil M", status="supported", metadata_=dict(KO_DEBT)))
        db.add(Claim(tenant_id=tenant.id, company_id=company.id, thesis_version_id=thesis.id,
                     statement="sin cifra", metadata_={"generated_claim_id": "x"}))
        db.commit()
        yield db, company, rival, thesis, tenant, other
    engine.dispose()


def seed(db, *rows):
    # Se siembra con una sesion SIN ambito de tenant y se prueba el lector bajo su
    # ambito real: el aislamiento cross-tenant no se relaja.
    from sqlalchemy.orm import Session as SeedSession

    with SeedSession(db.get_bind()) as seed_session:
        seed_session.add_all(rows)
        seed_session.commit()


def add_fact(db, company, tenant, value, *, metric="total_debt", unit=USD, period=PERIOD, source_type="sec"):
    seed(db, FinancialFact(tenant_id=tenant.id, company_id=company.id, metric=metric,
                           value=Decimal(value), unit=unit, period=period, source_type=source_type))


def test_db_reader_flags_ko_stale_debt(saved):
    db, company, _rival, thesis, tenant, _other = saved
    add_fact(db, company, tenant, 45_436_000_000)
    [item] = thesis_claim_drift(db, thesis)
    assert item["live_value"] == 45_436_000_000.0 and item["stored_value"] == 42_120_000_000.0


def test_db_reader_does_not_assert_drift_without_comparable_live_fact(saved):
    db, company, rival, thesis, tenant, other = saved
    assert thesis_claim_drift(db, thesis) == []  # sin hechos vivos
    add_fact(db, rival, tenant, 1)  # otra empresa
    add_fact(db, company, other, 1)  # otro tenant
    add_fact(db, company, tenant, 1, unit="EUR")  # otra moneda
    add_fact(db, company, tenant, 1, period="2024-12-31:FY")  # otro periodo
    add_fact(db, company, tenant, 1, metric="net_debt")  # otra metrica
    assert thesis_claim_drift(db, thesis) == []
    add_fact(db, company, tenant, 42_120_000_000)  # misma cifra: sin deriva
    assert thesis_claim_drift(db, thesis) == []


def test_db_reader_without_claims_with_figures_is_empty(saved):
    db, company, _rival, thesis, tenant, _other = saved
    db.query(Claim).delete()
    db.commit()
    assert thesis_claim_drift(db, thesis) == []


# ---- persistencia real de claims -----------------------------------------------------
def test_persist_claims_stores_the_comparable_key(saved):
    from app.services.thesis_service import ThesisService

    db, company, _rival, thesis, tenant, _other = saved
    service = ThesisService.__new__(ThesisService)
    payloads = [
        {"claim_id": "KO:net_debt:2025-12-31:FY", "predicate": "net_debt", "object": 31_850_000_000.0,
         "unit": USD, "period": PERIOD, "claim": "Deuda neta 31,85 mil M", "source_id": None,
         "source_type": "sec", "confidence": 0.9},
        {"claim_id": "KO:valuation_model", "predicate": "valuation_model", "object": "dcf",
         "claim": "Modelo dcf", "source_id": None, "source_type": "sec"},
    ]
    service._persist_claims(db, company, thesis, payloads)
    db.commit()
    stored = {c.statement: c.metadata_ for c in db.query(Claim).filter(Claim.created_by == "thesis_generation")}
    debt = stored["Deuda neta 31,85 mil M"]
    assert debt["claim_value"] == 31_850_000_000.0
    assert (debt["claim_metric"], debt["claim_period"], debt["claim_unit"]) == ("net_debt", PERIOD, USD)
    assert debt["generated_claim_id"] == "KO:net_debt:2025-12-31:FY"
    assert "claim_value" not in stored["Modelo dcf"]  # no numerico: nada que comparar


# ---- aviso en el chat (flujo real: _key_facts + lector acotado + respuesta) ------------
NET_PERIOD = "2025-12-31:FY"


def add_net_debt_facts(db, company, tenant, *, fy2025, fy2026=None):
    rows = [FinancialFact(tenant_id=tenant.id, company_id=company.id, metric="net_debt",
                          value=Decimal(fy2025), unit=USD, period=NET_PERIOD, fiscal_year=2025,
                          source_type="sec")]
    if fy2026 is not None:
        rows.append(FinancialFact(tenant_id=tenant.id, company_id=company.id, metric="net_debt",
                                  value=Decimal(fy2026), unit=USD, period="2026-12-31:FY",
                                  fiscal_year=2026, source_type="sec"))
    seed(db, *rows)


def real_flow_answer(monkeypatch, db, company, thesis, withheld=None):
    from app.services import chat_service

    monkeypatch.setattr(chat_service, "_english", lambda: False)
    facts = chat_service.ChatService()._key_facts(db, company)
    items = chat_service._thesis_drift_items(db, thesis, withheld)
    claims = db.query(Claim).all()
    text = chat_service._natural_company_answer(
        company=company, facts=facts, thesis=thesis, news=[], missing_metrics=[], claims=claims,
        contradiction_claims=[], price_line=None, question="tesis KO", thesis_withheld=withheld,
        thesis_drift_items=items,
    )
    return facts, text


@pytest.fixture
def saved_net(saved):
    db, company, rival, thesis, tenant, other = saved
    db.query(Claim).delete()
    db.add(Claim(tenant_id=tenant.id, company_id=company.id, thesis_version_id=thesis.id,
                 statement="Deuda neta 31,85 mil M", status="supported",
                 metadata_={"claim_value": 31_850_000_000.0, "claim_metric": "net_debt",
                            "claim_period": NET_PERIOD, "claim_unit": USD}))
    db.commit()
    return saved


def test_chat_warns_for_fy2025_thesis_even_when_fy2026_fact_is_the_latest(saved_net, monkeypatch):
    db, company, _rival, thesis, tenant, _other = saved_net
    add_net_debt_facts(db, company, tenant, fy2025=35_166_000_000, fy2026=36_000_000_000)
    facts, text = real_flow_answer(monkeypatch, db, company, thesis)
    # El chat solo ve el ultimo hecho (FY2026): la comparacion no puede depender de el.
    assert [f.period for f in facts] == ["2026-12-31:FY"]
    assert "Tengo guardada la tesis v1" in text
    assert "Aviso:" in text and DRIFT_WARNING_ES in text
    assert "31,85" not in text.split("Aviso:")[1]


def test_chat_has_no_warning_when_the_fy2025_figure_still_matches(saved_net, monkeypatch):
    db, company, _rival, thesis, tenant, _other = saved_net
    add_net_debt_facts(db, company, tenant, fy2025=31_850_000_000, fy2026=36_000_000_000)
    _facts, text = real_flow_answer(monkeypatch, db, company, thesis)
    assert "Aviso:" not in text and "Tengo guardada la tesis v1" in text


def test_chat_does_not_compare_against_a_different_period_or_unit(saved_net, monkeypatch):
    db, company, _rival, thesis, tenant, _other = saved_net
    seed(
        db,
        FinancialFact(tenant_id=tenant.id, company_id=company.id, metric="net_debt",
                      value=Decimal(1), unit="EUR", period=NET_PERIOD, fiscal_year=2025, source_type="sec"),
        FinancialFact(tenant_id=tenant.id, company_id=company.id, metric="net_debt",
                      value=Decimal(1), unit=USD, period="2026-12-31:FY", fiscal_year=2026, source_type="sec"),
    )
    _facts, text = real_flow_answer(monkeypatch, db, company, thesis)
    assert "Aviso:" not in text


def test_chat_withheld_thesis_never_measures_or_quotes_drift(saved_net, monkeypatch):
    from app.services import chat_service

    db, company, _rival, thesis, tenant, _other = saved_net
    add_net_debt_facts(db, company, tenant, fy2025=35_166_000_000)
    monkeypatch.setattr(chat_service, "archived_thesis_notice", lambda t, r: "archivada")
    assert chat_service._thesis_drift_items(db, thesis, "modelo no publicable") == []
    assert chat_service._thesis_drift_items(db, None, None) == []
    _facts, text = real_flow_answer(monkeypatch, db, company, thesis, withheld="modelo no publicable")
    assert "Aviso:" not in text and "archivada" in text


def test_drift_read_failure_does_not_break_the_answer(saved_net, monkeypatch, caplog):
    from app.services import chat_service

    db, _company, _rival, thesis, _tenant, _other = saved_net

    def boom(*_a, **_k):
        raise RuntimeError("bd caida")

    monkeypatch.setattr(chat_service, "thesis_claim_drift", boom)
    with caplog.at_level("WARNING"):
        assert chat_service._thesis_drift_items(db, thesis, None) == []
    assert "thesis_drift_failed" in caplog.text


def test_db_reader_without_tenant_scope_still_reads_by_company(saved):
    db, company, _rival, thesis, tenant, _other = saved
    add_fact(db, company, tenant, 45_436_000_000)
    db.info.pop("tenant_id")
    assert len(thesis_claim_drift(db, thesis)) == 1


@pytest.mark.parametrize("fy2025, expected_warning", [(35_166_000_000, True), (31_850_000_000, False)])
def test_deterministic_answer_measures_historical_thesis_not_latest_fact(saved_net, monkeypatch, fy2025, expected_warning):
    from app.models import FundamentalModelVersion
    from app.services import chat_service

    db, company, _rival, thesis, tenant, _other = saved_net
    db.add(FundamentalModelVersion(
        tenant_id=tenant.id, company_id=company.id, version=1,
        engine_version="test", algorithm_version="test", framework_key="dcf",
        horizon_years=10, status="ok", publishable=True, input_fingerprint="input",
        forecast_fingerprint="forecast", market_snapshot_fingerprint="market",
        valuation_snapshot_fingerprint="valuation",
    ))
    db.commit()
    add_net_debt_facts(db, company, tenant, fy2025=fy2025, fy2026=36_000_000_000)
    monkeypatch.setattr(chat_service, "_english", lambda: False)
    monkeypatch.setattr(chat_service.ChatService, "_rag_chunks", lambda *args: [])
    service = chat_service.ChatService()
    assert [fact.period for fact in service._key_facts(db, company)] == ["2026-12-31:FY"]
    response = service._deterministic_answer(db, "Resume la tesis de KO", "company", "KO")
    assert "Tengo guardada la tesis v1" in response.answer
    assert ("cifra desactualizada, regenerar" in response.answer) is expected_warning


@pytest.mark.parametrize("source_type", ["seed", "manual", "test", "dummy", "placeholder"])
def test_db_reader_ignores_facts_that_are_not_real_sources(saved, source_type):
    db, company, _rival, thesis, tenant, _other = saved
    add_fact(db, company, tenant, 1, source_type=source_type)
    assert thesis_claim_drift(db, thesis) == []


def test_non_source_fact_does_not_mask_or_create_drift_next_to_a_real_one(saved):
    db, company, _rival, thesis, tenant, _other = saved
    add_fact(db, company, tenant, 1, source_type="seed")
    add_fact(db, company, tenant, 45_436_000_000)  # hecho real distinto: sigue habiendo deriva, sin ambiguedad
    [item] = thesis_claim_drift(db, thesis)
    assert item["live_value"] == 45_436_000_000.0
    add_fact(db, company, tenant, 42_120_000_000, metric="net_debt", source_type="test")  # otra metrica: ruido
    assert len(thesis_claim_drift(db, thesis)) == 1
