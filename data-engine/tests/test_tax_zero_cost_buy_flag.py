"""Compras a precio 0 (regalo / spin-off): se aceptan, pero se marcan para revisión.

Nico (29 oct 2026): seguir aceptándolas y marcarlas en el informe fiscal y en la
lista de operaciones como «Coste 0 (regalo / spin-off): revisar». Solo aviso:
el FIFO y los importes no cambian.
"""
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

from app.core.database import init_db
from app.services.tax_report_service import (
    ZERO_COST_REVIEW_LABEL,
    replay_tax_fifo,
    zero_cost_buys_for_review,
)
from main import app
from tests.auth_helpers import csrf_client

START, END = date(2025, 1, 1), date(2025, 12, 31)


def tx(i, action, price, day, qty=10):
    return SimpleNamespace(
        id=i, action=action, quantity=D(qty), price=D(price), fees=D(0),
        currency="EUR", trade_date=day, raw_payload={},
    )


def test_zero_cost_buys_listed_for_review_without_changing_fifo():
    events = {
        "SPIN": [tx(1, "buy", "0", date(2024, 5, 1)), tx(2, "sell", "12", date(2025, 6, 1))],
        "GIFT": [tx(3, "buy", "0", date(2025, 2, 1))],
        "OLD": [tx(4, "buy", "0", date(2023, 1, 1))],  # sin ventas en 2025: no aplica
        "PAID": [tx(5, "buy", "10", date(2025, 2, 1))],
    }
    rows = zero_cost_buys_for_review(events, START, END)
    assert [(r["ticker"], r["date"]) for r in rows] == [("SPIN", "2024-05-01"), ("GIFT", "2025-02-01")]
    assert all(r["label"] == "Coste 0 (regalo / spin-off): revisar" for r in rows)
    # Política intacta: el lote a coste 0 sigue entrando al FIFO con coste 0.
    _, sales = replay_tax_fifo(events["SPIN"], lambda c, d: D("1"), START, END)
    assert sales[0]["cost_native"] == D("0")


def test_transaction_list_flags_zero_price_buy():
    init_db()
    client = csrf_client(app)
    for ticker, price in (("ZEROGIFT", "0"), ("PAIDBUY", "10")):
        response = client.post(
            "/api/portfolio/transactions",
            json={"ticker": ticker, "action": "buy", "quantity": "5", "price": price,
                  "currency": "EUR", "trade_date": "2025-03-03"},
        )
        assert response.status_code == 201, response.text
    # GET /transactions pagina (20 por defecto): en la suite, con la BD
    # compartida llena de operaciones de otros tests, las filas de 2025-03-03
    # caian fuera de la pagina 1 y el assert veia {}. El endpoint ya ofrece
    # filtro por ticker: deterministico con cualquier volumen acumulado.
    flags = {}
    for ticker in ("ZEROGIFT", "PAIDBUY"):
        listed = client.get("/api/portfolio/transactions", params={"ticker": ticker}).json()
        rows = listed if isinstance(listed, list) else listed.get("items", listed.get("transactions", []))
        flags[ticker] = rows[0].get("review_flag") if rows else None
    assert flags == {"ZEROGIFT": ZERO_COST_REVIEW_LABEL, "PAIDBUY": None}
