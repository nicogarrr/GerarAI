"""Bordes de ``filing_yoy_service``: parseo de periodos, bisiestos y tenant.

Lo que cada test demuestra:
- ``_end_and_suffix`` devuelve None ante fechas no ISO o imposibles (44-45).
- ``_anniversary`` cae al 28 de febrero cuando el aniversario de un 29 de
  febrero no existe en el ano destino (51-52).
- ``figures`` se salta hechos con periodo imparseable (88), hechos con
  sufijo ``FY`` cuando la comparacion es trimestral (93) y hechos fuera de
  ambas ventanas (actual y aniversario) (97->85); lo saltado no genera
  entrada alguna en la salida.
- ``comparison`` exige tenant en ``db.info`` (138).
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, FinancialFact, Tenant
from app.services.filing_yoy_service import (
    _anniversary,
    _end_and_suffix,
    comparison,
    figures,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(engine, expire_on_commit=False)() as session:
        tenant = Tenant(external_id="yoyb-one", name="One")
        company = Company(
            ticker="YOYB",
            name="YoyB",
            exchange="NASDAQ",
            currency="USD",
            company_type="holding",
            valuation_model="unassigned",
        )
        session.add_all([tenant, company])
        session.flush()
        session.info.update(tenant_id=tenant.id, company_id=company.id)
        yield session
    engine.dispose()


def fact(db, metric, value, period):
    db.add(
        FinancialFact(
            tenant_id=db.info["tenant_id"],
            company_id=db.info["company_id"],
            metric=metric,
            value=Decimal(value),
            period=period,
            source_type="SEC",
        )
    )
    db.flush()


def test_end_and_suffix_fecha_invalida_devuelve_none():
    assert _end_and_suffix("31/12/2024:FY") is None
    assert _end_and_suffix("2024-02-30:Q1") is None  # 30 de febrero no existe
    assert _end_and_suffix("2024-02-29:FY") == (date(2024, 2, 29), "FY")
    assert _end_and_suffix("2024-02-29") == (date(2024, 2, 29), "")


def test_anniversary_29_de_febrero_cae_al_28():
    assert _anniversary(date(2024, 2, 29), -1) == date(2023, 2, 28)
    assert _anniversary(date(2024, 2, 29), 1) == date(2025, 2, 28)
    # 2028 si es bisiesto: el aniversario exacto existe.
    assert _anniversary(date(2024, 2, 29), 4) == date(2028, 2, 29)
    assert _anniversary(date(2026, 9, 30), -1) == date(2025, 9, 30)


def test_figures_periodo_imparseable_se_salta(db):
    fact(db, "revenue", "100", "garbage")
    fact(db, "revenue", "100", "tampoco-es-fecha:FY")
    assert figures(db, db.info["company_id"], date(2026, 9, 30), "FY") == []


def test_figures_fy_no_se_mezcla_en_comparacion_trimestral(db):
    # Sufijo FY con comparacion sin sufijo (10-Q): nunca se mezcla con
    # cifras anuales; el hecho trimestral explicito si entra.
    fact(db, "revenue", "1000", "2026-09-30:FY")
    fact(db, "net_income", "42", "2026-09-30:Q3")
    out = figures(db, db.info["company_id"], date(2026, 9, 30), None)
    assert len(out) == 1
    item = out[0]
    assert item["metric"] == "net_income"
    assert item["current"]["value"] == "42.000000"  # Decimal guardado con 6 decimales
    assert item["current"]["period"] == "2026-09-30:Q3"
    assert item["previous"] is None
    assert item["label"] == "SIN_DATOS"
    assert item["change_pct"] is None
    assert item["highlight"] is False


def test_figures_fuera_de_ambas_ventanas_se_salta(db):
    # Ni la ventana actual (+-3 dias) ni la del aniversario (+-15 dias).
    fact(db, "revenue", "100", "2020-01-15:FY")
    assert figures(db, db.info["company_id"], date(2026, 9, 30), "FY") == []


def test_comparison_sin_tenant_exige_contexto():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(engine, expire_on_commit=False)() as session:
        with pytest.raises(ValueError, match="Tenant context required"):
            comparison(session, 1, "10-K", 1)
    engine.dispose()
