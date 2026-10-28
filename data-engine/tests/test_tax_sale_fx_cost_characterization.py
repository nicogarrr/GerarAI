"""Caracterización: coste en euros de las ventas y bookkeeping del diferido (regla 2 meses).

Fija las cifras ACTUALES de ``compute_report``, ``replay_tax_fifo`` y
``simulate_fifo_sale`` en escenarios en dólares con un tipo de cambio distinto
en cada fecha (compra, venta con pérdida, recompra, venta posterior), para que
la limpieza del cálculo muerto del coste en base lote a lote (sobrescrito por
el criterio DGT: coste nativo × cambio de la venta) no cambie ningún número.

Lo que se fija:
- informe anual: coste, ingreso y resultado en euros de cada venta, pérdida
  bloqueada en divisa y en euros;
- lotes que quedan tras el replay: diferido nativo y ``deferred_base`` (la
  pérdida diferida al cambio de SU venta) consumidos a prorrata al vender
  parte del lote;
- simulador del Cerebro: ``unit_eur`` = coste unitario al cambio de compra +
  diferido en euros por acción del lote restante.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, FXRate, Portfolio, Transaction
from app.services.sale_simulation import simulate_fifo_sale
from app.services.tax_report_service import TaxReportService, replay_tax_fifo

# Tipo EUR por dólar en cada fecha usada (todas distintas a propósito).
RATES = {
    "2025-07-01": "0.80",  # compra inicial
    "2025-08-01": "0.90",  # venta con pérdida
    "2025-08-10": "0.85",  # recompra que bloquea la pérdida
    "2026-01-15": "0.95",  # venta parcial del lote con diferido
    "2026-03-02": "0.92",  # venta con pérdida de un lote con diferido
    "2026-03-20": "0.88",  # otra venta parcial / recompra
}
SIM_DATE = date(2026, 10, 27)

BASE = [
    ("2025-07-01", "buy", "100", "10"),
    ("2025-08-01", "sell", "100", "8"),
    ("2025-08-10", "buy", "100", "8"),
]
PARTIAL = BASE + [("2026-01-15", "sell", "40", "11")]
TWO_PARTIALS = PARTIAL + [("2026-03-20", "sell", "20", "9")]
CHAIN = BASE + [("2026-03-02", "sell", "100", "7"), ("2026-03-20", "buy", "100", "7")]


def _resolve(currency, as_of):
    if currency == "EUR":
        return D(1)
    rate = RATES.get(as_of.isoformat())
    return None if rate is None else D(rate)


def _events(trades):
    return [
        SimpleNamespace(
            id=i, action=action, quantity=D(qty), price=D(price), fees=D("0"),
            currency="USD", trade_date=date.fromisoformat(day), raw_payload={},
        )
        for i, (day, action, qty, price) in enumerate(trades, start=1)
    ]


@pytest.fixture()
def ledger():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.info["tenant_id"] = 1
        company = Company(ticker="USDCO", name="Synthetic USD", exchange="NASDAQ", currency="USD",
                          company_type="holding", valuation_model="unassigned")
        db.add(company)
        db.flush()
        db.add(Portfolio(tenant_id=1, name="P", base_currency="EUR", is_default=True))
        for day, rate in RATES.items():
            db.add(FXRate(base_currency="EUR", quote_currency="USD",
                          rate_date=date.fromisoformat(day), rate=D(rate), source="ECB"))
        db.commit()
        yield db, company
    engine.dispose()


def _load(db, company, trades):
    for day, action, qty, price in trades:
        db.add(Transaction(tenant_id=1, company_id=company.id, trade_date=date.fromisoformat(day),
                           action=action, quantity=D(qty), price=D(price), fees=D("0"), currency="USD"))
    db.commit()


NUMERIC = ("quantity", "proceeds_native", "cost_native", "proceeds_base", "cost_base",
           "gain_native", "gain_base", "raw_gain_native", "blocked_loss_native", "blocked_loss_base")


def _sales(db, year):
    report = TaxReportService().compute_report(db, year, include_filing=False)
    (bucket,) = report["realized"]
    return [
        {"date": sale["date"], **{key: sale[key] for key in NUMERIC}}
        for sale in bucket["sales"]
    ], report["summary"]


# --- Informe anual (compute_report) -------------------------------------------------


def test_informe_venta_bloqueada_y_venta_parcial_del_lote_con_diferido(ledger):
    db, company = ledger
    _load(db, company, PARTIAL)
    sales_2025, summary_2025 = _sales(db, 2025)
    assert sales_2025 == [{
        "date": "2025-08-01", "quantity": 100.0,
        "proceeds_native": 800.0, "cost_native": 1000.0,
        # Criterio DGT: todo al cambio de la venta (0,90), no la compra a 0,80.
        "proceeds_base": 720.0, "cost_base": 900.0,
        "gain_native": 0.0, "gain_base": 0.0, "raw_gain_native": -200.0,
        "blocked_loss_native": 200.0, "blocked_loss_base": 180.0,
    }]
    assert summary_2025["total_blocked_loss_base"] == 180.0
    assert summary_2025["total_realized_gain_base"] == 0.0

    sales_2026, summary_2026 = _sales(db, 2026)
    assert sales_2026 == [{
        "date": "2026-01-15", "quantity": 40.0,
        # 40 × 8 $ + 40/100 del diferido de 200 $ = 400 $, × 0,95.
        "proceeds_native": 440.0, "cost_native": 400.0,
        "proceeds_base": 418.0, "cost_base": 380.0,
        "gain_native": 40.0, "gain_base": 38.0, "raw_gain_native": 40.0,
        "blocked_loss_native": 0.0, "blocked_loss_base": 0.0,
    }]
    assert summary_2026["total_realized_gain_base"] == 38.0
    assert summary_2026["net_taxable_base"] == 38.0


def test_informe_dos_ventas_parciales_consumen_el_diferido_a_prorrata(ledger):
    db, company = ledger
    _load(db, company, TWO_PARTIALS)
    sales, _summary = _sales(db, 2026)
    assert sales[1] == {
        "date": "2026-03-20", "quantity": 20.0,
        # 20 × 8 $ + 20/60 del diferido restante de 120 $ = 200 $, × 0,88.
        "proceeds_native": 180.0, "cost_native": 200.0,
        "proceeds_base": 158.4, "cost_base": 176.0,
        "gain_native": -20.0, "gain_base": -17.6, "raw_gain_native": -20.0,
        "blocked_loss_native": 0.0, "blocked_loss_base": 0.0,
    }


def test_informe_perdida_encadenada_de_un_lote_que_ya_arrastra_diferido(ledger):
    db, company = ledger
    _load(db, company, CHAIN)
    sales, summary = _sales(db, 2026)
    assert sales == [{
        "date": "2026-03-02", "quantity": 100.0,
        # 800 $ + 200 $ diferidos = 1.000 $, × 0,92; la pérdida de 300 $ se
        # bloquea por la recompra del 20/03 (ventana posterior).
        "proceeds_native": 700.0, "cost_native": 1000.0,
        "proceeds_base": 644.0, "cost_base": 920.0,
        "gain_native": 0.0, "gain_base": 0.0, "raw_gain_native": -300.0,
        "blocked_loss_native": 300.0, "blocked_loss_base": 276.0,
    }]
    assert summary["total_blocked_loss_base"] == 276.0


# --- Lotes restantes del replay (diferido nativo y en euros) -------------------------


def _lot_state(lots):
    return [
        {key: lot[key] for key in ("qty", "unit", "unit_base", "deferred", "deferred_base", "capacity")}
        for lot in lots
    ]


def test_replay_lote_restante_tras_venta_parcial():
    lots, _sales_ = replay_tax_fifo(_events(PARTIAL), _resolve, date(2025, 1, 1), date(2026, 12, 31))
    assert _lot_state(lots) == [{
        "qty": D("60"), "unit": D("8"), "unit_base": D("6.80"),
        # Quedan 60/100 del diferido: 120 $ y 108 € (180 € al cambio de la
        # venta con pérdida, consumido a prorrata, NO recalculado).
        "deferred": D("120"), "deferred_base": D("108"),
        "capacity": D("0"),
    }]


def test_replay_lote_restante_tras_dos_ventas_parciales():
    lots, _sales_ = replay_tax_fifo(_events(TWO_PARTIALS), _resolve, date(2025, 1, 1), date(2026, 12, 31))
    assert _lot_state(lots) == [{
        "qty": D("40"), "unit": D("8"), "unit_base": D("6.80"),
        "deferred": D("80"), "deferred_base": D("72"), "capacity": D("0"),
    }]


def test_replay_diferido_encadenado_al_cambio_de_su_venta():
    lots, _sales_ = replay_tax_fifo(_events(CHAIN), _resolve, date(2025, 1, 1), date(2026, 12, 31))
    assert _lot_state(lots) == [{
        "qty": D("100"), "unit": D("7"), "unit_base": D("6.16"),
        # 300 $ de pérdida, en euros 300 × 0,92 = 276 (cambio de la venta).
        "deferred": D("300"), "deferred_base": D("276"), "capacity": D("0"),
    }]


def test_replay_lote_sin_tipo_de_compra_mantiene_diferido_en_base_desconocido():
    # La recompra del 12/08 no tiene tipo publicado: su coste y su diferido en
    # euros son desconocidos (None) antes y después de vender parte del lote.
    trades = [
        ("2025-07-01", "buy", "100", "10"),
        ("2025-08-01", "sell", "100", "8"),
        ("2025-08-12", "buy", "100", "8"),
        ("2026-01-15", "sell", "40", "11"),
    ]
    lots, sales = replay_tax_fifo(_events(trades), _resolve, date(2026, 1, 1), date(2026, 12, 31))
    assert _lot_state(lots) == [{
        "qty": D("60"), "unit": D("8"), "unit_base": None,
        "deferred": D("120"), "deferred_base": None, "capacity": D("0"),
    }]
    (sale,) = sales
    # El coste en euros de la venta sigue siendo conocido: nativo × cambio de venta.
    assert sale["cost_native"] == D("400")
    assert sale["cost_base"] == D("380.00")
    assert sale["proceeds_base"] == D("418.00")
    assert sale["cost_unknown"] is False


def test_replay_venta_que_cruza_lotes_con_y_sin_diferido():
    trades = BASE + [("2026-01-15", "buy", "50", "12"), ("2026-03-20", "sell", "120", "9")]
    lots, sales = replay_tax_fifo(_events(trades), _resolve, date(2026, 1, 1), date(2026, 12, 31))
    (sale,) = sales
    # 100 × 8 $ + 200 $ diferidos + 20 × 12 $ = 1.240 $, × 0,88.
    assert sale["cost_native"] == D("1240")
    assert sale["cost_base"] == D("1091.20")
    assert sale["proceeds_base"] == D("950.40")
    assert sale["gain_base_raw"] == D("-140.80")
    assert _lot_state(lots) == [{
        "qty": D("30"), "unit": D("12"), "unit_base": D("11.40"),
        "deferred": D("0"), "deferred_base": D("0"), "capacity": D("50"),
    }]


# --- Simulador del Cerebro (simulate_fifo_sale) --------------------------------------


@pytest.mark.parametrize(("trades", "quantity", "held", "lot_date", "unit_eur", "cost_eur"), [
    # 6,80 € (8 $ × 0,85) + 108 € / 60 de diferido = 8,60 €.
    (PARTIAL, "60", "60", "2025-08-10", "8.60", "516"),
    (PARTIAL, "30", "60", "2025-08-10", "8.60", "258"),
    (TWO_PARTIALS, "40", "40", "2025-08-10", "8.60", "344"),
    # 6,16 € (7 $ × 0,88) + 276 € / 100 = 8,92 €.
    (CHAIN, "100", "100", "2026-03-20", "8.92", "892"),
])
def test_simulador_coste_eur_incluye_el_diferido_restante(ledger, trades, quantity, held, lot_date, unit_eur, cost_eur):
    db, company = ledger
    _load(db, company, trades)
    sale = simulate_fifo_sale(db, tenant_id=1, company_id=company.id,
                              quantity=D(quantity), held_quantity=D(held), sale_date=SIM_DATE)
    assert sale is not None
    assert [(lot.trade_date.isoformat(), lot.quantity) for lot in sale.lots] == [(lot_date, D(quantity))]
    assert sale.lots[0].unit_cost_eur == D(unit_eur)
    assert sale.cost_eur == D(cost_eur)
    assert sale.blocking_qty == 0
