"""Selección automática de comparables: misma industria, o sector y un factor real más.

Sin ``PeerRelationship`` curadas el grupo de comparables sale del selector
multifactor. Antes bastaba cualquier puntuación > 0: compartir sector (o
incluso solo divisa + bolsa + tamaño) metía a minoristas y hoteles de EE. UU.
como comparables de un comercio electrónico chino. Ahora un candidato entra
solo si comparte industria, o sector y al menos un factor de negocio más
(etiquetas de negocio compartidas); un tamaño parecido solo ordena. Una cotización extranjera o un ADR
puede tomar pares de cualquier región, pero solo de su industria. Con menos
de 3 candidatos válidos el contraste por múltiplos no se publica.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Company, FinancialFact, MarketPrice, PeerRelationship
from app.models.entities import Base
from app.services.peer_comparison_service import (
    NO_SAME_INDUSTRY_PEERS_REASON,
    PEER_SIZE_BAND_MAX_RATIO,
    PeerComparisonService,
)
from app.valuation.engines.relative_multiples import RelativeMultiplesEngine

PRICE_DAY = date(2026, 1, 2)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = 1
        yield session


def _company(db, ticker, *, sector, industry, exchange="NYSE", tags=(), cap=None,
             domicile="US", currency="USD", cik=None):
    row = Company(
        ticker=ticker, name=f"{ticker} test", exchange=exchange, currency=currency,
        sector=sector, industry=industry, company_type="research_candidate",
        valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=list(tags), domicile_country=domicile, cik=cik,
    )
    db.add(row)
    db.flush()
    if cap is not None:
        db.add(FinancialFact(
            tenant_id=1, company_id=row.id, metric="market_cap", period="FY2025",
            fiscal_year=2025, value=Decimal(str(cap)), unit="USD", source_type="peer_test",
        ))
    return row


def _find(db, company, limit=8):
    db.commit()
    peers, basis, trace = PeerComparisonService()._find_peers(db, company, limit)
    return [peer.ticker for peer in peers], basis, trace


def test_caso_tipo_baba_sin_minoristas_ni_hoteles_de_eeuu(db):
    """ADR chino con industria propia: los que solo comparten sector no entran,
    aunque tengan el mismo tamaño."""
    baba = _company(db, "BABAX", sector="Consumer Discretionary",
                    industry="China ecommerce and cloud", tags=("china", "adr:8", "ecommerce", "cloud"),
                    cap=240_000, domicile="HK")
    for ticker, industry in (("MCDX", "Hotels, Restaurants & Leisure"), ("HDX", "Retail"),
                             ("COSTX", "Retail"), ("BKNGX", "Hotels, Restaurants & Leisure"),
                             ("MARX", "Hotels, Restaurants & Leisure")):
        _company(db, ticker, sector="Consumer Discretionary", industry=industry, cap=220_000)
    peers, basis, trace = _find(db, baba)
    assert peers == []
    assert trace["eligible_count"] == 0
    assert trace["insufficient_reason"] == NO_SAME_INDUSTRY_PEERS_REASON


def test_misma_industria_gana_y_solo_sector_sin_factor_queda_fuera(db):
    target = _company(db, "KOX", sector="Consumer Staples", industry="Beverages", cap=280_000)
    for ticker in ("PEPX", "KDPX", "MNSTX"):
        _company(db, ticker, sector="Consumer Staples", industry="Beverages", cap=40_000)
    # Mismo sector, sin etiquetas compartidas y más de 3x de tamaño: fuera.
    for ticker in ("WMTX", "PGX"):
        _company(db, ticker, sector="Consumer Staples", industry="Household Products", cap=5_000)
    # Ni sector: fuera aunque comparta divisa, bolsa y tamaño.
    _company(db, "JPMX", sector="Financials", industry="Banks", cap=280_000)
    peers, _basis, trace = _find(db, target)
    assert sorted(peers) == ["KDPX", "MNSTX", "PEPX"]
    assert trace["eligible_count"] == 3
    assert trace.get("insufficient_reason") is None
    rows = {row["ticker"]: row for row in trace["candidates"]}
    assert rows["PEPX"]["eligibility"] == "industry"
    assert "JPMX" not in rows and "WMTX" not in rows


def test_sector_mas_un_factor_real_entra(db):
    target = _company(db, "GOOGX", sector="Communication Services", industry="Media",
                      tags=("ads", "ai"), cap=2_000_000)
    _company(db, "TAGX", sector="Communication Services", industry="Interactive",
             tags=("ads",), cap=10_000)
    _company(db, "TAGY", sector="Communication Services", industry="Search",
             tags=("ai",), cap=2_000_000 / float(PEER_SIZE_BAND_MAX_RATIO) + 1)
    _company(db, "FARX", sector="Communication Services", industry="Telecom", cap=10_000)
    peers, _basis, trace = _find(db, target)
    assert sorted(peers) == ["TAGX", "TAGY"]
    rows = {row["ticker"]: row for row in trace["candidates"]}
    assert rows["TAGX"]["eligibility"] == "sector+factor_tags"
    assert rows["TAGY"]["eligibility"] == "sector+factor_tags+size_band"
    assert trace["insufficient_reason"] == NO_SAME_INDUSTRY_PEERS_REASON


def test_sector_y_tamano_parecido_sin_negocio_comun_no_basta(db):
    """Operador de satélites vs discográficas y prensa del mismo tamaño: los
    dos son «Communication Services», pero el tamaño no es negocio."""
    target = _company(db, "SATX", sector="Communication Services",
                      industry="Satellite telecom", tags=("satellite",), cap=10_000)
    for index in range(4):
        _company(db, f"MUSX{index}", sector="Communication Services", industry="Music",
                 tags=("streaming",), cap=10_000 + index)
    peers, _basis, trace = _find(db, target)
    assert peers == []
    assert trace["insufficient_reason"] == NO_SAME_INDUSTRY_PEERS_REASON


def test_dentro_de_la_industria_ordena_el_tamano_en_escala_logaritmica(db):
    """Un gigante no empata con todas las microcaps de su industria: el más
    parecido en tamaño va primero aunque esté a más de 10x."""
    target = _company(db, "BIGX", sector="Communication Services", industry="Media",
                      cap=2_000_000)
    _company(db, "AAMICRO", sector="Communication Services", industry="Media", cap=2_000)
    _company(db, "ABSMALL", sector="Communication Services", industry="Media", cap=20_000)
    _company(db, "ZZLARGE", sector="Communication Services", industry="Media", cap=200_000)
    peers, _basis, _trace = _find(db, target)
    assert peers == ["ZZLARGE", "ABSMALL", "AAMICRO"]


def test_cotizacion_extranjera_exige_industria(db):
    target = _company(db, "SAPX", sector="Information Technology", industry="Software",
                      exchange="XETRA", tags=("software",), cap=300_000, domicile="DE", currency="EUR")
    _company(db, "ORCLX", sector="Information Technology", industry="Software", cap=400_000)
    _company(db, "AAPLX", sector="Information Technology", industry="Hardware",
             tags=("software",), cap=300_000)
    peers, _basis, _trace = _find(db, target)
    assert peers == ["ORCLX"]


def test_relaciones_curadas_siguen_mandando(db):
    target = _company(db, "BABAX", sector="Consumer Discretionary",
                      industry="China ecommerce and cloud", tags=("adr:8",), cap=240_000, domicile="HK")
    curated = [_company(db, f"C{i}", sector="Industrials", industry="Logistics") for i in range(3)]
    for peer in curated:
        db.add(PeerRelationship(company_id=target.id, peer_company_id=peer.id, score=Decimal("0.9"),
                                selected=True, rationale=["manual"], selection_trace={}))
    peers, basis, trace = _find(db, target)
    assert peers == ["C0", "C1", "C2"]
    assert basis == "manual_then_multifactor"
    assert trace.get("insufficient_reason") is None


def _with_fundamentals(db, company, price=40.0):
    for metric, value in {"eps": 2.0, "revenue": 1000.0, "free_cash_flow": 100.0, "total_debt": 200.0,
                          "cash_and_equivalents": 50.0, "shares_diluted": 100.0, "book_value": 400.0,
                          "ebitda": 150.0}.items():
        db.add(FinancialFact(
            company_id=company.id, metric=metric, value=Decimal(str(value)), unit="USD",
            period="FY2025", fiscal_year=2025, fiscal_quarter="FY", source_type="peer_test",
            is_reported=True, confidence=Decimal("0.90"),
        ))
    db.add(MarketPrice(company_id=company.id, date=PRICE_DAY, close=Decimal(str(price)),
                       adj_close=Decimal(str(price)), source="peer_test"))
    db.commit()


def test_con_menos_de_tres_comparables_validos_no_se_publica_el_contraste(db):
    target = _company(db, "SUBJ", sector="Industrials", industry="Machinery")
    _with_fundamentals(db, target, 20.0)
    for ticker in ("M1", "M2"):
        _with_fundamentals(db, _company(db, ticker, sector="Industrials", industry="Machinery"))
    for ticker in ("S1", "S2", "S3", "S4"):  # solo sector, sin factor: no cuentan
        _with_fundamentals(db, _company(db, ticker, sector="Industrials", industry="Airlines"))
    engine = RelativeMultiplesEngine()
    result = engine.value(engine.build_context(db, target, 20.0))
    assert result["status"] == "insufficient_data"
    assert result["base_value"] is None and result["expected_value"] is None
    assert NO_SAME_INDUSTRY_PEERS_REASON in result["trace"]["reason"]
    assert result["trace"]["peer_set"]["fallback_only"] is True


def test_misma_industria_va_antes_que_sector_mas_factor(db):
    target = _company(db, "TSLX", sector="Consumer Discretionary", industry="Automobiles",
                      tags=("auto", "ai"), cap=1_000_000)
    for ticker in ("FX", "GMX", "RIVNX"):
        _company(db, ticker, sector="Consumer Discretionary", industry="Automobiles", cap=20_000)
    _company(db, "AMZNX", sector="Consumer Discretionary", industry="Broadline Retail",
             tags=("ai",), cap=1_000_000)
    peers, _basis, _trace = _find(db, target, limit=3)
    assert sorted(peers) == ["FX", "GMX", "RIVNX"]


def test_otra_clase_del_mismo_emisor_no_es_comparable_y_cuenta_una_vez(db):
    target = _company(db, "GOOGLX", sector="Communication Services", industry="Media", cik="0001652044")
    _company(db, "GOOGX", sector="Communication Services", industry="Media", cik="1652044")
    _company(db, "BFAX", sector="Communication Services", industry="Media", cik="0000014693")
    bfb = _company(db, "BFBX", sector="Communication Services", industry="Media")
    bfb.name = "BFAX test Class B"  # sin CIK: mismo emisor por el nombre
    _company(db, "NYTX", sector="Communication Services", industry="Media")
    peers, _basis, trace = _find(db, target)
    assert "GOOGX" not in peers
    assert len([ticker for ticker in peers if ticker.startswith("BF")]) == 1
    assert trace["eligible_count"] == 2


def test_industria_con_otra_taxonomia_por_palabras(db):
    """«Electric Utilities» y «Utilities» son la misma industria en dos
    taxonomías; una cotización extranjera las acepta."""
    target = _company(db, "IBEX", sector="Utilities", industry="Electric Utilities",
                      exchange="BME", domicile="ES", currency="EUR")
    for ticker in ("NEEX", "SOX", "DUKX"):
        _company(db, ticker, sector="Utilities", industry="Utilities")
    _company(db, "WATX", sector="Utilities", industry="Water")
    peers, _basis, trace = _find(db, target)
    assert sorted(peers) == ["DUKX", "NEEX", "SOX"]
    assert {row["eligibility"] for row in trace["candidates"]} == {"industry_keywords"}
