"""detect_ticker con prefiltro por catálogo: mismo resultado que evaluar las
evidencias de todas las empresas (implementación de referencia de abajo)."""

import random

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company
from app.services.company_catalog import all_companies
from app.services.news_service import (
    STRICT_TICKERS,
    NewsService,
    _ticker_evidence_level,
)


def _reference_detect(db: Session, text: str) -> Company | None:
    """detect_ticker tal y como era: todas las empresas, sin prefiltro."""
    best_level = 0
    best: list[Company] = []
    for company in all_companies(db):
        level = _ticker_evidence_level(company.ticker, company.name, text)
        if level > best_level:
            best_level, best = level, [company]
        elif level == best_level and level > 0:
            best.append(company)
    return best[0] if len(best) == 1 else None


_STRICT = sorted(STRICT_TICKERS)[:6]
_TICKERS = [
    "AAPL", "MSFT", "IT", "ON", "A", "ALL", "CB", "BRK.B", "ITX.MC", "SAN", "BBVA", "KO",
    "IBM", "AI", "SKY", "KSS", "SI", "IIPR", "T", "F", "NVDA", "AMZN", "META", "OKTA",
    "RKLB", "ASTS", "ZETA", "COST", "AENA", "MO", "PM", "SO", "BE", "NOW",
] + [t for t in _STRICT if t not in {"CB", "AENA"}]
_NAMES = [
    "Apple Inc", "Microsoft Corp", "Gartner Inc", "ON Semiconductor", "Agilent Technologies",
    "Allstate Corp", "Chubb Limited", "Berkshire Hathaway", "Industria de Diseno Textil",
    "Banco Santander", "Banco Bilbao Vizcaya", "Coca-Cola Company", "International Business Machines",
    "C3.ai Inc", "Sky Harbour", "Kohl's Corp", "SiriusPoint", "Innovative Industrial Properties",
    "AT&T Inc", "Ford Motor", "Nvidia Corp", "Amazon.com", "Meta Platforms", "Okta Inc",
    "Rocket Lab", "AST SpaceMobile", "Zeta Global", "Costco Wholesale", "Aena SME", "Altria Group",
    "Philip Morris", "Southern Company", "Bloom Energy", "ServiceNow",
]
_WORDS = [
    "shares", "stock", "earnings", "rally", "price", "target", "to", "$300", "at", "the", "on",
    "it", "all", "a", "new", "deal", "acciones", "bolsa", "guidance", "fell", "rose", "today",
    "NYSE:", "NASDAQ:", "(", ")", "cornerback", "Target", "visado", "aeropuerto",
]


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        for i, ticker in enumerate(_TICKERS):
            session.add(Company(
                ticker=ticker, name=_NAMES[i] if i < len(_NAMES) else f"{ticker} Holdings",
                exchange="NYSE", currency="USD", sector="Tech", industry="Tech",
                company_type="holding", valuation_model="unassigned",
                special_sources=[], special_risks=[], factor_tags=[],
            ))
        session.commit()
        yield session


def _variant(token: str, rng: random.Random) -> str:
    roll = rng.random()
    if roll < 0.15:
        return "$" + token
    if roll < 0.25:
        return token.lower()
    if roll < 0.3:
        return f"(NYSE: {token})"
    if roll < 0.34:
        # Formas que re.IGNORECASE iguala a letras ASCII: «ı» sin punto, «ſ», Kelvin.
        return token.replace("I", "\u0131").replace("S", "\u017f").replace("K", "\u212a")
    return token


def _random_text(rng: random.Random) -> str:
    parts: list[str] = []
    for _ in range(rng.randint(3, 18)):
        roll = rng.random()
        if roll < 0.3:
            parts.append(_variant(rng.choice(_TICKERS), rng))
        elif roll < 0.5:
            parts.append(rng.choice(_NAMES).split()[0])
        else:
            parts.append(rng.choice(_WORDS))
    return " ".join(parts)


def test_detect_ticker_igual_que_referencia_en_textos_aleatorios(db):
    rng = random.Random(1234)
    service = NewsService()
    linked = 0
    for _ in range(4000):
        text = _random_text(rng)
        expected = _reference_detect(db, text)
        got = service.detect_ticker(db, text)
        assert (got.id if got else None) == (expected.id if expected else None), text
        linked += expected is not None
    assert linked > 200  # el fixture ejercita vínculos reales, no solo «ninguna»


@pytest.mark.parametrize("text", [
    "$aapl jumps after earnings",
    "Apple (NASDAQ: AAPL) beats",
    "CB Target J. Cobbins signs",
    "Chubb (CB) price target raised",
    "Berkshire BRK.B shares",
    "ON Semiconductor shares slide",
    "it is all a new deal",
    "$\u0131bm rally",
    "Gartner IT stock",
    "",
])
def test_detect_ticker_casos_conocidos(db, text):
    expected = _reference_detect(db, text)
    got = NewsService().detect_ticker(db, text)
    assert (got.id if got else None) == (expected.id if expected else None)


def test_catalogo_nuevo_reconstruye_el_prefiltro(db):
    service = NewsService()
    assert service.detect_ticker(db, "$ZZZQ soars") is None
    db.add(Company(
        ticker="ZZZQ", name="Zzzq Labs", exchange="NYSE", currency="USD", sector="Tech",
        industry="Tech", company_type="holding", valuation_model="unassigned",
        special_sources=[], special_risks=[], factor_tags=[],
    ))
    db.flush()
    found = service.detect_ticker(db, "$ZZZQ soars")
    assert found is not None and found.ticker == "ZZZQ"
