"""Presupuesto de consultas del dedup de dividendos/splits (regresion N+1).

El proveedor devuelve el historial COMPLETO en cada sync (Yahoo chart con
period1=0): una compania con N dividendos persistidos costaba N consultas
de dedup por fila, a diario, por compania. Estos tests fijan:
  1. una lectura por compania (constante en N), no una por fila;
  2. una segunda sync de la MISMA compania en la misma sesion sigue
     dedupando (la cache aprende los inserts de la corrida anterior);
  3. la ruta legacy (legacy_utc_ex_date + source yahoo_finance) sigue
     dedupando tras el cambio.
"""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, DividendRecord
from app.services.dividend_ingestion_service import DividendIngestionService

N = 120
ROWS = [
    {
        "ex_date": date(1996 + i // 4, (i % 4) * 3 + 2, 15),
        "pay_date": None,
        "amount": Decimal("0.25") + Decimal(i) * Decimal("0.001"),
        "currency": "USD",
        "legacy_utc_ex_date": date(1996 + i // 4, (i % 4) * 3 + 2, 15),
    }
    for i in range(N)
]


class _FakeService(DividendIngestionService):
    async def _fetch_provider_rows(self, company):
        return ROWS, "yahoo_finance"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        yield session


@pytest.fixture
def company(db):
    company = Company(
        ticker="PAYER",
        name="PAYER",
        exchange="NASDAQ",
        currency="USD",
        sector="S",
        industry="I",
        company_type="research_candidate",
        valuation_model="unassigned",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _seed_history(db, company) -> None:
    for row in ROWS:
        db.add(
            DividendRecord(
                company_id=company.id,
                ex_date=row["ex_date"],
                pay_date=None,
                amount=row["amount"],
                currency="USD",
                source="yahoo_finance",
            )
        )
    db.commit()


def _sync(db) -> dict:
    return asyncio.run(_FakeService().sync_company(db, ticker="PAYER"))


def test_dedup_statement_count_is_constant_in_history_size(db, company):
    """N filas ya persistidas + historial completo: 0 inserts y pocas consultas."""
    _seed_history(db, company)
    statements = 0

    @event.listens_for(db.get_bind(), "before_cursor_execute")
    def _count(conn, cursor, statement, parameters, context, executemany):
        nonlocal statements
        statements += 1

    result = _sync(db)
    assert result["status"] == "ok"
    assert result["inserted"] == 0
    assert result["existing"] == N
    # ANTES: 1 (resolve) + N dedup + 1 insert-count... > 100. DESPUES: una
    # lectura de la compania + constantes fijas; holgura para cabeceras.
    assert statements <= 12, f"N+1 de dedup: {statements} sentencias para {N} filas"


def test_second_sync_same_session_still_dedups(db, company):
    """Regresion: la cache no debe quedarse con la foto vacia de la 1a sync."""
    first = _sync(db)
    assert first["status"] == "ok" and first["inserted"] == N and first["existing"] == 0
    second = _sync(db)
    assert second["status"] == "ok"
    assert second["inserted"] == 0
    assert second["existing"] == N
    assert db.query(DividendRecord).filter_by(company_id=company.id).count() == N


def test_track_new_record_without_cache_is_noop(db, company):
    """_track_new_record sin cache poblada (defensa) no revienta ni crea nada."""
    from app.services.split_ingestion_service import ProviderIngestionService

    ProviderIngestionService._track_new_record(db, company, object(), "dedup_dividend_records")
    assert db.info.get("dedup_dividend_records") is None


def test_legacy_path_still_dedups_and_fixes_in_place(db, company):
    """Fila guardada con la fecha UTC (un dia antes): dedupa y corrige en sitio."""
    row = dict(ROWS[0])
    row["ex_date"] = date(1996, 2, 16)
    row["legacy_utc_ex_date"] = date(1996, 2, 15)  # fecha UTC heredada (ASX/NZX)
    db.add(
        DividendRecord(
            company_id=company.id,
            ex_date=date(1996, 2, 15),  # guardada con la fecha UTC heredada
            pay_date=None,
            amount=row["amount"],
            currency="USD",
            source="yahoo_finance",
        )
    )
    db.commit()
    service = _FakeService()
    match = service._existing_record(db, company, row)
    assert match is not None, "la ruta legacy (fecha UTC + amount + fuente) no dedupo"
    assert match.ex_date == row["ex_date"], "no corrigio la fecha en sitio como antes"


def test_legacy_path_ignores_other_sources(db, company):
    """La ruta legacy solo corrige filas yahoo_finance; otra fuente no dedupa."""
    row = dict(ROWS[0])
    row["ex_date"] = date(1996, 2, 16)
    row["legacy_utc_ex_date"] = date(1996, 2, 15)
    db.add(
        DividendRecord(
            company_id=company.id,
            ex_date=date(1996, 2, 15),
            pay_date=None,
            amount=row["amount"],
            currency="USD",
            source="fmp",
        )
    )
    db.commit()
    service = _FakeService()
    assert service._existing_record(db, company, row) is None


def test_failed_commit_rollback_retry_reingests(db, company, monkeypatch):
    """Regresion Auditoria: commit fallido + rollback + reintento en la MISMA
    sesion no debe dedupar contra fantasmas de la cache (perdida silenciosa).

    La cache en db.info solo puede aprender los inserts tras un commit con
    exito; si los aprende pendientes, el rollback los borra de la BD pero no
    de la cache y el reintento reporta existing=N con la tabla vacia.
    """
    service = _FakeService()
    real_commit = db.commit
    calls = {"n": 0}

    def fail_first_commit():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("commit caido (simulado)")
        return real_commit()

    monkeypatch.setattr(db, "commit", fail_first_commit)
    with pytest.raises(RuntimeError, match="commit caido"):
        asyncio.run(service.sync_company(db, ticker="PAYER"))
    db.rollback()
    result = asyncio.run(service.sync_company(db, ticker="PAYER"))
    assert result["status"] == "ok"
    assert result["inserted"] == N, (
        f"reintento tras rollback perdio la ingesta: {result['inserted']} inserts, "
        f"{result['existing']} 'existentes' fantasma"
    )
    assert result["existing"] == 0
    assert db.query(DividendRecord).filter_by(company_id=company.id).count() == N
