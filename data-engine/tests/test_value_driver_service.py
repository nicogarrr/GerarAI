"""ValueDriverService: inventario de impulsores de valor por tenant (etapa «Recopilador»).

Feature aprobada por Nico (equipo de expertos del Cerebro: «agente recopilador de
todo», «escenarios reales, no hardcodeo»). Empresa sintética; nada por ticker.
Cubre: validación fail-closed, aislamiento por tenant, idempotencia e histórico,
la puerta «impulsor firmado y material sin tratar» y que un rumor (foro, X)
nunca cuenta como firmado.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import ValueDriver
from app.models.entities import Base, Company, Tenant
from app.services.value_driver_service import (
    BLOCK_REASON,
    ValueDriverError,
    ValueDriverItem,
    ValueDriverService,
    is_material,
    normalize_item,
    publication_check,
)

T1, T2 = 1, 2
URL = "https://investors.example.com/press/2026-10-01"
QUOTE = "We signed a definitive agreement with Partner A for 5 years."


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([Tenant(id=T1, external_id="t1"), Tenant(id=T2, external_id="t2")])
        session.flush()
        yield session


def _company(db: Session) -> Company:
    company = Company(
        ticker="SYNTH",
        name="Synthetic Networks",
        exchange="NASDAQ",
        currency="USD",
        sector="Telecom",
        industry="Telecom Services",
        company_type="operating",
        valuation_model="unassigned",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.flush()
    return company


def _item(**overrides) -> ValueDriverItem:
    base = {
        "driver_key": "contrato_socio_a",
        "category": "contrato",
        "name": "Acuerdo definitivo con el socio A",
        "status": "firmado",
        "source_type": "filing",
        "evidence": "oficial",
        "source_url": URL,
        "source_quote": QUOTE,
        "as_of": date(2026, 10, 1),
        "economics": {"amount": 500, "currency": "USD", "amount_usd": 500_000_000, "term": "5 años"},
        "timing": "2027-2031",
    }
    base.update(overrides)
    return ValueDriverItem(**base)


svc = ValueDriverService()


# ------------------------------------------------------------------ validación
def test_valido_no_tiene_problemas() -> None:
    assert svc.validate(_item()) == []


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"source_url": None}, "URL"),
        ({"source_url": "ftp://x"}, "URL de fuente inválida"),
        ({"source_quote": "  "}, "cita"),
        ({"category": "inventada"}, "categoría"),
        ({"status": "casi_firmado"}, "estado"),
        ({"source_type": "blog"}, "tipo de fuente"),
        ({"treatment": "magia"}, "tratamiento"),
        ({"treatment": "en_modelo"}, "model_link"),
        ({"treatment": "no_valorado"}, "motivo"),
        ({"driver_key": "Con Espacios"}, "driver_key"),
        ({"name": ""}, "nombre"),
        ({"confidence": 1.5}, "confidence"),
        ({"economics": {"amount_usd": "mucho"}}, "economics.amount_usd"),
    ],
)
def test_validacion_fail_closed(overrides, fragment) -> None:
    problems = svc.validate(_item(**overrides))
    assert any(fragment in p for p in problems), problems


def test_upsert_invalido_no_escribe(db) -> None:
    company = _company(db)
    with pytest.raises(ValueDriverError):
        svc.upsert(db, company=company, tenant_id=T1, item=_item(source_url=None))
    assert db.query(ValueDriver).count() == 0


def test_upsert_many_es_todo_o_nada(db) -> None:
    company = _company(db)
    good = _item(driver_key="mercado_pais_x", category="geografia")
    bad = _item(driver_key="patentes", category="activo", source_quote=None)
    with pytest.raises(ValueDriverError) as err:
        svc.upsert_many(db, company=company, tenant_id=T1, items=[good, bad])
    assert "patentes" in str(err.value)
    assert db.query(ValueDriver).count() == 0
    with pytest.raises(ValueDriverError, match="repetida"):
        svc.upsert_many(db, company=company, tenant_id=T1, items=[good, good])


# ------------------------------------------------------------------ rumores
@pytest.mark.parametrize("source_type", ["foro", "redes"])
def test_rumor_de_foro_o_redes_nunca_cuenta_como_firmado(source_type) -> None:
    item = normalize_item(_item(source_type=source_type, source_url="https://x.com/someone/status/1"))
    assert item.status == "rumor"
    assert item.evidence == "rumor"
    assert item.metadata["status_declarado"] == "firmado"
    # Material y sin tratar, pero rumor: no bloquea la publicación.
    assert publication_check([_item(source_type=source_type, headline=True)]).publishable


def test_rumor_guardado_como_rumor(db) -> None:
    company = _company(db)
    result = svc.upsert(
        db,
        company=company,
        tenant_id=T1,
        item=_item(source_type="redes", source_url="https://x.com/a/status/2"),
    )
    assert (result.row.status, result.row.evidence) == ("rumor", "rumor")


def test_oficial_con_prensa_baja_a_estimado() -> None:
    item = normalize_item(_item(source_type="prensa"))
    assert item.evidence == "estimado"
    assert item.status == "firmado"
    assert item.metadata["evidence_declarada"] == "oficial"


# ------------------------------------------------------------------ puerta de publicación
def test_firmado_material_sin_tratar_bloquea() -> None:
    check = publication_check([_item()], market_cap_usd=10_000_000_000)
    assert not check.publishable
    assert check.reason == BLOCK_REASON
    assert [b.driver_key for b in check.blocking] == ["contrato_socio_a"]
    assert check.as_dict()["blocking"][0]["why"] == "sin tratamiento"


@pytest.mark.parametrize(
    "overrides",
    [
        {"treatment": "en_modelo", "model_link": "revenue.partner_a"},
        {"treatment": "opcion"},
        {"treatment": "suelo"},
        {"treatment": "riesgo"},
        {"treatment": "no_valorado", "reason_if_not_valued": "sin cifras públicas del reparto"},
    ],
)
def test_firmado_material_tratado_no_bloquea(overrides) -> None:
    assert publication_check([_item(**overrides)], market_cap_usd=10_000_000_000).publishable


@pytest.mark.parametrize("status", ["loi_mou", "regulatorio_pendiente", "rumor"])
def test_no_firmado_no_bloquea(status) -> None:
    assert publication_check([_item(status=status)], market_cap_usd=10_000_000_000).publishable


def test_anunciado_oficial_cuenta_como_comprometido() -> None:
    assert not publication_check([_item(status="anunciado_oficial")], market_cap_usd=1e10).publishable


def test_materialidad_umbral_uno_por_ciento() -> None:
    small = _item(economics={"amount_usd": 50_000_000})  # 0,5 % de 10.000 M$
    big = _item(economics={"amount_usd": 100_000_000})  # 1 %
    assert not is_material(small, 10_000_000_000)
    assert is_material(big, 10_000_000_000)
    assert publication_check([small], market_cap_usd=10_000_000_000).publishable
    # Sin importe: solo es material si es el tema principal de un 8-K/nota.
    assert not is_material(_item(economics={}), 1e10)
    assert is_material(_item(economics={}, headline=True), 1e10)
    # Con importe y sin capitalización conocida: prudente, material.
    assert is_material(small, None)


def test_no_valorado_sin_motivo_de_una_fila_cruda_bloquea(db) -> None:
    company = _company(db)
    row = ValueDriver(
        tenant_id=T1,
        company_id=company.id,
        driver_key="k",
        category="contrato",
        name="n",
        status="firmado",
        economics={},
        source_type="filing",
        evidence="oficial",
        headline=True,
        treatment="no_valorado",
        metadata_={},
    )
    check = publication_check([row])
    assert not check.publishable
    assert check.blocking[0].why == "no valorado sin motivo"


# ------------------------------------------------------------------ almacén
def test_aislamiento_por_tenant(db) -> None:
    company = _company(db)
    svc.upsert(db, company=company, tenant_id=T1, item=_item())
    assert set(svc.current(db, company_id=company.id, tenant_id=T1)) == {"contrato_socio_a"}
    assert svc.current(db, company_id=company.id, tenant_id=T2) == {}
    assert svc.check_publication(db, company_id=company.id, tenant_id=T2).publishable
    assert not svc.check_publication(db, company_id=company.id, tenant_id=T1, market_cap_usd=1e10).publishable


@pytest.mark.parametrize("tenant", [0, None, "1", True])
def test_tenant_invalido_falla(db, tenant) -> None:
    company = _company(db)
    with pytest.raises(ValueDriverError):
        svc.upsert(db, company=company, tenant_id=tenant, item=_item())


def test_tenant_distinto_de_la_sesion_falla(db) -> None:
    company = _company(db)
    db.info["tenant_id"] = T2
    try:
        with pytest.raises(ValueDriverError, match="sesión"):
            svc.current(db, company_id=company.id, tenant_id=T1)
    finally:
        db.info.pop("tenant_id", None)


def test_idempotente_y_con_historico(db) -> None:
    company = _company(db)
    first = svc.upsert(db, company=company, tenant_id=T1, item=_item(confidence=Decimal("0.8")))
    again = svc.upsert(db, company=company, tenant_id=T1, item=_item(confidence=0.8))
    assert first.action == "created"
    assert (again.action, again.changed) == ("unchanged", False)
    assert db.query(ValueDriver).count() == 1

    changed = svc.upsert(
        db,
        company=company,
        tenant_id=T1,
        item=_item(economics={"amount_usd": 700_000_000}),
        now=datetime(2026, 11, 4, tzinfo=UTC),
    )
    assert changed.action == "replaced"
    history = svc.history(db, company_id=company.id, tenant_id=T1, driver_key="contrato_socio_a")
    assert len(history) == 2
    assert history[0].superseded_at is not None
    assert history[1].superseded_at is None
    assert len(svc.current(db, company_id=company.id, tenant_id=T1)) == 1


def test_reejecutar_el_recopilador_no_borra_el_tratamiento(db) -> None:
    company = _company(db)
    svc.upsert(
        db,
        company=company,
        tenant_id=T1,
        item=_item(treatment="en_modelo", model_link="revenue.partner_a", value_per_share_marginal=1.25),
    )
    rerun = svc.upsert(db, company=company, tenant_id=T1, item=_item())  # pendiente
    assert rerun.action == "unchanged"
    row = svc.current(db, company_id=company.id, tenant_id=T1)["contrato_socio_a"]
    assert (row.treatment, row.model_link) == ("en_modelo", "revenue.partner_a")
    assert svc.check_publication(db, company_id=company.id, tenant_id=T1, market_cap_usd=1e10).publishable


def test_retire_deja_historico(db) -> None:
    company = _company(db)
    svc.upsert(db, company=company, tenant_id=T1, item=_item())
    assert svc.retire(db, company_id=company.id, tenant_id=T1, driver_key="contrato_socio_a")
    assert svc.current(db, company_id=company.id, tenant_id=T1) == {}
    assert not svc.retire(db, company_id=company.id, tenant_id=T1, driver_key="contrato_socio_a")
    assert db.query(ValueDriver).count() == 1
