"""Fuentes para emisores sin SEC en la tesis: orden de fuentes y valores dorados.

Valores dorados cotejados A MANO contra los documentos del propio emisor
(2026-10-27), no contra Yahoo:

- Georgia Capital PLC (CGEO.L, GEL), Annual Report 2025 depositado en el NSM
  de la FCA (NI-000143657): NAV/patrimonio 5.194.527 k, activos 5.198.380 k,
  pasivos 3.853 k, caja 13.495 k, beneficio 1.892.642 k, BPA diluido
  54,0296, flujo de explotacion -5.838 k; FY2024 3.609.013 / 3.611.317 /
  2.304 / 3.521 / 362.274 / 9,2987 / -6.400.
- Kraken Robotics (KRKNF -> PNG.V, CAD), notas de resultados 2025 y 2024:
  ingresos 102,2 M / 91,3 M, beneficio neto 2.860 k / 20.089 k, activos
  313,7 M / 162,6 M, caja 120,5 M / 58,5 M.

Los DataFrames simulan la respuesta de Yahoo del 2026-10-27 (sin red en
tests); la "Total Revenue" de Yahoo para CGEO (1.900.030 k) no existe en el
informe y debe quedar fuera.
"""

from decimal import Decimal
from functools import partial

import pandas as pd
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, Document, FinancialFact
from app.services import yahoo_fundamentals_service as yfs
from app.services.fundamentals_fallback import ingest_with_fallback
from app.services.thesis_evidence_service import ThesisEvidenceService
from app.services.yahoo_fundamentals_service import refresh_from_yahoo

NAN = float("nan")
Y25, Y24 = pd.Timestamp("2025-12-31"), pd.Timestamp("2024-12-31")
SEC_PENDING = {
    "status": "pending",
    "source": "SEC EDGAR companyfacts",
    "detail": "Sin CIK no hay companyfacts (empresa no filer USA o EDGAR inaccesible).",
}


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db, ticker, name):
    c = Company(
        ticker=ticker,
        name=name,
        exchange="X",
        currency="USD",
        sector="S",
        industry="I",
        company_type="research_candidate",
        valuation_model="unassigned",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(c)
    db.commit()
    return c


def _frame(rows: dict[str, tuple[float, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        {Y25: [v[0] for v in rows.values()], Y24: [v[1] for v in rows.values()]},
        index=list(rows),
    )


def _cgeo_yahoo(symbol):
    assert symbol == "CGEO.L"
    return {
        "name": "Georgia Capital PLC",
        "currency": "GEL",
        "income": _frame(
            {
                "Total Revenue": (1900030000.0, 368023000.0),  # no aparece en el informe
                "Operating Income": (NAN, NAN),
                "Net Income": (1892642000.0, 362274000.0),
                "Pretax Income": (1892642000.0, 362274000.0),
                "Diluted EPS": (54.0296, 9.2987),
                "Diluted Average Shares": (35029724.0, 38959640.0),
            }
        ),
        "balance": _frame(
            {
                "Total Assets": (5198380000.0, 3611317000.0),
                "Total Liabilities Net Minority Interest": (3853000.0, 2304000.0),
                "Stockholders Equity": (5194527000.0, 3609013000.0),
                "Cash And Cash Equivalents": (13495000.0, 3521000.0),
            }
        ),
        "cashflow": _frame(
            {
                "Operating Cash Flow": (-5838000.0, -6400000.0),
                "Free Cash Flow": (-5838000.0, -6400000.0),
            }
        ),
    }


def _krknf_yahoo(symbol):
    assert symbol == "PNG.V"
    return {
        "name": "Kraken Robotics Inc.",
        "currency": "CAD",
        "income": _frame(
            {
                "Total Revenue": (102210000.0, 91292000.0),
                "Net Income": (2860000.0, 20089000.0),
            }
        ),
        "balance": _frame(
            {
                "Total Assets": (313679000.0, 162613000.0),
                "Cash And Cash Equivalents": (120507000.0, 58518000.0),
            }
        ),
        "cashflow": pd.DataFrame(),
    }


def _values(db, company):
    facts = db.scalars(select(FinancialFact).where(FinancialFact.company_id == company.id)).all()
    return {(f.metric, f.fiscal_year): f for f in facts}


# Valores en unidades del informe (miles de GEL) -> unidades guardadas.
CGEO_GOLDEN_K = {
    ("total_equity", 2025): 5_194_527,
    ("total_equity", 2024): 3_609_013,
    ("total_assets", 2025): 5_198_380,
    ("total_assets", 2024): 3_611_317,
    ("total_liabilities", 2025): 3_853,
    ("total_liabilities", 2024): 2_304,
    ("cash_and_equivalents", 2025): 13_495,
    ("cash_and_equivalents", 2024): 3_521,
    ("net_income", 2025): 1_892_642,
    ("net_income", 2024): 362_274,
    ("operating_cash_flow", 2025): -5_838,
    ("operating_cash_flow", 2024): -6_400,
}


def test_cgeo_valores_dorados_del_informe_anual(db):
    company = _company(db, "CGEO.L", "Georgia Capital PLC")
    out = refresh_from_yahoo(db, company, fetcher=_cgeo_yahoo)
    got = _values(db, company)
    for key, thousands in CGEO_GOLDEN_K.items():
        assert got[key].value == Decimal(thousands) * 1000, key
        assert got[key].unit == "GEL"
        assert got[key].is_reported is False
    assert got[("eps_diluted", 2025)].value == Decimal("54.0296")
    assert got[("eps_diluted", 2025)].unit == "GEL/share"
    # Entidad de inversion: Yahoo sintetiza "Total Revenue" y el informe no la
    # publica -> fuera por la lista blanca revisada.
    assert not {m for m, _ in got} & {"revenue", "gross_profit", "operating_income"}
    assert out["currency"] == "GEL"


def test_krknf_valores_dorados_de_las_notas_de_resultados(db):
    company = _company(db, "KRKNF", "Kraken Robotics")
    refresh_from_yahoo(db, company, fetcher=_krknf_yahoo)
    got = _values(db, company)
    assert got[("revenue", 2025)].value == Decimal("102210000")  # 102,2 M CAD
    assert got[("revenue", 2024)].value == Decimal("91292000")  # 91,3 M CAD
    assert got[("net_income", 2025)].value == Decimal("2860000")
    assert got[("net_income", 2024)].value == Decimal("20089000")
    assert got[("total_assets", 2025)].value == Decimal("313679000")
    assert got[("cash_and_equivalents", 2024)].value == Decimal("58518000")
    assert {f.unit for f in got.values()} == {"CAD"}


def test_procedencia_en_cada_hecho_fuente_documento_y_fecha(db):
    company = _company(db, "CGEO.L", "Georgia Capital PLC")
    out = refresh_from_yahoo(db, company, fetcher=_cgeo_yahoo)
    fact = _values(db, company)[("total_equity", 2025)]
    doc = db.get(Document, fact.source_id)
    assert fact.source_type == "YAHOO_FUNDAMENTALS"
    assert "fuente no oficial" in doc.title
    assert doc.source_url == "https://finance.yahoo.com/quote/CGEO.L/financials"
    assert doc.metadata_["last_refreshed_at"] == out["retrieved_at"]
    assert any("NI-000143657" in url for url in doc.metadata_["verified_against"])
    assert fact.period == "2025-12-31:FY"


def test_ficha_sin_nombre_usa_los_nombres_revisados_y_un_nombre_distinto_bloquea(db):
    stub = _company(db, "CGEO.L", "CGEO.L")  # ensure_company_stub sin enriquecer
    assert refresh_from_yahoo(db, stub, fetcher=_cgeo_yahoo)["facts_imported"] > 0
    other = _company(db, "KRKNF", "Kraken Energy Corp")
    with pytest.raises(RuntimeError, match="company_mismatch"):
        refresh_from_yahoo(db, other, fetcher=_krknf_yahoo)


def test_tesis_sin_cik_recorre_el_orden_y_usa_yahoo_revisado(db, monkeypatch):
    company = _company(db, "CGEO.L", "Georgia Capital PLC")
    monkeypatch.setattr(yfs, "refresh_from_yahoo", partial(yfs.refresh_from_yahoo, fetcher=_cgeo_yahoo))
    monkeypatch.setattr(
        ThesisEvidenceService, "_ingest_fundamentals", lambda self, db, c, cik: dict(SEC_PENDING)
    )
    block = ThesisEvidenceService()._ingest_fundamentals_with_fallback(db, company, None)
    assert block["status"] == "ok" and block["official"] is False
    assert block["source"] == "Yahoo Finance (fuente no oficial)"
    assert block["currency"] == "GEL" and block["facts_imported"] == 20
    assert [step["source"] for step in block["fallback_chain"]] == [
        "SEC EDGAR companyfacts",
        "ESEF/CNMV guardado",
        "Yahoo Finance (fuente no oficial)",
    ]
    assert [step["status"] for step in block["fallback_chain"]] == ["pending", "sin_datos", "ok"]


def test_fallback_solo_hace_flush_la_tesis_corre_en_un_savepoint(db):
    company = _company(db, "KRKNF", "Kraken Robotics")
    outer = db.begin_nested()
    block = ingest_with_fallback(
        db, company, dict(SEC_PENDING), yahoo_refresh=partial(refresh_from_yahoo, fetcher=_krknf_yahoo)
    )
    assert block["status"] == "ok"
    assert _values(db, company)
    outer.rollback()  # la tesis revierte su savepoint: no queda nada commiteado
    assert not _values(db, company)


def test_fallo_de_la_fuente_no_rompe_la_tesis_y_no_deja_restos(db):
    company = _company(db, "KRKNF", "Kraken Robotics")

    def _boom(db, company, commit=True):
        db.add(
            FinancialFact(
                company_id=company.id,
                metric="revenue",
                value=Decimal(1),
                unit="CAD",
                period="2025-12-31:FY",
                fiscal_year=2025,
                fiscal_quarter="FY",
                source_type="YAHOO_FUNDAMENTALS",
            )
        )
        db.flush()
        raise TimeoutError("yahoo caido")

    block = ingest_with_fallback(db, company, dict(SEC_PENDING), yahoo_refresh=_boom)
    assert block["status"] == "pending"
    assert block["fallback_chain"][-1]["status"] == "error"
    assert "yahoo caido" in block["fallback_chain"][-1]["detail"]
    assert not _values(db, company)


def test_sec_ok_no_se_toca_y_ticker_sin_mapa_queda_pendiente(db):
    sec_ok = {"status": "ok", "source": "SEC EDGAR companyfacts", "facts_imported": 3}
    company = _company(db, "AAPL", "Apple")
    assert ingest_with_fallback(db, company, sec_ok) is sec_ok
    block = ingest_with_fallback(db, company, dict(SEC_PENDING))
    assert block["status"] == "pending"
    assert block["fallback_chain"][-1]["status"] == "no_aplica"


def test_hechos_oficiales_guardados_mandan_sobre_yahoo(db):
    company = _company(db, "ITX.MC", "Industria de Diseno Textil")
    doc = Document(company_id=company.id, title="ESEF", source_type="ESEF")
    db.add(doc)
    db.flush()
    db.add(
        FinancialFact(
            company_id=company.id,
            metric="revenue",
            value=Decimal(1),
            unit="EUR",
            period="2025-01-31:FY",
            fiscal_year=2024,
            fiscal_quarter="FY",
            source_id=doc.id,
            source_type="ESEF",
            tenant_id="tenant-test",
        )
    )
    db.commit()
    block = ingest_with_fallback(db, company, dict(SEC_PENDING))
    assert block["status"] == "ok" and block["official"] is True
    assert block["source"] == "ESEF/CNMV guardado" and block["already_present"] == 1
