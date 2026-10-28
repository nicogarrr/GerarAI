"""720, cuentas: un saldo 0 a 31/12 con saldo medio del 4T distinto de 0 nunca se omite en silencio.

Antes, si la divisa no tenía custodia declarada (o no tenía tipo de cambio),
``check_thresholds`` la saltaba sin dejar rastro: no sumaba al saldo medio ni
aparecía en ``foreign_unverified`` / ``unvalued``, y la categoría podía salir
«por_debajo» (falso verde). Con saldo distinto de 0 la misma cuenta sí se lista
«fuera del total». Ahora recibe el mismo trato y la categoría no es concluyente.
No cambia ningún umbral: el saldo medio de una cuenta sin ubicación declarada no
se suma (igual que su saldo a 31/12 cuando no es 0).
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.services.tax_modelo720_service import Modelo720Service
from tests.test_mutation_gaps_modelo720_cash import YEAR_END, _snap
from tests.test_tax_modelo720_q4 import _seed, _weekly


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _seed_cash(db, *, custody, accounts):
    """accounts: divisa -> (saldo semanal 4T, saldo a 31/12, tipo EUR o None)."""
    tenant, portfolio = _seed(db)
    tenant.metadata_ = {"tax_declarant": {"custody": custody}}
    for day in _weekly(date(2025, 10, 1), date(2025, 12, 24)):
        for currency, (weekly, _end, fx) in accounts.items():
            _snap(db, tenant, portfolio, day, currency, weekly, fx)
    for currency, (_weekly_balance, end, fx) in accounts.items():
        _snap(db, tenant, portfolio, YEAR_END, currency, end, fx)
    return tenant, portfolio


def test_saldo_cero_sin_custodia_con_saldo_medio_se_lista_para_revisar(db):
    # Dólares vaciados en diciembre, sin 'cash:USD' en la custodia; la libra
    # (declarada en GB) es pequeña. Antes: 'por_debajo' sin rastro del USD.
    _seed_cash(db, custody={"cash:GBP": "GB"}, accounts={
        "USD": (60000, 0, "0.90"),
        "GBP": (10000, 10000, "1.15"),
    })
    result = Modelo720Service().check_thresholds(db, 2025)
    cuentas = result["categories"]["cuentas"]

    flagged = [row for row in result["foreign_unverified"] if row["ticker"] == "cash-USD"]
    assert len(flagged) == 1
    assert flagged[0]["snapshot_date"] == "2025-12-31"
    reason = flagged[0]["reason"]
    assert "saldo medio" in reason.lower()
    assert "'cash:USD'" in reason
    assert "fuera del total" in reason
    # Importe orientativo del saldo medio (no suma al total).
    assert flagged[0]["average_q4_base"] == pytest.approx(53413.04, abs=0.01)

    # Sin ubicación declarada no suma (mismo trato que un saldo ≠ 0 sin custodia).
    assert cuentas["total_base"] == 11500.0
    assert cuentas["average_q4_total_base"] == 11500.0
    # Y nunca un falso verde.
    assert cuentas["status"] == "desconocido"
    assert cuentas["exceeds"] is None
    assert result["incomplete"] is True


def test_saldo_cero_sin_tipo_de_cambio_con_saldo_medio_queda_sin_valorar(db):
    _seed_cash(db, custody={"cash:USD": "IE", "cash:GBP": "GB"}, accounts={
        "USD": (60000, 0, None),
        "GBP": (10000, 10000, "1.15"),
    })
    result = Modelo720Service().check_thresholds(db, 2025)
    flagged = [row for row in result["unvalued"] if row["ticker"] == "cash-USD"]
    assert len(flagged) == 1
    assert flagged[0]["snapshot_date"] == "2025-12-31"
    assert "saldo medio" in flagged[0]["reason"].lower()
    assert "valorar a mano" in flagged[0]["reason"]
    cuentas = result["categories"]["cuentas"]
    assert cuentas["status"] == "desconocido"
    assert result["incomplete"] is True


def test_saldo_cero_todo_el_trimestre_no_genera_avisos(db):
    # Una divisa a 0 todo el 4T no es una cuenta que revisar: sin ruido.
    _seed_cash(db, custody={"cash:GBP": "GB"}, accounts={
        "USD": (0, 0, "0.90"),
        "GBP": (10000, 10000, "1.15"),
    })
    result = Modelo720Service().check_thresholds(db, 2025)
    assert result["foreign_unverified"] == []
    assert result["unvalued"] == []
    cuentas = result["categories"]["cuentas"]
    assert cuentas["status"] == "por_debajo"
    assert cuentas["average_q4_total_base"] == 11500.0


def test_saldo_cero_con_custodia_extranjera_sigue_sumando_saldo_medio(db):
    # Comportamiento previo que se mantiene: con custodia extranjera declarada
    # el saldo medio del 4T de la cuenta vaciada suma y la categoría lo refleja.
    _seed_cash(db, custody={"cash:USD": "IE", "cash:GBP": "GB"}, accounts={
        "USD": (60000, 0, "0.90"),
        "GBP": (10000, 10000, "1.15"),
    })
    result = Modelo720Service().check_thresholds(db, 2025)
    cuentas = result["categories"]["cuentas"]
    assert result["foreign_unverified"] == []
    assert cuentas["average_q4_total_base"] == 64913.04
