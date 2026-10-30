"""PR A: proyeccion determinista de tesis a 5 ejercicios (sin LLM)."""

from __future__ import annotations

import threading
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.thesis_projection import router
from app.core.database import Base, get_db
from app.models import (
    Company,
    Document,
    FinancialFact,
    InferredInput,
    MarketPrice,
    Position,
    Tenant,
    ThesisProjectionYear,
    ValuationAssumption,
    ValuationModel,
    ValuationOutput,
)
from app.services import thesis_projection_service as svc_module
from app.services.thesis_projection_service import ThesisProjectionService
from app.services.valuation_service import ValuationService
from app.valuation.point_in_time import LookaheadError

AS_OF = date(2026, 10, 9)
FAKE_VALUATION = {
    "bear_value": 40.0,
    "base_value": 50.0,
    "bull_value": 65.0,
    "publishable": True,
    "publication_blockers": [],
}


def fake_value_company(self, db, company, *, as_of=None):  # noqa: ARG001
    """Valor por accion actual fijo: el DCF real se prueba en su propio suite."""
    return dict(FAKE_VALUATION)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add_all(
            [Tenant(id=1, external_id="a"), Tenant(id=2, external_id="b")]
        )
        session.commit()
        session.info["tenant_id"] = 1
        session.add_all(
            [
                Company(
                    id=1,
                    ticker="TEST",
                    name="Test Co",
                    exchange="NASDAQ",
                    company_type="large_cap",
                    valuation_model="dcf",
                ),
                Company(
                    id=2,
                    ticker="EMPTY",
                    name="Sin Datos",
                    exchange="NASDAQ",
                    company_type="large_cap",
                    valuation_model="dcf",
                ),
            ]
        )
        for year, revenue in ((2022, 64.0), (2023, 80.0), (2024, 100.0)):
            session.add(
                FinancialFact(
                    company_id=1,
                    metric="revenue",
                    value=Decimal(str(revenue)),
                    unit="USD",
                    period=f"{year}-12-31:FY",
                    fiscal_year=year,
                    source_type="SEC",
                )
            )
        for metric, value in (
            ("free_cash_flow", 20.0),
            ("net_income", 10.0),
            ("shares_diluted", 10.0),
        ):
            session.add(
                FinancialFact(
                    company_id=1,
                    metric=metric,
                    value=Decimal(str(value)),
                    unit="USD",
                    period="2024-12-31:FY",
                    fiscal_year=2024,
                    source_type="SEC",
                )
            )
        session.add(
            MarketPrice(
                company_id=1,
                date=date(2026, 10, 8),
                close=Decimal("100"),
                source="seed",
            )
        )
        session.commit()
        yield session
    engine.dispose()


@pytest.fixture
def valued(monkeypatch):
    monkeypatch.setattr(ValuationService, "value_company", fake_value_company)
    return monkeypatch


def project(db, ticker_id=1):
    company = db.get(Company, ticker_id)
    return ThesisProjectionService().project(db, company, as_of=AS_OF)


def client_for(db):
    app = FastAPI()
    app.include_router(router, prefix="/companies")
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_projection_is_deterministic_and_labelled(db, valued):
    payload = project(db)
    assert payload["ejercicio_base"] == 2024
    assert payload["disclaimer"] == svc_module.DISCLAIMER_ES
    base = payload["escenarios"]["base"]["proyecciones"]
    assert [row["ejercicio"] for row in base] == [2025, 2026, 2027, 2028, 2029]
    # CAGR 2022-2024 = (100/64)^(1/2) - 1 = 0.25 exacto.
    assert base[0]["crecimiento"]["valor"] == pytest.approx(0.25)
    assert base[0]["ingresos"] == pytest.approx(125.0)
    assert base[-1]["ingresos"] == pytest.approx(100.0 * 1.25**5)
    assert base[-1]["fcf"] == pytest.approx(100.0 * 1.25**5 * 0.20)
    assert base[-1]["bps"] == pytest.approx(100.0 * 1.25**5 * 0.10 / 10.0)
    assert base[-1]["etiqueta"] == "INFERIDO"
    assert base[-1]["etiquetas"] == {
        "ingresos": "INFERIDO",
        "fcf": "INFERIDO",
        "bps": "INFERIDO",
    }
    assert "CAGR de ingresos FY2022-FY2024" in base[0]["crecimiento"]["base"]


def test_official_requires_verified_document(db, valued):
    # Facts SEC sin documento enlazado: fail-closed a INFERIDO, nunca OFICIAL.
    payload = project(db)
    ingresos = payload["base"]["ingresos"]
    assert ingresos["etiqueta"] == "INFERIDO"
    assert "sin documento con url y fecha" in ingresos["fuente"]

    # Con documento persistido con url + fecha: OFICIAL verificado.
    doc = Document(
        company_id=1,
        title="10-K FY2024",
        source_type="primary_official",
        source_url="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany",
        published_at=datetime(2025, 2, 15, tzinfo=UTC),
    )
    db.add(doc)
    db.flush()
    fact = db.scalar(
        select(FinancialFact).where(
            FinancialFact.company_id == 1,
            FinancialFact.metric == "revenue",
            FinancialFact.fiscal_year == 2024,
        )
    )
    fact.source_id = doc.id
    db.commit()
    ingresos = project(db)["base"]["ingresos"]
    assert ingresos["etiqueta"] == "OFICIAL"
    assert ingresos["fuente_url"] == doc.source_url
    assert ingresos["fuente_fecha"] == "2025-02-15"

    # Documento sin url: la oficialidad no se verifica -> INFERIDO.
    doc.source_url = None
    db.commit()
    assert project(db)["base"]["ingresos"]["etiqueta"] == "INFERIDO"


def test_stored_assumption_labeling_is_fail_closed(db, valued):
    model = ValuationModel(
        company_id=1, model_type="dcf", version=1, status="final"
    )
    db.add(model)
    db.flush()
    db.add(
        ValuationAssumption(
            valuation_model_id=model.id,
            name="revenue_growth",
            value=Decimal("0.50"),
            scenario="base",
            year=2025,
            source_type="SEC",
            # created_at fijado: la guardia anti-look-ahead compara con
            # AS_OF (2026-10-09) y el default "ahora" romperia el test en
            # cuanto el calendario lo superara.
            created_at=datetime(2026, 10, 8, tzinfo=UTC),
        )
    )
    db.commit()
    growth = project(db)["escenarios"]["base"]["proyecciones"][0]["crecimiento"]
    assert growth["valor"] == pytest.approx(0.50)
    # source_type SEC sin documento verificable: INFERIDO, no OFICIAL.
    assert growth["etiqueta"] == "INFERIDO"
    assert "sin documento con url y fecha" in growth["base"]


def test_official_rate_exposes_url_and_date(db, valued):
    # Rama OFICIAL completa: la url y la fecha verificadas llegan al payload.
    doc = Document(
        company_id=1,
        title="Guidance FY2025",
        source_type="primary_official",
        source_url="https://www.sec.gov/guidance",
        published_at=datetime(2025, 2, 1, tzinfo=UTC),
    )
    db.add(doc)
    db.flush()
    model = ValuationModel(
        company_id=1, model_type="dcf", version=1, status="final"
    )
    db.add(model)
    db.flush()
    db.add(
        ValuationAssumption(
            valuation_model_id=model.id,
            name="revenue_growth",
            value=Decimal("0.50"),
            scenario="base",
            year=2025,
            source_type="SEC",
            source_id=doc.id,
            # created_at fijado: la guardia anti-look-ahead compara con
            # AS_OF (2026-10-09) y el default "ahora" romperia el test en
            # cuanto el calendario lo superara.
            created_at=datetime(2026, 10, 8, tzinfo=UTC),
        )
    )
    db.commit()
    growth = project(db)["escenarios"]["base"]["proyecciones"][0]["crecimiento"]
    assert growth["valor"] == pytest.approx(0.50)
    assert growth["etiqueta"] == "OFICIAL"
    assert growth["fuente_url"] == "https://www.sec.gov/guidance"
    assert growth["fuente_fecha"] == "2025-02-01"


def test_scenario_spread_and_burn_rule(db, valued):
    payload = project(db)
    first = {
        s: payload["escenarios"][s]["proyecciones"][0] for s in ("bear", "base", "bull")
    }
    assert first["bear"]["crecimiento"]["valor"] == pytest.approx(0.25 - 0.08)
    assert first["bull"]["crecimiento"]["valor"] == pytest.approx(0.25 + 0.08)
    assert first["bear"]["margen_fcf"]["valor"] == pytest.approx(0.20 - 0.06)
    assert first["bull"]["margen_fcf"]["valor"] == pytest.approx(0.20 + 0.06)
    assert first["bear"]["etiqueta"] == "INFERIDO"


def test_bull_margin_cap_never_below_a_high_base_margin(db, valued):
    """Margen FCF base 50% (FCF 50 / ingresos 100): el techo del 45% del
    bull no puede dejarlo por debajo del base. Esperado a mano: bull = 50%
    (min(0,50 + 0,06; max(0,45; 0,50))); bear = 0,50 - 0,06 = 44%.
    Un base del 40% sigue recortado al techo: min(0,46; 0,45) = 45%."""
    fcf = db.scalar(select(FinancialFact).where(FinancialFact.metric == "free_cash_flow"))
    fcf.value = Decimal("50")
    db.commit()
    first = {s: project(db)["escenarios"][s]["proyecciones"][0] for s in ("bear", "base", "bull")}
    assert first["base"]["margen_fcf"]["valor"] == pytest.approx(0.50)
    assert first["bull"]["margen_fcf"]["valor"] == pytest.approx(0.50)
    assert first["bear"]["margen_fcf"]["valor"] == pytest.approx(0.44)
    fcf.value = Decimal("40")
    db.commit()
    bull = project(db)["escenarios"]["bull"]["proyecciones"][0]
    assert bull["margen_fcf"]["valor"] == pytest.approx(0.45)


def test_target_price_uses_valuation_service_and_dated_price(db, valued):
    payload = project(db)
    targets = {
        s: payload["escenarios"][s]["precio_objetivo_5y"] for s in ("bear", "base", "bull")
    }
    # ancla FCF/accion = 20/10 = 2; multiplo base = 50/2 = 25.
    assert payload["ancla_precio_objetivo"] == "fcf"
    fcf5_ps = 100.0 * 1.25**5 * 0.20 / 10.0
    assert targets["base"]["valor"] == pytest.approx(fcf5_ps * 25.0)
    assert targets["base"]["etiqueta"] == "INFERIDO"
    assert targets["base"]["precio_actual"] == pytest.approx(100.0)
    assert targets["base"]["precio_fecha"] == "2026-10-08"
    assert targets["base"]["mos"] == pytest.approx((fcf5_ps * 25.0 - 100.0) / (fcf5_ps * 25.0))
    assert payload["aviso_coherencia"] is None
    assert targets["bear"]["valor"] < targets["base"]["valor"] < targets["bull"]["valor"]


def test_adr_target_and_mos_are_per_adr_not_per_ordinary(db, monkeypatch):
    """ADR de 4 ordinarias, precio 100 por ADR. A mano, en base ADR:
    FCF/ADR = 4 * 20/10 = 8; valor base/ADR = 4 * 50 = 200 -> múltiplo 25;
    múltiplo de mercado = 100 / 8 = 12,5 -> tope 12,5.
    FCF a 5 años/ADR = 4 * 100 * 1,25^5 * 0,20 / 10 = 24,414 -> objetivo 305,18.
    Antes: objetivo por ordinaria (6,10 * 25 = 152,6) comparado con el precio ADR."""

    def adr_valuation(self, db, company, *, as_of=None):  # noqa: ARG001
        return {**FAKE_VALUATION, "adr_ratio": 4.0}

    monkeypatch.setattr(ValuationService, "value_company", adr_valuation)
    target = project(db)["escenarios"]["base"]["precio_objetivo_5y"]
    fcf5_per_adr = 4 * 100.0 * 1.25**5 * 0.20 / 10.0
    expected = fcf5_per_adr * 12.5
    assert target["valor"] == pytest.approx(expected)
    assert target["mos"] == pytest.approx((expected - 100.0) / expected)
    assert "por ADR (4 acciones ordinarias)" in target["base"]


def test_blocked_engine_is_never_rescaled_to_final(db, monkeypatch):
    def blocked(self, db, company, *, as_of=None):  # noqa: ARG001
        return {
            "bear_value": 40.0,
            "base_value": 50.0,
            "bull_value": 65.0,
            "publishable": False,
            "status": "blocked",
            "publication_blockers": ["source_missing"],
        }

    monkeypatch.setattr(ValuationService, "value_company", blocked)
    payload = project(db)
    for scenario in ("bear", "base", "bull"):
        target = payload["escenarios"][scenario]["precio_objetivo_5y"]
        assert target["valor"] is None and target["etiqueta"] == "N/D"
        assert target["mos"] is None
        assert target["bloqueos"] == ["source_missing"]
        assert "no publicable" in target["base"]
    # Y no se persiste como final ni con ValuationOutput.
    model = ThesisProjectionService().persist(db, db.get(Company, 1), payload)
    assert model.status == "draft"
    assert db.scalars(select(ValuationOutput)).all() == []


def test_mos_requires_dated_price(db, valued):
    # Un mark de Position manual no tiene fecha de precio: MOS queda N/D y la
    # comparacion no se persiste como final. Sin cierres en DB (un cierre
    # fechado ganaria al mark sin fecha: el precio mas fresco manda).
    db.query(MarketPrice).delete()
    db.add(
        Position(
            company_id=1,
            quantity=Decimal("5"),
            average_cost=Decimal("80"),
            market_price=Decimal("123"),
        )
    )
    db.commit()
    payload = project(db)
    target = payload["escenarios"]["base"]["precio_objetivo_5y"]
    assert target["precio_actual"] == pytest.approx(123.0)
    assert target["precio_fecha"] is None
    # Sin precio fechado no se puede acotar el multiplo: N/D con razon, nunca un 0.
    assert target["valor"] is None and target["etiqueta"] == "N/D"
    assert "sin precio fechado" in target["base"]
    assert target["mos"] is None
    model = ThesisProjectionService().persist(db, db.get(Company, 1), payload)
    assert model.status == "draft"
    assert db.scalars(select(ValuationOutput)).all() == []


def test_missing_inputs_are_nd_never_zero(db):
    payload = project(db, ticker_id=2)
    assert payload["ejercicio_base"] is None
    for scenario in ("bear", "base", "bull"):
        assert payload["escenarios"][scenario]["proyecciones"] == []
        target = payload["escenarios"][scenario]["precio_objetivo_5y"]
        assert target["valor"] is None and target["etiqueta"] == "N/D"
        assert target["mos"] is None
    assert payload["base"]["ingresos"]["etiqueta"] == "N/D"
    assert payload["ancla_precio_objetivo"] is None


def test_no_lookahead_on_period_close_beyond_as_of(db):
    # FY2026 cierra 2026-12-31: con as_of 2026-10-09 ese cierre es futuro,
    # aunque el ejercicio coincida con el ano del corte.
    db.add(
        FinancialFact(
            company_id=1,
            metric="revenue",
            value=Decimal("999"),
            unit="USD",
            period="2026-12-31:FY",
            fiscal_year=2026,
            source_type="SEC",
        )
    )
    db.commit()
    with pytest.raises(LookaheadError):
        project(db)


def test_no_lookahead_on_document_publication_date(db):
    doc = Document(
        company_id=1,
        title="10-K FY2024",
        source_type="primary_official",
        source_url="https://www.sec.gov/x",
        published_at=datetime(2027, 2, 1, tzinfo=UTC),
    )
    db.add(doc)
    db.flush()
    fact = db.scalar(
        select(FinancialFact).where(
            FinancialFact.company_id == 1,
            FinancialFact.metric == "revenue",
            FinancialFact.fiscal_year == 2024,
        )
    )
    fact.source_id = doc.id
    db.commit()
    with pytest.raises(LookaheadError):
        project(db)


def test_no_lookahead_on_old_cagr_endpoint_publication(db):
    # Repro del auditor: el documento futuro cuelga del FY VIEJO (extremo del
    # CAGR), no del ancla reciente. Tambien se rechaza.
    doc = Document(
        company_id=1,
        title="Restatement FY2022",
        source_type="primary_official",
        source_url="https://www.sec.gov/restatement",
        published_at=datetime(2027, 2, 1, tzinfo=UTC),
    )
    db.add(doc)
    db.flush()
    old_fact = db.scalar(
        select(FinancialFact).where(
            FinancialFact.company_id == 1,
            FinancialFact.metric == "revenue",
            FinancialFact.fiscal_year == 2022,
        )
    )
    old_fact.source_id = doc.id
    db.commit()
    with pytest.raises(LookaheadError):
        project(db)


def test_no_lookahead_on_future_assumption_versions(db):
    model = ValuationModel(
        company_id=1, model_type="dcf", version=1, status="final"
    )
    db.add(model)
    db.flush()
    db.add(
        ValuationAssumption(
            valuation_model_id=model.id,
            name="revenue_growth",
            value=Decimal("0.50"),
            scenario="base",
            year=2025,
            source_type="model",
            created_at=datetime(2099, 1, 1, tzinfo=UTC),
        )
    )
    db.add(
        InferredInput(
            company_id=1,
            input_key="fcf_margin",
            value=Decimal("0.30"),
            base="dado el margen historico, inferimos un margen normalizado",
            source_urls=["https://www.sec.gov/x"],
            created_at=datetime(2099, 1, 1, tzinfo=UTC),
        )
    )
    db.commit()
    with pytest.raises(LookaheadError):
        project(db)


def test_no_lookahead_raises_on_future_facts(db):
    db.add(
        FinancialFact(
            company_id=1,
            metric="revenue",
            value=Decimal("999"),
            unit="USD",
            period="2099-12-31:FY",
            fiscal_year=2099,
            source_type="SEC",
        )
    )
    db.commit()
    with pytest.raises(LookaheadError):
        project(db)


def test_non_positive_cagr_anchor_is_nd_never_exception(db, valued):
    # Repro del auditor: revenue2022=64 y revenue2024=-100. El CAGR no esta
    # definido (base negativa -> complejo): N/D, nunca TypeError.
    fact = db.scalar(
        select(FinancialFact).where(
            FinancialFact.company_id == 1,
            FinancialFact.metric == "revenue",
            FinancialFact.fiscal_year == 2024,
        )
    )
    fact.value = Decimal("-100")
    db.commit()
    payload = project(db)
    assert payload["base"]["crecimiento_base"]["etiqueta"] == "N/D"
    for scenario in ("bear", "base", "bull"):
        for row in payload["escenarios"][scenario]["proyecciones"]:
            assert row["ingresos"] is None and row["etiqueta"] == "N/D"
        assert payload["escenarios"][scenario]["precio_objetivo_5y"]["valor"] is None
    with client_for(db) as client:
        response = client.get("/companies/TEST/thesis-5y")
        assert response.status_code == 200
        assert response.json()["escenarios"]["base"]["proyecciones"][-1]["ingresos"] is None


def test_tenant_isolation(db, valued):
    assert project(db)["escenarios"]["base"]["proyecciones"] != []
    db.info["tenant_id"] = 2
    payload = project(db)
    # Los facts son del tenant 1: para el tenant 2 la empresa no tiene datos.
    assert payload["escenarios"]["base"]["proyecciones"] == []
    assert payload["base"]["ingresos"]["etiqueta"] == "N/D"


def test_coherence_warning_when_scenarios_invert(db, monkeypatch):
    def inverted(self, db, company, *, as_of=None):  # noqa: ARG001
        return {
            "bear_value": 900.0,
            "base_value": 50.0,
            "bull_value": 40.0,
            "publishable": True,
            "publication_blockers": [],
        }

    monkeypatch.setattr(ValuationService, "value_company", inverted)
    payload = project(db)
    assert payload["aviso_coherencia"] is not None
    assert "bear <= base <= bull" in payload["aviso_coherencia"]


def test_get_endpoint_e2e(db, valued):
    with client_for(db) as client:
        body = client.get("/companies/TEST/thesis-5y").json()
        assert body["ticker"] == "TEST"
        assert set(body["escenarios"]) == {"bear", "base", "bull"}
        assert body["disclaimer"] == svc_module.DISCLAIMER_ES
        assert body["persistido"] is None
        assert client.get("/companies/NOPE/thesis-5y").status_code == 404
    # El GET es calculo puro: no persiste nada.
    assert db.scalar(select(func.count(ValuationModel.id))) == 0


def test_post_persists_and_is_idempotent_per_day(db, valued):
    with client_for(db) as client:
        first = client.post("/companies/TEST/thesis-5y/recalcular")
        assert first.status_code == 201
        body = first.json()
        assert body["persistido"]["version"] == 1
        assert body["persistido"]["status"] == "final"
        second = client.post("/companies/TEST/thesis-5y/recalcular")
        assert second.status_code == 201 and second.json()["persistido"]["version"] == 2
    models = db.scalars(
        select(ValuationModel).where(ValuationModel.model_type == "thesis_5y")
    ).all()
    assert len(models) == 2 and models[0].tenant_id == 1
    outputs = db.scalars(select(ValuationOutput)).all()
    assert {o.scenario for o in outputs} == {"bear", "base", "bull"}
    rows = db.scalars(select(ThesisProjectionYear)).all()
    # 3 escenarios x 5 ejercicios; el segundo POST sustituye, no apila.
    assert len(rows) == 15
    assert {row.label for row in rows} == {"INFERIDO"}
    assert all(row.revenue is not None for row in rows)


def test_post_quota_is_tenant_wide_across_companies(db, valued, monkeypatch):
    # Repro del auditor: cuota=1, POST a DOS empresas del mismo tenant.
    monkeypatch.setattr(svc_module, "DAILY_RECALC_QUOTA", 1)
    with client_for(db) as client:
        assert client.post("/companies/TEST/thesis-5y/recalcular").status_code == 201
        blocked = client.post("/companies/EMPTY/thesis-5y/recalcular")
        assert blocked.status_code == 429
        assert "cuota diaria" in blocked.json()["detail"]


def test_post_requires_tenant(db, valued):
    db.info.clear()
    with client_for(db) as client:
        assert client.post("/companies/TEST/thesis-5y/recalcular").status_code == 403


def test_quota_is_atomic_under_concurrent_recalcs(tmp_path, monkeypatch):
    """Check+persist serializado: N POST simultaneos con cuota 1 -> 1 ok, N-1 429."""
    monkeypatch.setattr(svc_module, "DAILY_RECALC_QUOTA", 1)
    engine = create_engine(
        f"sqlite:///{tmp_path / 'q.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    with Session(engine) as setup:
        setup.add(Tenant(id=1, external_id="q-1"))
        setup.commit()
        setup.info["tenant_id"] = 1
        setup.add(
            Company(
                id=1,
                ticker="TEST",
                name="Test Co",
                exchange="NASDAQ",
                company_type="large_cap",
                valuation_model="dcf",
            )
        )
        for year, revenue in ((2023, 80.0), (2024, 100.0)):
            setup.add(
                FinancialFact(
                    company_id=1,
                    metric="revenue",
                    value=Decimal(str(revenue)),
                    unit="USD",
                    period=f"{year}-12-31:FY",
                    fiscal_year=year,
                    source_type="SEC",
                )
            )
        setup.commit()

    outcomes: list[str] = []

    def recalc():
        with Session(engine, expire_on_commit=False) as session:
            session.info["tenant_id"] = 1
            try:
                ThesisProjectionService().recalculate_within_quota(
                    session, session.get(Company, 1), as_of=AS_OF
                )
                outcomes.append("ok")
            except svc_module.ProjectionQuotaExceeded:
                outcomes.append("quota")

    threads = [threading.Thread(target=recalc) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["ok"] + ["quota"] * 5
    with Session(engine) as session:
        session.info["tenant_id"] = 1
        assert session.scalar(select(func.count(ValuationModel.id))) == 1
    engine.dispose()


def test_persist_skips_outputs_without_target_or_mos(db):
    # Sin ValuationService mockeado el DCF real no tiene inputs suficientes:
    # no publicable -> objetivo N/D -> no se graba ValuationOutput ni final.
    payload = project(db)
    model = ThesisProjectionService().persist(db, db.get(Company, 1), payload)
    assert model.status == "draft"
    assert db.scalars(select(ValuationOutput)).all() == []
    rows = db.scalars(select(ThesisProjectionYear)).all()
    assert len(rows) == 15


def _fixed_values(monkeypatch, bear, base, bull):
    def fixed(self, db, company, *, as_of=None):  # noqa: ARG001
        return {
            "bear_value": bear,
            "base_value": base,
            "bull_value": bull,
            "publishable": True,
            "publication_blockers": [],
        }

    monkeypatch.setattr(ValuationService, "value_company", fixed)


def test_guard_blanks_target_outside_price_range(db, monkeypatch):
    # precio 100; ancla FCF/accion 2. bull con multiplo enorme -> fuera de 4x.
    _fixed_values(monkeypatch, 20.0, 50.0, 5000.0)
    payload = project(db)
    bull = payload["escenarios"]["bull"]["precio_objetivo_5y"]
    assert bull["valor"] is None and bull["mos"] is None and bull["etiqueta"] == "N/D"
    assert "fuera de rango" in bull["base"]
    assert payload["escenarios"]["base"]["precio_objetivo_5y"]["valor"] is not None


def test_guard_blanks_all_when_unordered_and_persist_has_no_outputs(db, monkeypatch):
    _fixed_values(monkeypatch, 90.0, 40.0, 25.0)
    payload = project(db)
    for scenario in ("bear", "base", "bull"):
        target = payload["escenarios"][scenario]["precio_objetivo_5y"]
        assert target["valor"] is None and target["etiqueta"] == "N/D"
        assert "incoherentes" in target["base"]
    assert payload["aviso_coherencia"] is not None
    model = ThesisProjectionService().persist(db, db.get(Company, 1), payload)
    assert model.status == "draft"
    assert db.scalars(select(ValuationOutput)).all() == []


def test_multiple_is_capped_at_current_market_multiple(db, monkeypatch):
    # precio 100, ancla FCF/accion 2 -> multiplo de mercado 50x. El valor base de 500
    # implica 250x: sin tope contaria el crecimiento dos veces.
    _fixed_values(monkeypatch, 20.0, 500.0, 600.0)
    payload = project(db)
    base = payload["escenarios"]["base"]["precio_objetivo_5y"]
    fcf5_ps = 100.0 * 1.25**5 * 0.20 / 10.0
    assert base["valor"] == pytest.approx(fcf5_ps * 50.0)
    assert "acotado al multiplo de mercado actual (50.0x" in base["base"]
    assert "2026-10-08" in base["base"]
    assert base["etiqueta"] == "INFERIDO"


def test_multiple_below_market_is_not_changed(db, monkeypatch):
    _fixed_values(monkeypatch, 20.0, 50.0, 60.0)  # 25x base, por debajo de 50x
    base = project(db)["escenarios"]["base"]["precio_objetivo_5y"]
    assert base["valor"] == pytest.approx(100.0 * 1.25**5 * 0.20 / 10.0 * 25.0)
    assert "acotado" not in base["base"]
