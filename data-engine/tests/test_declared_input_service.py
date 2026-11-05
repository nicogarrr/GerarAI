"""DeclaredInputService: huecos del modelo declarado y almacén de inputs por tenant.

Feature aprobada por Nico (pipeline automático de inputs que faltan). Empresas
sintéticas: el marco sale de sus etiquetas (``subscriber``) o se pasa
explícito (``space_network``); nada por ticker.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import DeclaredInputValue
from app.models.entities import (
    Base,
    Company,
    CompanyKPI,
    Document,
    DocumentChunk,
    FinancialFact,
    KPIExtractionCandidate,
    Tenant,
)
from app.services.company_framework import FRAMEWORKS
from app.services.declared_input_service import (
    DeclaredInput,
    DeclaredInputError,
    DeclaredInputService,
)

T1, T2 = 1, 2
URL = "https://investors.example.com/press/2026-q3"
# Fórmula del marco (subs × ARPU) y luego las métricas obligatorias del marco.
SUBSCRIBER_INPUTS = ["subscribers", "monthly_arpu", "churn", "retention"]


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([Tenant(id=T1, external_id="t1"), Tenant(id=T2, external_id="t2")])
        session.flush()
        yield session


def _company(db: Session, *, tags: list[str] | None = None, ticker: str = "SYNTH") -> Company:
    company = Company(
        ticker=ticker,
        name="Synthetic Networks",
        exchange="NASDAQ",
        currency="USD",
        sector="Telecom",
        industry="Telecom Services",
        company_type="operating",
        valuation_model="unassigned",
        special_sources=[],
        special_risks=[],
        factor_tags=tags if tags is not None else ["subscriber"],
    )
    db.add(company)
    db.flush()
    return company


def _fact(db, company, metric, *, tenant=T1, quarter=None, value="1000"):
    fact = FinancialFact(
        tenant_id=tenant,
        company_id=company.id,
        metric=metric,
        value=Decimal(value),
        unit="subscribers",
        period="2025:FY" if quarter is None else f"2025:{quarter}",
        fiscal_year=2025,
        fiscal_quarter=quarter,
        source_type="SEC",
    )
    db.add(fact)
    db.flush()
    return fact


def _approved_kpi(db, company, metric, *, tenant=T1, status="approved"):
    kpi = CompanyKPI(tenant_id=tenant, company_id=company.id, metric_key=metric, display_name=metric)
    doc = Document(
        tenant_id=tenant,
        company_id=company.id,
        title="10-Q",
        source_type="SEC",
        published_at=datetime.now(UTC),
        metadata_={},
    )
    db.add_all([kpi, doc])
    db.flush()
    chunk = DocumentChunk(tenant_id=tenant, document_id=doc.id, chunk_index=0, text="ARPU was $9.50")
    db.add(chunk)
    db.flush()
    candidate = KPIExtractionCandidate(
        tenant_id=tenant,
        company_id=company.id,
        company_kpi_id=kpi.id,
        document_id=doc.id,
        document_chunk_id=chunk.id,
        metric_key=metric,
        raw_label=metric,
        raw_value="9.50",
        normalized_value=Decimal("9.5"),
        canonical_unit="USD/subscriber/month",
        period="2025-Q3",
        status=status,
    )
    db.add(candidate)
    db.flush()
    return candidate


def _estimate(key="monthly_arpu", base=5.0, **kw) -> DeclaredInput:
    defaults: dict[str, Any] = dict(
        input_key=key,
        base=base,
        low=3.0,
        high=8.0,
        unit="USD/subscriber/month",
        method="infer",
        source_url=URL,
        as_of=date(2026, 11, 4),
    )
    defaults.update(kw)
    return DeclaredInput(**defaults)


SVC = DeclaredInputService()


# ---------------------------------------------------------------- huecos


def test_sin_datos_los_huecos_son_exactamente_los_inputs_de_la_formula(db):
    company = _company(db)
    report = SVC.detect_gaps(db, company=company, tenant_id=T1)
    assert report.framework_key == "subscriber"
    assert report.formula_key == "subscriber_monetization"
    assert report.gap_keys == SUBSCRIBER_INPUTS
    assert report.covered == ()
    arpu = report.gaps[1]
    assert arpu.bounds == (0.0, 100.0)
    assert arpu.expected_dimension
    assert "subscriber_monetization" in arpu.why


def test_marco_de_red_lista_sus_ocho_inputs_en_orden(db):
    company = _company(db, tags=[])
    report = SVC.detect_gaps(db, company=company, tenant_id=T1, framework=FRAMEWORKS["space_network"])
    assert report.gap_keys == [
        "addressable_subscribers",
        "penetration",
        "monthly_arpu",
        "revenue_share",
        "satellites",
        "capacity_per_satellite",
        "utilization",
        "price_per_gb",
    ]


def test_extra_inputs_del_motor_se_anaden_como_huecos(db):
    company = _company(db)
    report = SVC.detect_gaps(db, company=company, tenant_id=T1, extra_inputs=["deployment.life_years"])
    assert report.gap_keys == [*SUBSCRIBER_INPUTS, "deployment.life_years"]
    assert report.gaps[-1].bounds == (3.0, 20.0)


def test_fact_anual_cubre_pero_un_trimestral_no(db):
    company = _company(db)
    _fact(db, company, "monthly_arpu", quarter="Q3")
    fact = _fact(db, company, "subscribers")
    report = SVC.detect_gaps(db, company=company, tenant_id=T1)
    assert report.gap_keys == ["monthly_arpu", "churn", "retention"]
    assert [(c.key, c.source, c.record_ids) for c in report.covered] == [
        ("subscribers", "financial_fact", (fact.id,))
    ]


def test_kpi_aprobado_cubre_y_uno_pendiente_no(db):
    company = _company(db)
    _approved_kpi(db, company, "subscribers", status="pending_approval")
    approved = _approved_kpi(db, company, "monthly_arpu")
    report = SVC.detect_gaps(db, company=company, tenant_id=T1)
    assert report.gap_keys == ["subscribers", "churn", "retention"]
    assert report.covered[0].source == "approved_kpi"
    assert report.covered[0].record_ids == (approved.id,)


def test_input_declarado_vigente_cubre_y_dado_de_baja_no(db):
    company = _company(db)
    SVC.upsert(db, company=company, tenant_id=T1, item=_estimate())
    SVC.upsert(
        db,
        company=company,
        tenant_id=T1,
        item=_estimate("subscribers", base=1e8, low=5e7, high=2e8, unit="subscribers"),
    )
    for rate in ("churn", "retention"):
        SVC.upsert(
            db,
            company=company,
            tenant_id=T1,
            item=_estimate(rate, base=0.02, low=0.01, high=0.05, unit="ratio"),
        )
    report = SVC.detect_gaps(db, company=company, tenant_id=T1)
    assert report.gap_keys == []
    assert {c.source for c in report.covered} == {"declared_input"}
    assert all(c.status == "estimado" and not c.blocks_publication for c in report.covered)

    assert SVC.retire(db, company_id=company.id, tenant_id=T1, input_key="monthly_arpu")
    report = SVC.detect_gaps(db, company=company, tenant_id=T1)
    assert report.gap_keys == ["monthly_arpu"]
    assert len(report.covered) == 3


def test_valor_por_defecto_cubre_pero_bloquea_la_publicacion(db):
    company = _company(db)
    SVC.upsert(db, company=company, tenant_id=T1, item=_estimate(method="default", source_url=None))
    cov = {c.key: c for c in SVC.detect_gaps(db, company=company, tenant_id=T1).covered}
    assert cov["monthly_arpu"].status == "supuesto_por_defecto"
    assert cov["monthly_arpu"].blocks_publication is True


def test_fila_guardada_que_ya_no_valida_no_cubre(db):
    company = _company(db)
    row = SVC.upsert(db, company=company, tenant_id=T1, item=_estimate()).row
    row.base = Decimal("500")  # fuera de (0, 100] $/mes: ya no es utilizable
    db.flush()
    assert SVC.detect_gaps(db, company=company, tenant_id=T1).gap_keys == SUBSCRIBER_INPUTS


# ---------------------------------------------------------------- tenant


def test_datos_de_otro_tenant_no_cubren_ni_se_leen(db):
    company = _company(db)
    _fact(db, company, "subscribers", tenant=T2)
    _approved_kpi(db, company, "monthly_arpu", tenant=T2)
    SVC.upsert(db, company=company, tenant_id=T2, item=_estimate())
    assert SVC.detect_gaps(db, company=company, tenant_id=T1).gap_keys == SUBSCRIBER_INPUTS
    assert SVC.current(db, company_id=company.id, tenant_id=T1) == {}
    assert set(SVC.current(db, company_id=company.id, tenant_id=T2)) == {("monthly_arpu", "")}
    assert SVC.detect_gaps(db, company=company, tenant_id=T2).gap_keys == ["churn", "retention"]


def test_sin_tenant_o_con_tenant_distinto_al_de_la_sesion_falla_cerrado(db):
    company = _company(db)
    for bad in (None, 0, -1, "1"):
        with pytest.raises(DeclaredInputError):
            SVC.upsert(db, company=company, tenant_id=bad, item=_estimate())  # type: ignore[arg-type]
        with pytest.raises(DeclaredInputError):
            SVC.detect_gaps(db, company=company, tenant_id=bad)  # type: ignore[arg-type]
    db.info["tenant_id"] = T1
    with pytest.raises(DeclaredInputError):
        SVC.current(db, company_id=company.id, tenant_id=T2)
    assert db.scalar(select(DeclaredInputValue)) is None


# ---------------------------------------------------------------- upsert


def test_upsert_idempotente_y_con_historico(db):
    company = _company(db)
    first = SVC.upsert(db, company=company, tenant_id=T1, item=_estimate())
    again = SVC.upsert(db, company=company, tenant_id=T1, item=_estimate())
    assert (first.changed, first.reason) == (True, "created")
    assert (again.changed, again.reason) == (False, "unchanged")
    assert again.row.id == first.row.id
    assert len(db.scalars(select(DeclaredInputValue)).all()) == 1

    revised = SVC.upsert(db, company=company, tenant_id=T1, item=_estimate(base=6.0))
    assert (revised.changed, revised.reason) == (True, "replaced")
    history = SVC.history(db, company_id=company.id, tenant_id=T1, input_key="monthly_arpu")
    assert [h.base for h in history] == [Decimal("5.00000000"), Decimal("6.00000000")]
    assert history[0].superseded_at is not None and history[1].superseded_at is None
    current = SVC.current(db, company_id=company.id, tenant_id=T1)
    assert current[("monthly_arpu", "")].id == revised.row.id


def test_segmentos_distintos_conviven(db):
    company = _company(db)
    SVC.upsert(db, company=company, tenant_id=T1, item=_estimate(segment_key="us"))
    SVC.upsert(db, company=company, tenant_id=T1, item=_estimate(segment_key="intl", base=2.0, low=1.0))
    assert set(SVC.current(db, company_id=company.id, tenant_id=T1)) == {
        ("monthly_arpu", "us"),
        ("monthly_arpu", "intl"),
    }


def test_precedencia_manual_gana_y_un_estimado_no_desplaza_al_oficial(db):
    company = _company(db)
    official = _estimate(method="extract", source_quote="ARPU of $5.00 per month", base=5.0)
    SVC.upsert(db, company=company, tenant_id=T1, item=official)
    kept = SVC.upsert(db, company=company, tenant_id=T1, item=_estimate(base=7.0))
    assert (kept.changed, kept.reason, kept.row.status) == (False, "kept_higher_precedence", "oficial")

    manual = SVC.upsert(
        db,
        company=company,
        tenant_id=T1,
        item=_estimate(method="manual", source_url=None, base=6.5),
    )
    assert (manual.changed, manual.row.status) == (True, "manual")
    after = SVC.upsert(db, company=company, tenant_id=T1, item=official)
    assert (after.changed, after.reason) == (False, "kept_higher_precedence")


def test_supuesto_de_analista_es_estimado_y_nombra_la_firma(db):
    company = _company(db)
    result = SVC.upsert(
        db,
        company=company,
        tenant_id=T1,
        item=_estimate(method="analyst", analyst_firm="Firma X", metadata={"rank": 1}),
    )
    assert (result.row.status, result.row.method, result.row.analyst_firm) == (
        "estimado",
        "analyst",
        "Firma X",
    )
    assert result.row.metadata_ == {"rank": 1}


@pytest.mark.parametrize(
    ("item", "fragment"),
    [
        (_estimate("penetration", base=0.8, low=0.1, high=0.9, unit="ratio"), "fuera de rango"),
        (_estimate("penetration", base=20, low=10, high=30, unit="percent"), "decimal"),
        (_estimate(unit="USD"), "unidad incompatible"),
        (_estimate(source_url=None), "URL https"),
        (_estimate(source_url="http://example.com/x"), "URL https"),
        (_estimate(method="analyst"), "firma"),
        (_estimate(analyst_firm="Firma X"), "analyst_firm"),
        (_estimate(low=6.0), "bajo > base"),
        (_estimate(high=4.0), "alto < base"),
        (_estimate(base=float("nan")), "finito"),
        (_estimate(method="extract"), "cita literal"),
        (_estimate(method="inventado"), "método desconocido"),
        (_estimate("Monthly ARPU"), "clave de input"),
        (_estimate(unit=""), "falta la unidad"),
    ],
)
def test_validacion_rechaza_con_motivo(db, item, fragment):
    company = _company(db)
    with pytest.raises(DeclaredInputError) as err:
        SVC.upsert(db, company=company, tenant_id=T1, item=item)
    assert any(fragment in problem for problem in err.value.problems), err.value.problems
    assert db.scalar(select(DeclaredInputValue)) is None


def test_dato_oficial_vale_con_documento_y_cita_sin_url(db):
    company = _company(db)
    doc = Document(
        tenant_id=T1,
        company_id=company.id,
        title="10-Q",
        source_type="SEC",
        published_at=datetime.now(UTC),
        metadata_={},
    )
    db.add(doc)
    db.flush()
    result = SVC.upsert(
        db,
        company=company,
        tenant_id=T1,
        item=DeclaredInput(
            input_key="revenue_share",
            base=0.5,
            unit="ratio",
            method="extract",
            source_quote="we share revenue 50/50 with our partners",
            document_id=doc.id,
        ),
    )
    assert result.row.status == "oficial"
    assert result.row.document_id == doc.id
