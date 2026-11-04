"""Capa 1 de vínculo noticia → empresa sin ticker: alias de la empresa.

Fixture: tests/fixtures/news_links/asts_v1.json (titulares realistas de AST
SpaceMobile sin «ASTS» y negativos). Garantía de equivalencia: todo texto con
evidencia de ticker (nivel > 0) se vincula exactamente igual que con
detect_ticker; los alias solo actúan donde antes no había nada.
"""

import json
import random
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.data.company_master import COMPANY_MASTER
from app.models.entities import Base, Company, NewsEvent
from app.schemas.api import NewsFeedItem
from app.services.company_aliases import (
    LINK_ABOUT,
    _name_phrase,
    generated_name_report,
    load_alias_file,
)
from app.services.news_service import NewsService

FIXTURE = Path(__file__).parent / "fixtures" / "news_links" / "asts_v1.json"

# Empresas reales que aparecen en los titulares (socios, competidores y
# homónimos de «BlueBird»), además del catálogo maestro del repo.
_EXTRA = [
    ("SPCX", "Space Exploration Technologies Corp"),
    ("T", "AT&T Inc."),
    ("VZ", "Verizon Communications Inc."),
    ("VOD", "Vodafone Group Plc"),
    ("TMUS", "T-Mobile US, Inc."),
    ("GSAT", "Globalstar, Inc."),
    ("IRDM", "Iridium Communications Inc."),
    ("AAPL", "Apple Inc."),
    ("BLBD", "Blue Bird Corporation"),
    ("BLUE", "bluebird bio, Inc."),
    ("SATS", "EchoStar Corporation"),
    ("VSAT", "Viasat, Inc."),
    ("GOOGL", "Alphabet Inc. Class A"),
    ("GOOG", "Alphabet Inc. Class C"),
    ("META", "Meta Platforms, Inc."),
    ("MSFT", "Microsoft Corporation"),
    ("AMZN", "Amazon.com, Inc."),
    ("ORAN", "Orange S.A."),
    ("TEF", "Telefonica S.A."),
]


def _add(db: Session, ticker: str, name: str) -> None:
    db.add(
        Company(
            ticker=ticker,
            name=name,
            exchange="NASDAQ",
            currency="USD",
            sector="Tech",
            industry="Tech",
            company_type="holding",
            valuation_model="unassigned",
            special_sources=[],
            special_risks=[],
            factor_tags=[],
        )
    )


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        seen: set[str] = set()
        for ticker, name in [(c["ticker"], c["name"]) for c in COMPANY_MASTER] + _EXTRA:
            if ticker not in seen:
                seen.add(ticker)
                _add(session, ticker, name)
        session.commit()
        yield session


def _cases(expect: str) -> list[str]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return [c["texto"] for c in data["casos"] if c["espera"] == expect]


def _ticker_of(db: Session, text: str) -> str | None:
    link = NewsService().detect_company_link(db, text)
    return link.company.ticker if link else None


def test_fixture_asts_tiene_el_tamano_declarado():
    assert len(_cases("sobre")) >= 20
    assert len(_cases("ninguna")) >= 40
    # Ningún titular del fixture trae el ticker: es justo lo que se mide.
    for text in _cases("sobre") + _cases("relacionada"):
        assert "ASTS" not in text


def test_hoy_detect_ticker_no_vincula_ningun_titular_de_asts(db):
    service = NewsService()
    linked = [t for t in _cases("sobre") if (c := service.detect_ticker(db, t)) and c.ticker == "ASTS"]
    assert linked == []


def test_alias_vinculan_los_titulares_sobre_asts(db):
    sobre = _cases("sobre")
    got = {t: _ticker_of(db, t) for t in sobre}
    hits = [t for t, tk in got.items() if tk == "ASTS"]
    misses = {t: tk for t, tk in got.items() if tk != "ASTS"}
    # Único fallo conocido: «AT&T» es evidencia de ticker (T) y lo que ya se
    # vinculaba por ticker no cambia (garantía de equivalencia).
    assert misses == {"SpaceMobile service beta to begin with AT&T customers next year": "T"}
    assert len(hits) / len(sobre) >= 0.95


def test_alias_dice_por_que_vinculo(db):
    service = NewsService()
    link = service.detect_company_link(
        db, "Abel Avellan says space-based cellular broadband will reach every phone"
    )
    assert link is not None
    assert (link.company.ticker, link.link_type, link.via) == ("ASTS", LINK_ABOUT, "persona:Abel Avellan")
    link = service.detect_company_link(db, "Next batch of Block 2 BlueBird satellites to fly on Falcon 9")
    assert link is not None and link.via == "alias:BlueBird"


def test_negativos_nunca_vinculan_asts(db):
    for text in _cases("ninguna"):
        assert _ticker_of(db, text) != "ASTS", text


@pytest.mark.parametrize(
    ("text", "ticker"),
    [
        ("Bluebird bio receives FDA approval for gene therapy launch", None),
        ("Eastern bluebird populations rebound across the Midwest", None),
        ("BlueBird school buses get electric upgrade", None),
        ("Blue Bird Corporation reports record school bus deliveries", "BLBD"),
        ("AST levels elevated in patients with liver disease", None),
        ("The AST of a JavaScript program is a tree", None),
        # Marca con mayúscula: «azure» como color no es Microsoft.
        ("Azure outage hits enterprise customers", "MSFT"),
        ("an azure sky over the bay", None),
        # «Google» es alias de GOOG y GOOGL a la vez: ambiguo, no se vincula.
        ("Google unveils new search features", None),
    ],
)
def test_casos_limite(db, text, ticker):
    assert _ticker_of(db, text) == ticker


def test_misma_empresa_que_detect_ticker_cuando_hay_evidencia_de_ticker(db):
    """Equivalencia: con evidencia de ticker, el vínculo es el de siempre."""
    service = NewsService()
    tickers = [c.ticker for c in db.scalars(select(Company))]
    names = [c.name for c in db.scalars(select(Company))]
    words = [
        "shares",
        "stock",
        "earnings",
        "rally",
        "price",
        "target",
        "to",
        "the",
        "NYSE:",
        "NASDAQ:",
        "(",
        ")",
        "AST",
        "SpaceMobile",
        "BlueBird",
        "satellites",
        "Abel",
        "Avellan",
        "Starlink",
        "iPhone",
        "Google",
        "AT&T",
        "launch",
    ]
    rng = random.Random(7)
    with_evidence = 0
    for _ in range(3000):
        parts = []
        for _ in range(rng.randint(3, 14)):
            roll = rng.random()
            if roll < 0.25:
                tk = rng.choice(tickers)
                parts.append(rng.choice([tk, "$" + tk, f"(NASDAQ: {tk})", tk.lower()]))
            elif roll < 0.45:
                parts.append(rng.choice(names))
            else:
                parts.append(rng.choice(words))
        text = " ".join(parts)
        company, level = service._detect_by_ticker(db, text)
        link = service.detect_company_link(db, text)
        assert company is service.detect_ticker(db, text)
        if level > 0:
            with_evidence += 1
            assert (link.company if link else None) is company, text
            assert link is None or link.via == "ticker"
        elif link is not None:
            assert link.via != "ticker"
    assert with_evidence > 500


def test_ingesta_guarda_el_vinculo_por_alias(db):
    service = NewsService()
    item = NewsFeedItem(
        title="Abel Avellan says space-based cellular broadband will reach every phone",
        text="The chief executive spoke at a satellite industry conference.",
        source="Reuters",
        url="https://news.example/avellan-broadband",
    )
    result = service.ingest_news_items(db, [item], default_source="feed")
    assert result.created == 1
    event = db.scalar(select(NewsEvent))
    asts = db.scalar(select(Company).where(Company.ticker == "ASTS"))
    assert event.company_id == asts.id
    assert event.metadata_["vinculo"] == {"ticker": "ASTS", "tipo": "sobre", "via": "persona:Abel Avellan"}


def test_ingesta_por_ticker_no_anade_metadatos_nuevos(db):
    service = NewsService()
    item = NewsFeedItem(
        title="AT&T raises dividend and beats subscriber estimates",
        text="",
        source="Reuters",
        url="https://news.example/att-dividend",
    )
    service.ingest_news_items(db, [item], default_source="feed")
    event = db.scalar(select(NewsEvent))
    assert "vinculo" not in (event.metadata_ or {})


def test_fichero_de_alias_valido():
    data = load_alias_file()
    owners: dict[str, set[str]] = {}
    for ticker, entry in data["empresas"].items():
        assert ticker == ticker.upper()
        for alias in entry.get("aliases", []):
            assert alias["termino"].strip()
            assert set(alias) <= {"termino", "tipo", "mayusculas", "requiere", "excluye", "sin_contexto", "otras_empresas"}
            owners.setdefault(alias["termino"].casefold(), set()).add(ticker)
    # Un alias curado pertenece a una sola empresa (si no, es ambiguo).
    assert {term: tks for term, tks in owners.items() if len(tks) > 1} == {}


@pytest.mark.parametrize(
    ("name", "phrase"),
    [
        ("AST SpaceMobile", "AST SpaceMobile"),
        ("Blue Bird Corporation", "Blue Bird"),
        ("Bank of America Corp", "Bank of America"),
        ("Apple Inc.", None),
        ("Amazon.com, Inc.", None),
        ("Alphabet Inc. Class A", None),
        ("The Coca-Cola Company", None),
        ("Rocket Lab USA, Inc.", "Rocket Lab USA"),
    ],
)
def test_nombre_generado(name, phrase):
    assert _name_phrase(name) == phrase


def test_nombres_ambiguos_se_marcan_y_no_se_usan(db):
    _add(db, "BLB2", "Blue Bird Corp")
    db.commit()
    report = generated_name_report(db)
    assert report["ambiguos"]["Blue Bird"] == ["BLB2", "BLBD"]
    assert "AAPL" in report["una_palabra_o_vacio"]
    assert _ticker_of(db, "Blue Bird Corporation reports record deliveries") is None
