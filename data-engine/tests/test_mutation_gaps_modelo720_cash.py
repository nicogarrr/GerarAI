"""Supervivientes de mutmut en ``tax_modelo720_service`` (ronda 2): saldos en cuenta.

El tramo de cuentas de ``check_thresholds`` tenia caminos sin ningun test:
un saldo 0 a 31/12 cuyo saldo medio del 4T si cuenta, una cuenta declarada en
Espana, un saldo sin tipo de cambio y una divisa sin custodia declarada.
Solo se fijan los comportamientos actuales; ninguna regla fiscal cambia.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import CashDailySnapshot, PortfolioDailySnapshot
from app.services.tax_modelo720_service import Modelo720Service
from tests.test_tax_modelo720_q4 import _seed, _weekly

YEAR_END = date(2025, 12, 31)


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _snap(db, tenant, portfolio, day, currency, balance, fx):
    parent = db.query(PortfolioDailySnapshot).filter_by(
        portfolio_id=portfolio.id, snapshot_date=day,
    ).one_or_none()
    if parent is None:
        parent = PortfolioDailySnapshot(
            tenant_id=tenant.id, portfolio_id=portfolio.id, snapshot_date=day,
            base_currency="EUR", positions_value_base=Decimal("0"),
            cash_value_base=Decimal("0"), total_value_base=Decimal("0"),
            metadata_={"missing_pricing": []},
        )
        db.add(parent)
        db.flush()
    db.add(CashDailySnapshot(
        tenant_id=tenant.id, portfolio_snapshot_id=parent.id, portfolio_id=portfolio.id,
        snapshot_date=day, currency=currency, balance_native=Decimal(str(balance)),
        fx_rate=None if fx is None else Decimal(fx),
    ))
    db.flush()


ACCOUNTS = {
    # divisa: (saldo semanal del 4T, saldo a 31/12, tipo EUR)
    "USD": (60000, 0, "0.90"),      # vaciada antes del 31/12 (custodia IE)
    "GBP": (10000, 10000, "1.15"),  # cuenta normal (custodia GB)
    "CHF": (5000, 10000, "1.05"),   # declarada en Espana
    "JPY": (100, 10000, None),      # sin tipo de cambio
    "NOK": (1000, 10000, "0.09"),   # sin custodia declarada
}


def _seed_accounts(db, custody=None):
    tenant, portfolio = _seed(db)
    tenant.metadata_ = {"tax_declarant": {"custody": custody or {
        "cash:USD": "IE", "cash:GBP": "GB", "cash:CHF": "ES",
    }}}
    for day in _weekly(date(2025, 10, 1), date(2025, 12, 24)):
        for currency, (weekly, _end, fx) in ACCOUNTS.items():
            _snap(db, tenant, portfolio, day, currency, weekly, fx)
    for currency, (_weekly_balance, end, fx) in ACCOUNTS.items():
        _snap(db, tenant, portfolio, YEAR_END, currency, end, fx)
    return tenant, portfolio


def test_cuentas_cada_saldo_va_a_su_sitio(db):
    _seed_accounts(db)
    result = Modelo720Service().check_thresholds(db, 2025)
    cuentas = result["categories"]["cuentas"]
    # A 31/12 solo computa la libra: 10.000 x 1,15.
    assert cuentas["total_base"] == 11500.0
    assert [b["currency"] for b in cuentas["balances"]] == ["GBP"]
    assert cuentas["balances"][0]["value_base"] == 11500.0
    assert cuentas["balances"][0]["custody_country"] == "GB"
    assert cuentas["balances"][0]["snapshot_date"] == "2025-12-31"
    # El saldo medio del 4T SUMA la cuenta de dolares vaciada en diciembre
    # (la libra 11.500 + los dolares ~53.413): por eso supera aunque el 31/12 no.
    assert cuentas["average_q4_total_base"] == 64913.04
    assert cuentas["average_q4_missing"] is False
    assert any("cash-USD" in reason for reason in cuentas["reasons"])
    # Espana: no es bien en el extranjero, se lista aparte y no computa.
    assert result["domestic_assets"] == [{
        "ticker": "cash-CHF", "value_base": 10500.0,
        "reason": "Cuenta declarada en España: no es bien en el extranjero; no computa en el 720.",
    }]
    # Sin tipo de cambio: fuera del total y sin valorar.
    assert result["unvalued"] == [{
        "ticker": "cash-JPY", "snapshot_date": "2025-12-31",
        "reason": "Sin tipo de cambio para el saldo: fuera del total EUR, valorar a mano.",
    }]
    # Sin custodia declarada: fuera del total, con la clave que hay que declarar.
    assert [row["ticker"] for row in result["foreign_unverified"]] == ["cash-NOK"]
    assert result["foreign_unverified"][0]["snapshot_date"] == "2025-12-31"
    assert "'cash:NOK'" in result["foreign_unverified"][0]["reason"]
    assert "fuera del total" in result["foreign_unverified"][0]["reason"]
    assert result["incomplete"] is True


def test_saldo_cero_en_espana_o_sin_tipo_no_suma_saldo_medio(db):
    # Los dolares vaciados, pero declarados en Espana: su saldo medio no computa.
    _seed_accounts(db, custody={"cash:USD": "ES", "cash:GBP": "GB", "cash:CHF": "ES"})
    cuentas = Modelo720Service().check_thresholds(db, 2025)["categories"]["cuentas"]
    assert cuentas["average_q4_total_base"] == 11500.0
    assert not any("cash-USD" in reason for reason in cuentas["reasons"])


def test_sin_portfolio_todo_desconocido_con_estructura_completa(db):
    from app.services.tax_modelo720_service import _inmuebles

    result = Modelo720Service().check_thresholds(db, 2025)
    reason = "Sin portfolio activo: no hay snapshots que evaluar."
    unknown = {"exceeds": None, "status": "desconocido", "total_base": None,
               "snapshot_lag_days": None, "reasons": [reason], "custody": "por_partida"}
    assert result["categories"] == {
        "valores": {**unknown, "positions": [], "missing_isin": []},
        "cuentas": {**unknown, "balances": [], "average_q4_missing": True},
        "inmuebles": _inmuebles(),
    }
    for key, value in {
        "fiscal_year": 2025, "threshold_base": 50000.0, "base_currency": None,
        "custody_country": None, "unvalued": [], "foreign_unverified": [],
        "short_positions": [], "stale_snapshots": [], "domestic_assets": [],
    }.items():
        assert result[key] == value, key
    assert result["incomplete"] in (True, False)
    assert result["notas"]


def test_custodia_declarada_solo_codigos_iso2_de_texto(db):
    from app.services.tax_modelo720_service import _declared_custody_map

    tenant, _portfolio = _seed(db)
    tenant.metadata_ = {"tax_declarant": {"custody": {
        "us0378331005": " ie ", "cash:usd": "us", "num": 12, "largo": "ESP", "none": None,
    }}}
    db.flush()
    assert _declared_custody_map(db, tenant.id) == {"US0378331005": "IE", "CASH:USD": "US"}
    assert _declared_custody_map(db, None) == {}
    assert _declared_custody_map(db, tenant.id + 999) == {}
    tenant.metadata_ = {"tax_declarant": {"custody": ["IE"]}}
    db.flush()
    assert _declared_custody_map(db, tenant.id) == {}
    tenant.metadata_ = {"tax_declarant": "IE"}
    db.flush()
    assert _declared_custody_map(db, tenant.id) == {}
