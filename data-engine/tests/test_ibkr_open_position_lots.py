"""Flex con «Open Positions: Lot»: los lotes no sobrescriben la posicion.

IBKR emite por posicion una fila ``OpenPosition levelOfDetail="SUMMARY"`` y una
``OpenPosition levelOfDetail="LOT"`` por lote. Valores esperados a mano:
lotes 6 @ 140 y 4 @ 165 -> 10 acciones, coste 6*140 + 4*165 = 1500, medio 150;
valor 10 * 180,5 = 1805; P/L no realizado 1805 - 1500 = 305.
"""

from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Position
from app.services.ibkr_import_service import IBKRImportService
from tests.test_ibkr_import import _tenant_session

COMMON = (
    'accountId="U1" symbol="AAPL" conid="265598" currency="USD" markPrice="180.5" reportDate="2026-08-20"'
)
SUMMARY = (
    f'<OpenPosition {COMMON} levelOfDetail="SUMMARY" position="10" positionValue="1805" '
    'costBasisPrice="150" costBasisMoney="1500" fifoPnlUnrealized="305"/>'
)
LOT_A = (
    f'<OpenPosition {COMMON} levelOfDetail="LOT" position="6" positionValue="1083" '
    'costBasisPrice="140" costBasisMoney="840" fifoPnlUnrealized="243" openDateTime="20250102;093000"/>'
)
LOT_B = (
    f'<OpenPosition {COMMON} levelOfDetail="LOT" position="4" positionValue="722" '
    'costBasisPrice="165" costBasisMoney="660" fifoPnlUnrealized="62" openDateTime="20260301;100000"/>'
)


def _xml(*rows):
    return (
        '<?xml version="1.0"?><FlexQueryResponse><FlexStatements><FlexStatement accountId="U1">'
        "<OpenPositions>" + "".join(rows) + "</OpenPositions>"
        "</FlexStatement></FlexStatements></FlexQueryResponse>"
    )


def _import(*rows):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db: Session = _tenant_session(engine)
    IBKRImportService().import_flex_xml(db, _xml(*rows))
    positions = [
        (p.quantity, p.average_cost, p.market_value, p.unrealized_pnl, p.cost_basis_native)
        for p in db.query(Position).all()
    ]
    db.close()
    return positions


def test_summary_row_wins_over_its_lots():
    [(qty, avg, value, upl, cost)] = _import(SUMMARY, LOT_A, LOT_B)
    assert qty == Decimal("10")
    assert avg == Decimal("150")
    assert value == Decimal("1805")
    assert upl == Decimal("305")
    assert cost == Decimal("1500")


def test_lots_without_summary_are_summed():
    [(qty, avg, value, upl, cost)] = _import(LOT_A, LOT_B)
    assert qty == Decimal("10")
    assert avg == Decimal("150")
    assert value == Decimal("1805")
    assert upl == Decimal("305")
    assert cost == Decimal("1500")


def test_single_summary_row_unchanged():
    [(qty, avg, *_)] = _import(SUMMARY)
    assert (qty, avg) == (Decimal("10"), Decimal("150"))
