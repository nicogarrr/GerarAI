"""Chat: un ticker escrito sin el sufijo de su bolsa («SAN») encuentra el
listado guardado con sufijo («SAN.MC») cuando es el único con esa base.

Antes «¿cuántas acciones tengo de SAN?» con SAN.MC en cartera contestaba
«No tengo «SAN» entre las empresas de GerarAI…», aunque el resolvedor ya
hacía el camino contrario (SAN.MC → SAN). Si hay dos listados con la misma
base (SAN.MC y SAN.PA) no se adivina, y un ticker exacto sigue mandando.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.models.entities import Company, Position
from tests.test_chat_account_year import _ask, _db, _today  # noqa: F401


def _add(db, ticker, *, held=False):
    c = Company(ticker=ticker, name=f"Empresa {ticker}", exchange="BME", company_type="bank",
                valuation_model="unassigned", currency="EUR")
    db.add(c)
    db.flush()
    if held:
        db.add(Position(tenant_id=1, company_id=c.id, quantity=Decimal(1000), average_cost=Decimal(3),
                        market_value=Decimal(3000), market_value_native=Decimal(3000),
                        market_value_base=Decimal(3000), cost_basis_native=Decimal(3000),
                        cost_basis_base=Decimal(3000), currency="EUR", base_currency="EUR",
                        as_of=date(2026, 10, 30)))
    db.commit()
    return c


@pytest.mark.parametrize("question", [
    "¿cuántas acciones tengo de SAN?",
    "¿cómo va mi posición en SAN?",
])
def test_base_sin_sufijo_encuentra_el_listado_unico(question):
    db = _db()
    _add(db, "SAN.MC", held=True)
    resp = _ask(db, question)
    assert resp.llm_trace["path"] == "portfolio_position"
    assert "SAN.MC" in resp.answer
    assert "No tengo" not in resp.answer


def test_dos_listados_con_la_misma_base_no_se_adivina():
    db = _db()
    _add(db, "SAN.MC", held=True)
    _add(db, "SAN.PA")
    resp = _ask(db, "¿cuántas acciones tengo de SAN?")
    assert resp.llm_trace["path"] != "portfolio_position"


def test_ticker_exacto_sigue_mandando():
    db = _db()
    _add(db, "SAN.MC", held=True)
    _add(db, "SAN")
    resp = _ask(db, "¿cuántas acciones tengo de SAN?")
    assert resp.llm_trace["path"] == "portfolio_position"
    assert "SAN.MC" not in resp.answer
    assert "posición guardada en SAN" in resp.answer


def test_minusculas_no_cuentan():
    db = _db()
    _add(db, "SAN.MC", held=True)
    resp = _ask(db, "¿cuántas acciones tengo de san?")
    assert "SAN.MC" not in resp.answer
