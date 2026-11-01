"""Tickers: misma forma en la operación manual, el alta de ficha y la importación genérica.

#4067 dejó la watchlist en «letras/cifras separadas por un solo . o -», pero
el resto de puertas seguía aceptando «.», «-», «A..B» o «AAPL.»:

- ``POST /api/portfolio/transactions`` y ``POST /api/companies/ensure`` creaban
  una ficha y una posición con ese «ticker»;
- la vista previa de la importación genérica lo daba por válido;
- y el commit de la importación (que recibe las filas del cliente) no miraba
  el ticker en absoluto: uno de 25 caracteres o con salto de línea llegaba a
  ``Company.ticker`` (String(20)) y en Postgres el commit entero daba 500.
"""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import main
from app.core import auth as auth_module
from app.core.database import init_db
from app.services.transaction_import_service import (
    ParsedTransaction,
    TransactionImportCommitRequest,
    TransactionImportService,
)
from tests.auth_helpers import auth_settings, signed_request

SECRET = "ticker-shape-secret"
BAD = [".", "-", "..", "A..B", "-AAPL", "AAPL.", "A.-B"]
GOOD = ["AAPL", "brk.b", "BF-B", "0700.HK", "7203.T"]


@pytest.fixture()
def call(monkeypatch):
    init_db()
    monkeypatch.setattr(
        auth_module, "get_settings", lambda: auth_settings(strict=True, secret=SECRET, app_env="test")
    )
    suffix = uuid4().hex[:8]
    client = TestClient(main.app, raise_server_exceptions=False)

    def _call(method, path, json_body=None):
        return signed_request(client, SECRET, f"ts-{suffix}", f"user-ts-{suffix}", method, path, json_body=json_body)

    return _call


def _trade(ticker: str) -> dict:
    return {"ticker": ticker, "action": "buy", "quantity": 1, "price": 10, "currency": "USD", "trade_date": "2026-01-05"}


@pytest.mark.parametrize("ticker", BAD)
def test_operacion_manual_rechaza_ticker_sin_forma(call, ticker):
    assert call("POST", "/api/portfolio/transactions", _trade(ticker)).status_code == 422


@pytest.mark.parametrize("ticker", GOOD)
def test_operacion_manual_acepta_tickers_reales(call, ticker):
    response = call("POST", "/api/portfolio/transactions", _trade(ticker))
    assert response.status_code == 201, response.text


@pytest.mark.parametrize("ticker", BAD)
def test_alta_de_ficha_rechaza_ticker_sin_forma(call, ticker):
    assert call("POST", "/api/companies/ensure", {"ticker": ticker}).status_code == 422


def _preview(tickers: list[str]):
    csv = "ticker,date,action,quantity,price\n" + "".join(f"{t},2026-01-05,buy,1,10\n" for t in tickers)
    return TransactionImportService().preview_import(csv.encode(), "x.csv")


def test_vista_previa_rechaza_ticker_sin_forma():
    result = _preview([*BAD, "ABC_D", "BRK.B"])
    bad_rows = {e.row_number for e in result.errors if e.field == "ticker"}
    assert len(bad_rows) == len(BAD), result.errors
    assert sorted(item.ticker for item in result.preview_items) == ["ABC_D", "BRK.B"]


def _row(ticker: str) -> ParsedTransaction:
    return ParsedTransaction(row_number=2, ticker=ticker, date="2026-01-05", action="buy", quantity=1, price=10, currency="USD")


@pytest.mark.parametrize("ticker", [*BAD, "A" * 25, "MS\nFT", "AB\x00", ""])
def test_commit_rechaza_ticker_imposible(ticker):
    with pytest.raises(ValidationError, match="ticker"):
        TransactionImportCommitRequest(transactions=[_row(ticker)])


@pytest.mark.parametrize("ticker", ["AAPL", "brk.b", "ABC_D", "US0378331005"])
def test_commit_acepta_tickers_e_isin(ticker):
    assert TransactionImportCommitRequest(transactions=[_row(ticker)]).transactions[0].ticker == ticker


# El commit tampoco repetía las reglas de fecha de la vista previa ni el tope
# de notas de POST /transactions (2000): «1800-01-01» entraba como compra de
# hace dos siglos y 100.000 caracteres de nota por fila iban al libro.
@pytest.mark.parametrize("day", ["1800-01-01", "0201-03-15"])
def test_commit_rechaza_anio_imposible(day):
    with pytest.raises(ValidationError, match="revisa el año"):
        TransactionImportCommitRequest(transactions=[_row("AAPL").model_copy(update={"date": day})])


def test_commit_rechaza_nota_desmesurada():
    with pytest.raises(ValidationError):
        ParsedTransaction(row_number=2, ticker="AAPL", date="2026-01-05", action="buy", quantity=1, price=10, notes="x" * 2001)
    assert ParsedTransaction(row_number=2, ticker="AAPL", date="2026-01-05", action="buy", quantity=1, price=10, notes="x" * 2000)
