"""Un listado fuera de EE. UU. no hereda los hechos SEC de un homónimo de EE. UU.

Caso real (prod, 4-nov-2026): PRIM, S.A. cotiza en BME con el ticker «PRM».
La SEC resuelve «PRM» a Perimeter Solutions (CIK 0001880319), así que la
ingesta SEC guardó los 10-K de Perimeter (ingresos 652 M USD, 150 M de
acciones) en la ficha de PRIM y su DCF dio 198 € con la acción a 12,30 €.
Lo mismo pasaba con IBERPAPEL («IBG»). El ticker solo NO identifica a un
emisor fuera de su bolsa: con listado no estadounidense, la razón social de
la SEC tiene que casar con la de la ficha (Novo Nordisk, Santander sí casan).
Los tests son sintéticos, sin ningún ticker real en la lógica.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, FinancialFact
from app.services import financial_ingestion_service as ingestion
from app.services import insider_monitor
from app.services.company_identity_verification import sec_identity_mismatch
from app.services.financial_ingestion_service import FinancialIngestionService


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


@pytest.fixture(autouse=True)
def _sin_free_data(monkeypatch):
    async def _stub(ticker, cik):
        return {"status": "skipped", "recent_filings": [], "macro": None}

    monkeypatch.setattr(ingestion, "_free_data_snapshot", _stub)


def _company(db, *, ticker="XYZ", name="Alfa Industrias, S.A.", exchange="BME", currency="EUR", cik=None):
    company = Company(
        ticker=ticker,
        name=name,
        exchange=exchange,
        currency=currency,
        sector="S",
        industry="I",
        company_type="general",
        valuation_model="unassigned",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
        cik=cik,
    )
    db.add(company)
    db.commit()
    return company


def _fake_sec(entity_name: str):
    class _Fake:
        async def cik_for_ticker(self, ticker):
            return "0000000077"

        async def company_facts(self, cik):
            return {
                "cik": 77,
                "entityName": entity_name,
                "facts": {
                    "us-gaap": {
                        "Revenues": {
                            "units": {
                                "USD": [
                                    {
                                        "fy": 2025,
                                        "fp": "FY",
                                        "form": "10-K",
                                        "start": "2025-01-01",
                                        "end": "2025-12-31",
                                        "val": 650000000,
                                        "filed": "2026-02-20",
                                        "accn": "0000000077-26-000001",
                                    },
                                ]
                            }
                        }
                    }
                },
            }

        async def annual_report_anchors(self, cik):
            return {"0000000077-26-000001": "2025-12-31"}

    return _Fake


def _revenue(db, company):
    return list(
        db.scalars(
            select(FinancialFact).where(
                FinancialFact.company_id == company.id, FinancialFact.metric == "revenue"
            )
        )
    )


# ---- regla pura -----------------------------------------------------------


def test_listado_extranjero_con_otra_razon_social_no_casa():
    reason = sec_identity_mismatch(
        company_name="Alfa Industrias, S.A.",
        exchange="BME",
        sec_entity_name="Omega Solutions, Inc.",
    )
    assert reason is not None and "Omega Solutions" in reason


@pytest.mark.parametrize(
    ("name", "exchange", "sec_name"),
    [
        ("Novo Nordisk A/S", "OMX NORDIC EXCHANGE COPENHAGEN A/S", "NOVO NORDISK A S"),
        ("Banco Santander SA", "BOLSA DE MADRID", "BANCO SANTANDER, S.A."),
        # En EE. UU. el ticker sí identifica al emisor: nada cambia.
        ("Acme", "NASDAQ NMS - GLOBAL MARKET", "Totally Different Corp"),
        ("Acme", "OTC MARKETS", "Totally Different Corp"),
        # Sin bolsa o sin razón social de la SEC no hay nada que contrastar.
        ("Acme", "", "Totally Different Corp"),
        ("Alfa Industrias, S.A.", "BME", None),
    ],
)
def test_casos_que_siguen_aceptandose(name, exchange, sec_name):
    assert (
        sec_identity_mismatch(
            company_name=name,
            exchange=exchange,
            sec_entity_name=sec_name,
        )
        is None
    )


# ---- ingesta SEC ----------------------------------------------------------


def test_refresh_from_sec_no_atribuye_hechos_de_un_homonimo_de_eeuu(db, monkeypatch):
    monkeypatch.setattr(ingestion, "SECClient", _fake_sec("Omega Solutions, Inc."))
    company = _company(db)
    with pytest.raises(RuntimeError, match="no es el emisor"):
        asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))
    assert _revenue(db, company) == []


def test_refresh_from_sec_retira_los_hechos_y_el_cik_del_homonimo(db, monkeypatch):
    """Una ficha ya contaminada (CIK y hechos SEC del homónimo) se limpia en
    el siguiente refresco: esos hechos nunca fueron del emisor."""
    company = _company(db, cik="0000000077")
    monkeypatch.setattr(ingestion, "SECClient", _fake_sec("Alfa Industrias, S.A."))
    # Simula la contaminación previa: ingesta con la ficha aún sin contrastar.
    monkeypatch.setattr(ingestion, "sec_identity_mismatch", lambda **_: None)
    asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))
    assert _revenue(db, company)
    monkeypatch.undo()
    monkeypatch.setattr(ingestion, "_free_data_snapshot", _sin_free_data_stub)
    monkeypatch.setattr(ingestion, "SECClient", _fake_sec("Omega Solutions, Inc."))
    with pytest.raises(RuntimeError, match="no es el emisor"):
        asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))
    db.expire_all()
    assert _revenue(db, company) == []
    assert not (db.get(Company, company.id).cik or "")


async def _sin_free_data_stub(ticker, cik):
    return {"status": "skipped", "recent_filings": [], "macro": None}


def test_refresh_from_sec_sigue_igual_para_un_emisor_que_casa(db, monkeypatch):
    monkeypatch.setattr(ingestion, "SECClient", _fake_sec("ALFA INDUSTRIAS SA"))
    company = _company(db)
    result = asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))
    assert result["status"] == "ingested"
    assert len(_revenue(db, company)) == 1


def test_refresh_from_sec_listado_eeuu_no_cambia(db, monkeypatch):
    monkeypatch.setattr(ingestion, "SECClient", _fake_sec("Omega Solutions, Inc."))
    company = _company(db, name="XYZ", exchange="NYSE", currency="USD")
    result = asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))
    assert result["status"] == "ingested"


# ---- CIK de la ficha por ticker (monitor de insiders / 13D-G) -------------


def test_resolve_ciks_no_pega_el_cik_de_eeuu_a_un_listado_extranjero(db, monkeypatch):
    monkeypatch.setattr(insider_monitor, "_cik_for_ticker", lambda t, c=None: "0000000077")
    foreign = _company(db, ticker="XYZ")
    us = _company(db, ticker="ABC", name="ABC", exchange="NASDAQ", currency="USD")
    resolved = insider_monitor.resolve_ciks(db, ["XYZ", "ABC"])
    assert resolved == {"ABC": "0000000077"}
    db.expire_all()
    assert not (db.get(Company, foreign.id).cik or "")
    assert db.get(Company, us.id).cik == "0000000077"
