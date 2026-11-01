"""CSV de IBKR: un importe que no cabe en la cartera es un error de fila, no un 500.

``validate_ibkr_csv`` solo miraba que cantidad y precio fueran números. Un precio
de 15 cifras («999999999999999»), una cantidad igual o una comisión de 1e19
pasaban y ``import_ibkr_csv`` los guardaba: en SQLite queda una posición de
10^16, en Postgres el INSERT en Numeric(20, 6)/(20, 2) revienta (500) y se pierde
el fichero entero. Una comisión que no es un número tampoco se revisaba.
Los topes son los de POST /transactions (#2606).
"""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, Transaction
from app.services.ibkr_import_service import IBKRImportService, validate_ibkr_csv

H = "Symbol,Buy/Sell,Quantity,TradePrice,TradeDate,IBCommission,CurrencyPrimary\n"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.mark.parametrize(
    ("row", "word"),
    [
        ("AAPL,BUY,10,999999999999999,2024-03-15,-1,USD", "precio"),
        ("AAPL,BUY,999999999999999,10,2024-03-15,-1,USD", "cantidad"),
        ("AAPL,BUY,10,10,2024-03-15,-10000000000000000000,USD", "comisión"),
        ("AAPL,BUY,10,10,2024-03-15,abc,USD", "comisión"),
    ],
)
def test_importe_fuera_de_rango_es_error_de_fila(row, word):
    errors = validate_ibkr_csv(H + row + "\n")
    assert len(errors) == 1, errors
    assert errors[0].startswith("Fila 2 del CSV (AAPL)")
    assert word in errors[0]


def test_la_fila_que_no_cabe_se_omite_y_el_resto_entra(db: Session):
    csv_text = (
        H
        + "ZZIB1,BUY,10,999999999999999,2024-03-15,-1,USD\n"
        + "ZZIB2,BUY,10,12.5,2024-03-15,-1,USD\n"
    )
    result = IBKRImportService().import_ibkr_csv(db, csv_text)
    assert result["trades_imported"] == 1
    assert any(error.startswith("Fila 2 del CSV (ZZIB1)") for error in result["row_errors"])
    prices = [tx.price for tx in db.scalars(select(Transaction)).all()]
    assert [float(p) for p in prices] == [12.5]


def test_importes_grandes_pero_validos_siguen_valiendo():
    csv_text = H + "AAPL,BUY,1000000,99999.123456,2024-03-15,-12.5,USD\n"
    assert validate_ibkr_csv(csv_text) == []
