"""El backfill del BCE nunca puede tumbar la importacion CSV.

Reproduccion hermetica del fallo original: importar un CSV historico en USD
sin tipos guardados dispara la descarga del BCE (#2349) desde
``ensure_historical_fx``, cuya escritura hacia ``db.commit()`` dentro del
``with db.begin_nested()`` de la fila en curso. El savepoint moria y la
importacion entera se caia con InvalidRequestError a mitad del fichero (y las
filas ya procesadas quedaban comiteadas a medias por ese commit ajeno). La
suite no lo veia: con APP_ENV=test el backfill solo corre inyectado y los
stubs no commitean.

La solucion tiene dos capas:

1. ``_default_fx_backfill`` (la via de produccion) descarga con una SESION
   PROPIA: el commit del backfill es de esa sesion y jamas toca la del
   importador, esté o no en un savepoint. El reintento de una descarga
   fallida dentro del bucle es seguro por construccion.
2. El importador calienta los tipos ANTES del bucle con los pares
   (divisa, desde) EXACTOS que el bucle va a pedir: la divisa efectiva de
   cada fila (la del listado verificado por ISIN si lo hay) y tambien las
   fechas de las patas buy/sell ya guardadas que ``rebuild_position``
   reproduce. En condiciones normales el bucle no descarga nada.
"""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models import Company, FXRate, Position, Tenant, Transaction
from app.services import portfolio_ledger_service as ledger_mod
from app.services.ibkr_import_service import IBKRImportService
from app.services.listing_identity import ListingIdentity
from app.services.portfolio_ledger_service import (
    PortfolioLedgerService,
    _default_fx_backfill,
)

CSV_TWO_BUYS = (
    "symbol,action,quantity,price,date,fees,currency\n"
    "ZZBK,buy,10,100.50,01/06/2025,1.25,USD\n"
    "ZZBK,buy,5,101.75,02/03/2025,0,USD\n"
)

CSV_TWO_SYMBOLS = (
    "symbol,action,quantity,price,date,fees,currency\n"
    "AAA,buy,10,50,2025-01-06,0,USD\n"
    "BBB,buy,5,100,2025-02-03,0,USD\n"
)


@pytest.fixture
def db():
    ledger_mod._ECB_BACKFILL_TRIED.clear()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        tenant = Tenant(external_id="csv-fx-commit", name="csv fx commit")
        session.add(tenant)
        session.flush()
        session.info["tenant_id"] = tenant.id
        yield session


def _inject_backfill(monkeypatch, backfill):
    real = PortfolioLedgerService
    monkeypatch.setattr(
        ledger_mod,
        "PortfolioLedgerService",
        lambda: real(fx_backfill=backfill),
    )


def _recording_backfill(calls):
    """Backfill falso: anota como se le llamo y escribe el tipo desde ``start``."""

    def _fake(db, currencies, start, end):
        calls.append(
            {
                "currencies": {code.upper() for code in currencies},
                "start": start,
                "nested": db.in_nested_transaction(),
            }
        )
        for code in currencies:
            db.add(
                FXRate(
                    base_currency="EUR",
                    quote_currency=code.upper(),
                    rate=Decimal("0.92"),
                    rate_date=start,
                    source="ecb",
                )
            )
        db.flush()
        return {"source": "ecb", "written": dict.fromkeys(currencies, 1), "not_published": []}

    return _fake


def _position(db, ticker):
    company = db.query(Company).filter_by(ticker=ticker).one()
    return db.query(Position).filter_by(company_id=company.id).one()


def _committing_backfill(db, currencies, start, end):
    """Simula una descarga BCE con exito: escribe el tipo y COMMITEA."""
    db.add(
        FXRate(
            base_currency="EUR",
            quote_currency="USD",
            rate=Decimal("0.92"),
            rate_date=end,
            source="ecb",
        )
    )
    db.commit()
    return {"source": "ecb", "written": {"USD": 1}, "not_published": []}


def test_successful_ecb_backfill_does_not_break_csv_import(db, monkeypatch):
    _inject_backfill(monkeypatch, _committing_backfill)
    result = IBKRImportService().import_ibkr_csv(db, CSV_TWO_BUYS)
    assert result["trades_imported"] == 2
    rows = sorted(
        (float(t.quantity), float(t.price), t.trade_date)
        for t in db.query(Transaction).all()
    )
    assert rows == [
        (5.0, 101.75, date(2025, 2, 3)),
        (10.0, 100.50, date(2025, 1, 6)),
    ]
    # El tipo descargado persiste (esa era la intencion del backfill).
    assert db.query(FXRate).count() == 1


def test_rows_before_and_after_backfill_keep_their_own_data(db, monkeypatch):
    """La fila que disparo el backfill no puede quedar comiteada a medias."""
    _inject_backfill(monkeypatch, _committing_backfill)
    IBKRImportService().import_ibkr_csv(db, CSV_TWO_BUYS)
    first = [t for t in db.query(Transaction).all() if float(t.quantity) == 10.0][0]
    assert float(first.fees) == 1.25
    assert first.currency == "USD"


def test_warmup_covers_every_symbol_and_date_before_the_loop(db, monkeypatch):
    """Dos simbolos con fechas distintas: una sola descarga, fuera del bucle."""
    calls = []
    _inject_backfill(monkeypatch, _recording_backfill(calls))
    result = IBKRImportService().import_ibkr_csv(db, CSV_TWO_SYMBOLS)
    assert result["trades_imported"] == 2
    # Una unica llamada, con la fecha mas antigua (2025-01-06 menos el margen
    # de 10 dias de fines de semana/festivos) y NUNCA dentro de un savepoint.
    assert calls == [
        {"currencies": {"USD"}, "start": date(2024, 12, 27), "nested": False}
    ]
    assert _position(db, "AAA").cost_basis_base == Decimal("460")  # 10*50*0.92
    assert _position(db, "BBB").cost_basis_base == Decimal("460")  # 5*100*0.92


def test_failed_warmup_degrades_and_later_retry_is_safe(db, monkeypatch):
    """Red caida en el calentamiento: la fila se degrada, el reintento no rompe.

    Escenario del piloto: el backfill de AAA/2025-01-06 falla por red y BBB
    tiene otra fecha (2025-02-03), asi que el bucle reintenta la descarga
    DENTRO del savepoint. Antes eso escribia y commiteaba la sesion del
    importador: InvalidRequestError. Ahora la via de produccion usa una sesion
    propia (ver test_default_fx_backfill_uses_its_own_session); aqui el stub
    inyectado escribe sin commitear para fijar la semantica: la importacion
    termina, AAA queda degradada (sin tipo) y BBB se valora con el reintento.
    """
    calls = []

    def flaky(db, currencies, start, end):
        calls.append({"start": start, "nested": db.in_nested_transaction()})
        if len(calls) == 1:
            raise ConnectionError("BCE inalcanzable")
        for code in currencies:
            db.add(
                FXRate(
                    base_currency="EUR",
                    quote_currency=code.upper(),
                    rate=Decimal("0.92"),
                    rate_date=start,
                    source="ecb",
                )
            )
        db.flush()
        return {"source": "ecb", "written": dict.fromkeys(currencies, 1)}

    _inject_backfill(monkeypatch, flaky)
    result = IBKRImportService().import_ibkr_csv(db, CSV_TWO_SYMBOLS)
    assert result["trades_imported"] == 2
    # 1) calentamiento fuera del savepoint (falla); 2) reintento de la fecha
    # de BBB dentro del bucle (ya no puede tumbar la sesion del importador).
    assert calls == [
        {"start": date(2024, 12, 27), "nested": False},
        {"start": date(2025, 1, 24), "nested": True},
    ]
    assert _position(db, "AAA").cost_basis_base is None  # degradada, sin tipo
    assert _position(db, "BBB").cost_basis_base == Decimal("460")


def test_warmup_uses_the_isin_listing_currency(db, monkeypatch):
    """La divisa calentada es la del listado verificado por ISIN, no la del sufijo.

    «TST.L» sin columna de divisa se adivinaria en USD (las plazas en
    subunidad no se presumen); el listado verificado dice GBP y es la divisa
    con la que la fila se asienta. Calentar USD dejaba la descarga de GBP
    para dentro del savepoint.
    """
    listing = ListingIdentity(
        isin="GB0000000001",
        name="Test PLC",
        ticker="TST.L",
        exchange="LONDON STOCK EXCHANGE",
        currency="GBP",
        yahoo="TST.L",
        stooq="tst.uk",
        source="test",
    )
    monkeypatch.setattr(
        "app.services.listing_identity.reviewed_listing",
        lambda isin: listing if (isin or "").strip().upper() == listing.isin else None,
    )
    calls = []
    _inject_backfill(monkeypatch, _recording_backfill(calls))
    csv_text = (
        "symbol,isin,action,quantity,price,date\n"
        "TST.L,GB0000000001,buy,10,100,2025-02-03\n"
    )
    result = IBKRImportService().import_ibkr_csv(db, csv_text)
    assert result["trades_imported"] == 1, result
    assert calls == [
        {"currencies": {"GBP"}, "start": date(2025, 1, 24), "nested": False}
    ]
    trade = db.query(Transaction).one()
    assert trade.currency == "GBP"
    assert _position(db, "TST.L").cost_basis_base == Decimal("920")  # 10*100*0.92


def test_warmup_covers_existing_ledger_legs(db, monkeypatch):
    """Las patas buy/sell YA guardadas que rebuild_position reproduce tambien se calientan.

    Sin esto, importar una compra de 2025 sobre una cartera con una compra de
    2024 sin tipo descargaba la serie de 2024 DENTRO del savepoint de la fila.
    """
    # Pata vieja sembrada con el backfill desactivado (APP_ENV=test): sin tipo.
    PortfolioLedgerService().create_transaction(
        db,
        ticker="AAA",
        action="buy",
        quantity=Decimal("10"),
        price=Decimal("50"),
        trade_date=date(2024, 6, 3),
        currency="USD",
    )
    db.flush()
    assert _position(db, "AAA").cost_basis_base is None  # sin tipo todavia

    calls = []
    _inject_backfill(monkeypatch, _recording_backfill(calls))
    result = IBKRImportService().import_ibkr_csv(
        db,
        "symbol,action,quantity,price,date,fees,currency\n"
        "AAA,buy,5,100,2025-02-03,0,USD\n",
    )
    assert result["trades_imported"] == 1, result
    # Una sola descarga, fuera del bucle, DESDE la pata vieja (2024-06-03
    # menos el margen de 10 dias), no desde la fila nueva.
    assert calls == [
        {"currencies": {"USD"}, "start": date(2024, 5, 24), "nested": False}
    ]
    # Rebuild con tipo para las dos patas: (10*50 + 5*100) * 0.92.
    assert _position(db, "AAA").cost_basis_base == Decimal("920")


def test_default_fx_backfill_commits_only_its_own_session(tmp_path, monkeypatch):
    """El backfill por defecto escribe y confirma con SESION PROPIA.

    Es la garantia estructural: aunque una descarga ocurra con el savepoint
    de una fila abierto, el commit es de otra sesion y la transaccion del
    importador sigue viva (InvalidRequestError imposible desde esta via).
    """
    engine = create_engine(f"sqlite:///{tmp_path}/fx.db")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.core.database.SessionLocal", factory)
    captured = {}

    def fake_sync(session, *, currencies, start, end):
        captured["session"] = session
        session.add(
            FXRate(
                base_currency="EUR",
                quote_currency="USD",
                rate=Decimal("0.92"),
                rate_date=start,
                source="ecb",
            )
        )
        session.commit()  # como el backfill real: confirma SU escritura
        return {"written": {"USD": 1}}

    monkeypatch.setattr(
        "app.services.connectors.ecb_history.backfill_ecb_rates_sync", fake_sync
    )
    caller = factory()
    with caller.begin_nested():
        _default_fx_backfill(caller, {"USD"}, date(2025, 1, 1), date(2025, 1, 10))
        # Si el commit hubiera sido de ``caller``, el savepoint estaria muerto.
        assert caller.in_nested_transaction()
        caller.add(Tenant(external_id="own-session", name="own session"))
        caller.flush()
    caller.commit()
    assert captured["session"] is not caller
    assert not captured["session"].in_transaction()  # commit hecho y sesion cerrada
    with Session(engine) as check:
        # El tipo del backfill y el trabajo del llamante: ambos confirmados,
        # cada uno por su camino.
        assert check.scalar(select(FXRate.quote_currency)) == "USD"
        assert check.scalar(select(Tenant.external_id)) == "own-session"
