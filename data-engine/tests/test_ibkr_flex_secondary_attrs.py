"""Flex XML de IBKR: un valor roto en un atributo secundario es error de fila.

Tras #4062 la cantidad, el precio, el valor, el coste y el saldo ya se
validaban, pero ``fifoPnlUnrealized`` (OpenPosition), ``settledCash`` e
``interestRate`` (CashReport) seguían pasando directos a ``_decimal``:
``validate_flex_xml`` daba el fichero por bueno y la importación (también la
sincronización automática) lanzaba «Importe no interpretable» y se perdía el
fichero entero. Un valor que no cabe en su columna (Numeric(20, 2) para P/L y
saldo liquidado, Numeric(10, 6) para el tipo de interés) llegaba al INSERT y
en Postgres daba 500. Ahora se omite solo esa fila y se dice cuál.
"""

import pytest
from sqlalchemy import create_engine, select

from app.models.entities import Base, CashBalance, Position
from app.services.ibkr_import_service import IBKRImportService, validate_flex_xml
from tests.test_ibkr_import import _tenant_session


def _xml(positions: str = "", cash: str = "") -> str:
    return (
        '<?xml version="1.0"?><FlexQueryResponse><FlexStatements><FlexStatement accountId="U1">'
        + (f"<OpenPositions>{positions}</OpenPositions>" if positions else "")
        + (f"<CashReport>{cash}</CashReport>" if cash else "")
        + "</FlexStatement></FlexStatements></FlexQueryResponse>"
    )


def _position(symbol: str, **extra: str) -> str:
    attrs = {
        "symbol": symbol, "position": "10", "markPrice": "10", "positionValue": "100",
        "costBasisPrice": "9", "currency": "USD", "reportDate": "2026-08-20",
    }
    attrs.update(extra)
    return "<OpenPosition " + " ".join(f'{k}="{v}"' for k, v in attrs.items()) + "/>"


def _cash(currency: str, **extra: str) -> str:
    attrs = {"currency": currency, "endingCash": "100", "reportDate": "2026-08-20"}
    attrs.update(extra)
    return "<CashReportCurrency " + " ".join(f'{k}="{v}"' for k, v in attrs.items()) + "/>"


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


@pytest.mark.parametrize(
    ("raw", "reason"),
    [("abc", "no es un número"), ("1e400", "notación científica"), ("99999999999999999999", "demasiado grande")],
)
def test_plusvalia_latente_rota_omite_solo_esa_posicion(engine, raw, reason):
    xml = _xml(_position("ZXP", fifoPnlUnrealized=raw) + _position("OKP", fifoPnlUnrealized="10"))
    errors = validate_flex_xml(xml)
    assert len(errors) == 1, errors
    assert "ZXP" in errors[0] and "plusvalía latente" in errors[0] and reason in errors[0]
    with _tenant_session(engine) as db:
        result = IBKRImportService().import_flex_xml(db, xml)
        positions = db.scalars(select(Position)).all()
        assert len(positions) == 1 and float(positions[0].unrealized_pnl) == 10
    assert result["positions_imported"] == 1
    assert any("plusvalía latente" in e for e in result["row_errors"])


@pytest.mark.parametrize(
    ("attrs", "word", "reason"),
    [
        ({"settledCash": "abc"}, "saldo liquidado", "no es un número"),
        ({"settledCash": "99999999999999999999"}, "saldo liquidado", "demasiado grande"),
        ({"interestRate": "abc"}, "tipo de interés", "no es un número"),
        ({"interestRate": "1e400"}, "tipo de interés", "notación científica"),
        ({"interestRate": "12345"}, "tipo de interés", "demasiado grande"),
    ],
)
def test_saldo_con_atributo_roto_omite_solo_esa_divisa(engine, attrs, word, reason):
    xml = _xml(cash=_cash("USD", **attrs) + _cash("EUR", settledCash="50", interestRate="1.5"))
    errors = validate_flex_xml(xml)
    assert len(errors) == 1, errors
    assert word in errors[0] and reason in errors[0] and "USD" in errors[0]
    with _tenant_session(engine) as db:
        result = IBKRImportService().import_flex_xml(db, xml)
        cash = db.scalars(select(CashBalance)).all()
        assert [c.currency for c in cash] == ["EUR"]
        assert float(cash[0].settled_cash) == 50 and float(cash[0].interest_rate) == 1.5
    assert any(word in e for e in result["row_errors"])


def test_valores_normales_y_vacios_siguen_entrando(engine):
    xml = _xml(
        _position("OKP", fifoPnlUnrealized="-12.5") + _position("NOP"),
        _cash("USD", settledCash="90", interestRate="0.0425") + _cash("EUR", settledCash="", interestRate=""),
    )
    assert validate_flex_xml(xml) == []
    with _tenant_session(engine) as db:
        result = IBKRImportService().import_flex_xml(db, xml)
        cash = {c.currency: c for c in db.scalars(select(CashBalance)).all()}
        assert float(cash["USD"].settled_cash) == 90 and float(cash["EUR"].settled_cash) == 100
    assert result["positions_imported"] == 2 and result["row_errors"] == []
