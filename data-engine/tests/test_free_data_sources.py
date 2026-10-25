"""Fuentes gratuitas sin datos inventados.

Cubre las correcciones de la auditoría de datos fabricados:
- Cadena FMP: etiquetas de proveedor reales, readiness de valuation honesta
  y cero fabricacion cuando la fuente cae.
- registry de engines sin tickers mágicos: la decisión vive en company_master.
- claim_intelligence: confidence/materiality derivados de reglas (nunca
  constantes redondas) y marcado confidence_source="heuristic".
- news: la confianza del ExternalClaim deriva de la regla de fiabilidad de
  fuente (SOURCE_TIERS), no de un 0.65 inventado.

Tests herméticos: proveedores inyectables por constructor, sin red.
"""

import asyncio
import inspect
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, EvidenceSuggestion, ExternalClaim, FinancialFact, MarketPrice
from app.services.claim_intelligence_service import (
    ClaimIntelligenceService,
    _rule_scores,
    heuristic_statement,
)
from app.services.financial_ingestion_service import FinancialIngestionService
from app.services.news_service import NewsService
from app.services.source_hierarchy_service import classify_source
from app.valuation.engines.registry import resolve_engine_key


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session, ticker: str = "AAA", **overrides) -> Company:
    fields = dict(
        ticker=ticker,
        name=ticker,
        exchange="NASDAQ",
        currency="USD",
        sector="S",
        industry="I",
        company_type="tech",
        valuation_model="standard_dcf+x",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    fields.update(overrides)
    company = Company(**fields)
    db.add(company)
    db.commit()
    return company


# --------------------------------------------------------------------------
# (4) registry: sin tickers mágicos, decisión en company_master
# --------------------------------------------------------------------------

def test_engine_registry_sin_tickers_magicos_y_dirigido_por_master():
    import app.valuation.engines.registry as registry_module

    source = inspect.getsource(registry_module)
    # Allowlist de identidad verificada a mano (e03954e9): BN es el unico ticker
    # literal admitido; BABA/RKLB se deciden solo por company_master.
    assert '"BABA"' not in source and '"RKLB"' not in source
    assert source.count('"BN"') == 1 and "verified_engines" in source
    assert "company.ticker" not in source, "el engine jamás se decide por ticker"

    from app.data.company_master import COMPANY_MASTER

    master = {row["ticker"]: row for row in COMPANY_MASTER}
    expected = {"BN": "holding_company", "BABA": "holding_company", "RKLB": "sotp"}
    for ticker, engine_key in expected.items():
        row = master[ticker]
        # Con un ticker ajeno: la decisión viene de valuation_model/factor_tags.
        company = Company(
            ticker="ZZZ",
            name="x",
            exchange="NYSE",
            currency="USD",
            sector="x",
            industry="x",
            company_type=row["company_type"],
            valuation_model=row["valuation_model"],
            special_sources=[],
            special_risks=[],
            factor_tags=list(row["factor_tags"]),
        )
        assert resolve_engine_key(company) == engine_key, ticker
        company.ticker = ticker
        assert resolve_engine_key(company) == engine_key, ticker


# --------------------------------------------------------------------------
# (5) cadena FMP: etiquetas reales, readiness honesta, cero fabricacion
# --------------------------------------------------------------------------

class OkFMP:
    async def income_statement(self, ticker: str, limit: int = 10):
        return [
            {
                "date": "2025-09-30",
                "calendarYear": "2025",
                "period": "FY",
                "revenue": 391_035_000_000,
                "netIncome": 93_736_000_000,
                "weightedAverageShsOutDil": 15_408_000_000,
            }
        ]

    async def balance_sheet(self, ticker: str, limit: int = 10):
        return [
            {
                "date": "2025-09-30",
                "calendarYear": "2025",
                "period": "FY",
                "totalAssets": 364_980_000_000,
            }
        ]

    async def cash_flow(self, ticker: str, limit: int = 10):
        return [
            {
                "date": "2025-09-30",
                "calendarYear": "2025",
                "period": "FY",
                "freeCashFlow": 108_807_000_000,
            }
        ]

    async def ratios(self, ticker: str, limit: int = 10):
        return [
            {
                "date": "2025-09-30",
                "calendarYear": "2025",
                "period": "FY",
                "grossProfitMargin": 0.46,
            }
        ]

    async def company_profile(self, ticker: str):
        return [
            {
                "companyName": "AAA Inc.",
                "price": 21.5,
                "mktCap": 330_000_000_000,
                "currency": "USD",
            }
        ]

    async def quote(self, ticker: str):
        # Viernes de mercado: una ingesta en fin de semana debe fechar la
        # barra con el timestamp del proveedor, no con el dia de la ingesta.
        friday = datetime(2026, 9, 25, 20, 0, tzinfo=UTC)
        return [{"price": 21.5, "timestamp": int(friday.timestamp()), "volume": 4321}]


class QuoteNoTimestampFMP(OkFMP):
    async def quote(self, ticker: str):
        return [{"price": 21.5}]


class QuoteBadTimestampFMP(OkFMP):
    async def quote(self, ticker: str):
        return [{"price": 21.5, "timestamp": "no-es-un-numero"}]


class BrokenFMP:
    async def quote(self, ticker: str):
        raise RuntimeError("FMP down")

    async def income_statement(self, ticker: str, limit: int = 10):
        raise RuntimeError("FMP down")

    async def balance_sheet(self, ticker: str, limit: int = 10):
        raise RuntimeError("FMP down")

    async def cash_flow(self, ticker: str, limit: int = 10):
        raise RuntimeError("FMP down")

    async def ratios(self, ticker: str, limit: int = 10):
        raise RuntimeError("FMP down")

    async def company_profile(self, ticker: str):
        raise RuntimeError("FMP down")


def test_chain_fmp_etiquetas_reales_y_readiness(db):
    company = _company(db)
    result = asyncio.run(
        FinancialIngestionService().refresh_from_fmp(db, company, client=OkFMP())
    )
    assert result["provider"] == "FMP"
    assert result["facts_imported"] > 0

    facts = db.scalars(select(FinancialFact)).all()
    assert facts and {fact.source_type for fact in facts} <= {"FMP", "FMP_profile", "derived"}
    metrics = {fact.metric for fact in facts}
    assert {"revenue", "free_cash_flow", "shares_diluted"} <= metrics
    # revenue + FCF + shares presentes: el input de valuation esta listo.
    assert result["valuation_input_ready"] is True

    # La barra spot se fecha con el timestamp REAL de la quote (viernes),
    # nunca con el dia de la ingesta, y guarda el volumen del proveedor.
    bars = db.scalars(select(MarketPrice)).all()
    assert len(bars) == 1
    assert bars[0].date == datetime(2026, 9, 25, tzinfo=UTC).date()
    assert bars[0].volume == 4321
    assert bars[0].close == Decimal("21.5")
    # Spot no es barra ajustada: la fila nueva no afirma ajuste.
    assert bars[0].adj_close is None


def test_chain_fmp_quote_sin_timestamp_no_fabrica_barra(db):
    """Adversarial: el codigo viejo fechaba profile.price con el dia de la
    ingesta y fabricaba barras de fin de semana. Sin timestamp no hay barra."""
    company = _company(db)
    result = asyncio.run(
        FinancialIngestionService().refresh_from_fmp(
            db, company, client=QuoteNoTimestampFMP()
        )
    )
    assert result["provider"] == "FMP"
    assert result["facts_imported"] > 0
    assert db.scalars(select(MarketPrice)).all() == []


def test_chain_fmp_quote_malformada_no_tumba_el_refresh(db):
    """Un timestamp no numerico no debe propagar excepcion tras importar
    facts: el refresh termina y no se escribe barra sin fecha honesta."""
    company = _company(db)
    result = asyncio.run(
        FinancialIngestionService().refresh_from_fmp(
            db, company, client=QuoteBadTimestampFMP()
        )
    )
    assert result["provider"] == "FMP"
    assert result["facts_imported"] > 0
    assert db.scalars(select(MarketPrice)).all() == []


def test_chain_fmp_spot_no_pisa_adjusted_autentico(db):
    """Un refresh spot del mismo dia actualiza el close pero preserva OHLC y
    el adj_close real de la barra persistida por la via OHLCV."""
    company = _company(db)
    friday = datetime(2026, 9, 25, tzinfo=UTC).date()
    db.add(
        MarketPrice(
            company_id=company.id,
            date=friday,
            open=Decimal("20.0"),
            high=Decimal("22.0"),
            low=Decimal("19.5"),
            close=Decimal("21.0"),
            adj_close=Decimal("19.25"),
            volume=9000,
            source="FMP",
        )
    )
    db.flush()
    asyncio.run(
        FinancialIngestionService().refresh_from_fmp(db, company, client=OkFMP())
    )
    bars = db.scalars(select(MarketPrice)).all()
    assert len(bars) == 1
    bar = bars[0]
    assert bar.close == Decimal("21.5")
    assert bar.adj_close == Decimal("19.25")
    assert bar.open == Decimal("20.0")
    assert bar.high == Decimal("22.0")
    assert bar.low == Decimal("19.5")
    assert bar.volume == 4321


def test_chain_fmp_caido_no_fabrica_ingesta(db):
    company = _company(db)
    with pytest.raises(RuntimeError):
        asyncio.run(
            FinancialIngestionService().refresh_from_fmp(
                db, company, client=BrokenFMP()
            )
        )
    assert db.scalars(select(FinancialFact)).all() == []


# --------------------------------------------------------------------------
# (3) claim_intelligence: confidence/materiality por reglas, marcado heuristic
# --------------------------------------------------------------------------

def test_claim_fallback_scores_por_reglas_nunca_constantes(db):
    text = "AAPL raises buyback by 10%"  # <35 chars: sin frase extraíble
    statement = heuristic_statement(text)
    confidence, score = _rule_scores(text)
    assert statement.confidence == confidence
    assert statement.materiality_score == score
    # Nunca el par inventado (0.55, 5) salvo que la regla lo produzca.
    assert (round(statement.confidence, 4), statement.materiality_score) != (0.55, 5)

    rich = heuristic_statement(
        "Revenue growth record and a buyback of 5 billion expects guidance raise"
    )
    poor = heuristic_statement("something plain without numbers or markers at all")
    assert rich.materiality_score > poor.materiality_score
    assert rich.confidence > 0.52

    company = _company(db)
    service = ClaimIntelligenceService()
    result = service.scan_text(db, company=company, text=text, source_type="manual")
    assert result["suggestions"] >= 1
    row = db.scalars(select(EvidenceSuggestion)).all()[-1]
    assert row.metadata_.get("confidence_source") == "heuristic"
    assert float(row.confidence) == pytest.approx(statement.confidence)


# --------------------------------------------------------------------------
# (3) news: confianza del claim derivada de la regla de fiabilidad de fuente
# --------------------------------------------------------------------------

def test_manual_news_claim_confidence_deriva_de_regla_de_fuente(db):
    company = _company(db, ticker="AAPL", name="AAPL Co")
    service = NewsService()
    text = "AAPL beats revenue expectations with record margins in 2025 and guides higher."
    service.analyze_manual_news(db, text, "manual", None)

    claim = db.scalars(
        select(ExternalClaim).where(ExternalClaim.claim_type == "manual_news_claim")
    ).all()[-1]
    expected = round(classify_source("manual", None).trust_score, 4)
    assert float(claim.confidence) == pytest.approx(expected, abs=5e-5)
    assert float(claim.confidence) != 0.65
    assert claim.used_in_model is False
