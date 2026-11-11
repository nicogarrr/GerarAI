"""Estado de negociacion de un listado: dato derivado vs baja probada.

Decision del piloto (11-nov-2026, via main): 5 sesiones sin barra prueban
AUSENCIA de datos/negociacion (suspension temporal, proveedor caido), NO la
baja del listado. Por eso el estado "no_trading_data" es derivado (se calcula
del ultimo MarketPrice y del calendario de sesiones, nunca se persiste y se
reversa solo cuando vuelve una barra) y ``Company.delisted_at`` SOLO se fija
con evidencia primaria de la baja. Caso real: SES.TO (Secure Energy Services)
— comunicado de GFL del 1-sep-2026 cerrando la adquisicion; Yahoo seguia
respondiendo 200 con el ultimo precio congelado y 0 barras (11-nov-2026).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.entities import Base, Company, MarketPrice, Portfolio, Position
from app.services import listing_delisting
from app.services.connectors.ecb import ECBRates
from app.services.market_refresh_service import MarketRefreshService, PriceObservation

# Semana sin festivos TSX/NYSE: vie 30-oct-2026 al lun 9-nov-2026.
HOY = date(2026, 11, 9)  # lunes


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session, ticker: str, exchange: str = "TORONTO STOCK EXCHANGE") -> Company:
    company = Company(
        ticker=ticker,
        name=ticker,
        exchange=exchange,
        currency="CAD",
        sector="S",
        industry="I",
        company_type="holding",
        valuation_model="unassigned",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.flush()
    return company


def _bar(db: Session, company: Company, day: date) -> None:
    db.add(
        MarketPrice(
            company_id=company.id, date=day, close=Decimal("10"),
            adj_close=Decimal("10"), source="test",
        )
    )
    db.flush()


def test_modelo_declara_columnas_e_indice() -> None:
    table = Company.__table__
    assert "delisted_at" in table.c and table.c.delisted_at.nullable
    assert "listing_note" in table.c and table.c.listing_note.nullable
    assert "ix_companies_delisted_at" in {ix.name for ix in table.indexes}


def test_cinco_sesiones_sin_barra_es_no_trading_data() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as db:
        db.info["tenant_id"] = "tenant-test"
        # vie 30-oct -> vie 6-nov: lun-vie 2..6 nov = 5 sesiones sin barra.
        company = _company(db, "ZDEL.TO")
        _bar(db, company, date(2026, 10, 30))
        assert listing_delisting.listing_data_state(db, company, today=date(2026, 11, 6)) == "no_trading_data"


def test_cuatro_sesiones_sin_barra_sigue_activa() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as db:
        db.info["tenant_id"] = "tenant-test"
        # vie 30-oct -> jue 5-nov: 4 sesiones sin barra.
        company = _company(db, "ZOK4.TO")
        _bar(db, company, date(2026, 10, 30))
        assert listing_delisting.listing_data_state(db, company, today=date(2026, 11, 5)) == "active"


def test_fin_de_semana_no_cuenta_como_sesiones() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as db:
        db.info["tenant_id"] = "tenant-test"
        company = _company(db, "ZFIN.TO")
        _bar(db, company, date(2026, 11, 6))  # viernes
        assert listing_delisting.listing_data_state(db, company, today=HOY) == "active"


def test_empresa_sin_barras_es_activa() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as db:
        db.info["tenant_id"] = "tenant-test"
        company = _company(db, "ZNEW.TO")
        assert listing_delisting.listing_data_state(db, company, today=HOY) == "active"


def test_estado_derivado_se_reversa_solo_con_barra_nueva() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as db:
        db.info["tenant_id"] = "tenant-test"
        company = _company(db, "ZREV.TO")
        _bar(db, company, date(2026, 10, 30))
        assert listing_delisting.listing_data_state(db, company, today=HOY) == "no_trading_data"
        _bar(db, company, date(2026, 11, 6))  # vuelve la cotizacion
        assert listing_delisting.listing_data_state(db, company, today=HOY) == "active"


def test_mark_delisted_exige_evidencia_primaria() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as db:
        db.info["tenant_id"] = "tenant-test"
        company = _company(db, "ZEVI.TO")
        with pytest.raises(ValueError):
            listing_delisting.mark_delisted(db, company, evidence="")
        with pytest.raises(ValueError):
            listing_delisting.mark_delisted(db, company, evidence="   ")


def test_mark_delisted_fija_fecha_y_nota_y_domina_el_estado() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as db:
        db.info["tenant_id"] = "tenant-test"
        company = _company(db, "ZMARK.TO")
        _bar(db, company, HOY)  # barra de hoy: sin la baja seria "active"
        cuando = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
        listing_delisting.mark_delisted(db, company, evidence="comunicado adquisicion", at=cuando)
        assert company.delisted_at == cuando
        assert company.listing_note == "comunicado adquisicion"
        assert listing_delisting.listing_data_state(db, company, today=HOY) == "delisted"


def test_clear_delisted_revierte_con_evidencia_sin_borrar_nada() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as db:
        db.info["tenant_id"] = "tenant-test"
        company = _company(db, "ZCLR.TO")
        listing_delisting.mark_delisted(db, company, evidence="baja confirmada")
        listing_delisting.clear_delisted(db, company, evidence="relistado confirmado")
        assert company.delisted_at is None
        assert company.listing_note is None
        with pytest.raises(ValueError):
            listing_delisting.clear_delisted(db, company, evidence="")


class _RecordingPriceProvider:
    def __init__(self) -> None:
        self.seen: list[str] = []

    async def fetch(self, companies, *, as_of):
        self.seen.extend(company.ticker for company in companies)
        observations = {
            company.ticker: PriceObservation(
                ticker=company.ticker, price=Decimal("100"), price_date=as_of, source="fake",
            )
            for company in companies
        }
        return observations, []


class _FakeFXProvider:
    async def fetch(self, *, base_currency, quote_currencies):
        return ECBRates(
            rate_date=HOY, rates={currency: Decimal("1.1") for currency in quote_currencies},
        )


def _seed_refresh(db: Session) -> tuple[Company, Company]:
    db.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
    viva = _company(db, "ZVIVA.TO")
    baja = _company(db, "ZBAJA.TO")
    db.add(Position(company_id=baja.id, quantity=Decimal("5"), currency="CAD",
                    market_price=Decimal("10"), market_value=Decimal("50")))
    _bar(db, baja, date(2026, 10, 30))
    db.commit()
    return viva, baja


def test_refresh_no_pide_precios_de_la_baja_pero_su_posicion_se_valora(db) -> None:
    viva, baja = _seed_refresh(db)
    listing_delisting.mark_delisted(db, baja, evidence="comunicado adquisicion")
    db.commit()
    provider = _RecordingPriceProvider()
    service = MarketRefreshService(price_provider=provider, fx_provider=_FakeFXProvider())
    result = asyncio.run(service.refresh(db, as_of=HOY))
    assert provider.seen == ["ZVIVA.TO"]
    # La posicion de la baja sigue valorandose con su ultima barra guardada.
    assert [stage["name"] for stage in result["stages"]][:1] == ["update_prices"]


def test_refresh_filtra_la_baja_aunque_el_caller_la_pase_explicita(db) -> None:
    viva, baja = _seed_refresh(db)
    listing_delisting.mark_delisted(db, baja, evidence="comunicado adquisicion")
    db.commit()
    provider = _RecordingPriceProvider()
    service = MarketRefreshService(price_provider=provider, fx_provider=_FakeFXProvider())
    asyncio.run(service.refresh(db, as_of=HOY, companies=[viva, baja]))
    assert provider.seen == ["ZVIVA.TO"]
