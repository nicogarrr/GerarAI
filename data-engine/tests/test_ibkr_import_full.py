"""Importacion Flex completa de IBKR contra SQLite real (posiciones, caja, snapshot).

Tercer lote de huecos de ibkr_import_service: el camino de importacion
completa (sin trades_only). Los trabajos en segundo plano que ese camino
encola (backfill de precios y señal DCA) quedan DOBLADOS: se registra la
llamada y no se ejecuta nada. El resto (posiciones, caja, filas crudas, snapshot diario) se
ejerce de verdad contra SQLite en memoria.

- OpenPosition + CashReport: posicion y saldo persistidos con cantidad,
  coste medio, cotizacion y fechas EXACTAS del extracto; snapshot diario
  creado para la fecha del extracto.
- Segundo import del mismo extracto: las filas crudas ya presentes no se
  duplican y la posicion se actualiza sin crear otra.
- Extracto mas antiguo que la posicion ya fijada (statement_as_of
  posterior): la posicion NO retrocede; la fila se omite.
- reconcile sin ``query_complete_attested``: se bloquea declarando el
  motivo y NO se borra ninguna posicion (ni la que falta en el extracto).

NO prueba (declarado): reconcile con attestacion completa (borrado real),
valuation hold, conversiones FX, splits, ni la fidelidad contra un
extracto real de IBKR (XML sinteticos).
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import app.services.dca_on_add
import app.services.market_close_sync
from app.models.entities import (
    Base,
    CashBalance,
    Company,
    IbkrRawRow,
    PortfolioDailySnapshot,
    Position,
)
from app.services.ibkr_import_service import IBKRImportError, IBKRImportService


@pytest.fixture
def encolados(monkeypatch):
    """Dobla los trabajos en segundo plano del import completo."""
    llamadas = {"backfill": 0, "dca": 0}

    def _backfill_falso(db, company_ids, tenant_id=None, user_id=None):
        llamadas["backfill"] += 1
        return 0

    def _dca_falso(db):
        llamadas["dca"] += 1
        return 0

    monkeypatch.setattr(
        app.services.market_close_sync, "enqueue_price_backfills", _backfill_falso
    )
    monkeypatch.setattr(
        app.services.dca_on_add, "enqueue_dca_for_new_tracked", _dca_falso
    )
    return llamadas


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session
    engine.dispose()


def _flex(*filas: str) -> str:
    cuerpo = "".join(filas)
    return (
        '<FlexQueryResponse queryName="q" type="AF">'
        f'<FlexStatements><FlexStatement accountId="U1" fromDate="2026-03-01" toDate="2026-03-31">'
        f"{cuerpo}</FlexStatement></FlexStatements></FlexQueryResponse>"
    )


_POSICION_AAPL = (
    '<OpenPositions><OpenPosition symbol="AAPL" assetCategory="STK" '
    'position="10" markPrice="150.50" costBasisPrice="140.25" '
    'reportDate="2026-03-31" currency="USD" listingExchange="NASDAQ"/></OpenPositions>'
)
_CAJA_USD = (
    '<CashReport><CashReportCurrency currency="USD" endingCash="1234.56" '
    'settledCash="1234.56" reportDate="2026-03-31"/></CashReport>'
)


def _emisor(db, ticker="AAPL"):
    company = Company(
        ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def test_import_completo_posicion_caja_y_snapshot(db, encolados):
    resultado = IBKRImportService().import_flex_xml(db, _flex(_POSICION_AAPL, _CAJA_USD))
    assert resultado["status"] == "imported"
    assert resultado["positions_imported"] == 1
    assert resultado["cash_imported"] == 1
    posicion = db.scalar(select(Position))
    assert posicion.quantity == Decimal("10")
    assert posicion.average_cost == Decimal("140.25")
    assert posicion.market_price == Decimal("150.50")
    assert posicion.as_of == date(2026, 3, 31)
    assert posicion.statement_as_of == date(2026, 3, 31)
    assert posicion.source == "ibkr_flex"
    caja = db.scalar(select(CashBalance).where(CashBalance.currency == "USD"))
    assert caja.balance == Decimal("1234.56")
    assert caja.as_of == date(2026, 3, 31)
    # Snapshot diario real en BD para la fecha del extracto.
    assert resultado["portfolio_snapshot_id"] is not None
    snapshot = db.scalar(select(PortfolioDailySnapshot))
    assert snapshot.snapshot_date == date(2026, 3, 31)
    # Los trabajos en segundo plano se encolaron (doblados: nada real).
    assert encolados == {"backfill": 1, "dca": 1}


def test_segundo_import_no_duplica_filas_crudas_ni_posicion(db, encolados):
    xml = _flex(_POSICION_AAPL, _CAJA_USD)
    servicio = IBKRImportService()
    primero = servicio.import_flex_xml(db, xml)
    segundo = servicio.import_flex_xml(db, xml)
    assert primero["raw_rows_stored"] > 0
    assert segundo["raw_rows_stored"] == 0
    assert segundo["raw_rows_already_present"] == primero["raw_rows_stored"]
    assert db.scalar(select(func.count()).select_from(Position)) == 1
    posicion = db.scalar(select(Position))
    assert posicion.quantity == Decimal("10")


def test_extracto_antiguo_no_retrocede_la_posicion(db, encolados):
    company = _emisor(db)
    posicion = Position(
        portfolio_id=None, company_id=company.id,
        quantity=Decimal("5"), average_cost=Decimal("100"), currency="USD",
        source="ibkr_flex", statement_as_of=date(2026, 4, 1),
        as_of=date(2026, 4, 1), market_price=Decimal("160"),
    )
    db.add(posicion)
    db.commit()
    # El extracto (31 de marzo) es anterior al que fijo cantidad y coste
    # (1 de abril): la fila se omite y la posicion no se toca.
    resultado = IBKRImportService().import_flex_xml(db, _flex(_POSICION_AAPL))
    assert resultado["positions_imported"] == 0
    db.refresh(posicion)
    assert posicion.quantity == Decimal("5")
    assert posicion.average_cost == Decimal("100")
    assert posicion.statement_as_of == date(2026, 4, 1)


def test_reconcile_sin_attestacion_bloquea_y_no_borra(db, encolados):
    company = _emisor(db, ticker="MSFT")
    posicion = Position(
        portfolio_id=None, company_id=company.id,
        quantity=Decimal("3"), average_cost=Decimal("400"), currency="USD",
        source="ibkr_flex", statement_as_of=date(2026, 3, 30),
        as_of=date(2026, 3, 30), market_price=Decimal("410"),
    )
    db.add(posicion)
    db.commit()
    # MSFT ya no viene en el extracto, pero sin attestacion de consulta
    # completa el reconcile se bloquea: nada se borra y se declara el motivo.
    resultado = IBKRImportService().import_flex_xml(
        db,
        _flex(_POSICION_AAPL, _CAJA_USD),
        reconcile=True,
        expected_account_id="U1",
        query_complete_attested=False,
        max_statement_age_days=365,
    )
    assert resultado["reconcile_blocked"]
    assert resultado["positions_closed"] == []
    assert db.scalar(select(func.count()).select_from(Position)) == 2


def test_reconcile_cuenta_equivocada_rechaza_antes_de_escribir(db, encolados):
    with pytest.raises(IBKRImportError, match="Extracto Flex rechazado"):
        IBKRImportService().import_flex_xml(
            db,
            _flex(_POSICION_AAPL),
            reconcile=True,
            expected_account_id="OTRA-CUENTA",
            max_statement_age_days=365,
        )
    assert db.scalar(select(func.count()).select_from(Position)) == 0
    assert db.scalar(select(func.count()).select_from(IbkrRawRow)) == 0
