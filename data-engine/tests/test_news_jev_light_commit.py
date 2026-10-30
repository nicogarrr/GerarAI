"""Regresión: la vía ligera Jev (duplicate/noise) persistía el evento solo
si el llamador commiteaba.

``_analyze_news`` commitea dentro de ``scan_text`` (vía completa con empresa)
y tenía un commit explícito para eventos sin empresa, pero la vía ligera Jev
con empresa no corría ninguno de los dos. Los workers de ingesta
(refresh_news, refresh_ticker_news, refresh_rss_feeds) cierran la sesión sin
commit propio, así que un duplicado/ruido detectado por Jev se perdía en
silencio y el siguiente barrido volvía a ingerirlo y a pagar su gate Jev en
vez de detectarlo como duplicado en el tracker.
"""

from __future__ import annotations

from unittest.mock import Mock, patch

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company, ExternalClaim, NewsEvent
from app.schemas import NewsFeedItem
from app.services import jev_gates
from app.services.news_service import NewsService


class _JevDecision:
    def __init__(self, label: str, confidence: float) -> None:
        self.label = label
        self.confidence = confidence


def _memdb():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _company(ticker: str) -> Company:
    return Company(
        ticker=ticker,
        name=f"{ticker} Test",
        exchange="TEST",
        currency="USD",
        sector="Test",
        industry="Test",
        company_type="standard",
        valuation_model="standard_dcf",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )


_NEWS_TEXT = (
    "TST board approves routine bylaw update. TST shares were little changed. "
    "TST said the change is administrative."
)


def _counts(engine) -> tuple[int, int]:
    with Session(engine) as db:
        news = db.scalar(select(func.count()).select_from(NewsEvent)) or 0
        claims = db.scalar(select(func.count()).select_from(ExternalClaim)) or 0
    return news, claims


def test_via_ligera_persiste_sin_commit_del_llamador():
    """Worker que cierra la sesión sin commit: el evento ligero debe quedar."""
    engine = _memdb()
    with Session(engine) as db:
        db.add(_company("TST"))
        db.commit()
    svc = NewsService()
    scan = Mock()
    with (
        patch.object(svc.claim_intelligence, "scan_text", scan),
        patch.object(
            jev_gates,
            "jev_news_action_sync",
            return_value=_JevDecision("duplicate", 0.91),
        ),
    ):
        with Session(engine) as db:
            resp = svc._analyze_news(db, _NEWS_TEXT, "feed", "https://medio.example/tst-1")
        # Sin commit del llamador: la sesión se cierra como en el worker.
    news, claims = _counts(engine)
    assert resp.requires_update is False
    assert scan.call_count == 0
    assert news == 1
    assert claims == 1
    assert any("jev_news_action(duplicate" in r for r in resp.materiality_reasons)


def test_via_ligera_la_reingesta_detecta_el_duplicado():
    """Persistido el primer evento, el siguiente barrido no lo recrea ni
    vuelve a llamar al gate Jev sobre la misma URL."""
    engine = _memdb()
    with Session(engine) as db:
        db.add(_company("TST"))
        db.commit()
    svc = NewsService()
    decision = _JevDecision("duplicate", 0.91)
    jev = Mock(return_value=decision)
    item = NewsFeedItem(
        title="TST board approves routine bylaw update",
        text=_NEWS_TEXT,
        ticker="TST",
        url="https://medio.example/tst-1",
        source="Yahoo Finance",
    )
    with patch.object(jev_gates, "jev_news_action_sync", jev):
        with Session(engine) as db:
            first = svc.ingest_news_items(db, [item], default_source="Yahoo Finance", connector="rss")
        with Session(engine) as db:
            second = svc.ingest_news_items(db, [item], default_source="Yahoo Finance", connector="rss")
    news, _ = _counts(engine)
    assert first.created == 1
    assert second.created == 0
    assert second.skipped_duplicates == 1
    assert news == 1
    # La segunda ingesta se descartó por duplicado ANTES del gate Jev.
    assert jev.call_count == 1


def test_via_completa_sigue_persistiendo_sin_commit_del_llamador():
    """Regresión del arreglo: la vía completa (scan_text commitea dentro)
    sigue persistiendo igual."""
    engine = _memdb()
    with Session(engine) as db:
        db.add(_company("TST"))
        db.commit()
    svc = NewsService()
    with patch.object(jev_gates, "jev_news_action_sync", return_value=None):
        with Session(engine) as db:
            resp = svc._analyze_news(db, _NEWS_TEXT, "feed", "https://medio.example/tst-2")
    news, claims = _counts(engine)
    assert news == 1
    assert claims == 1
    assert not any("jev_news_action" in r for r in resp.materiality_reasons)


def test_sin_empresa_sigue_persistiendo_sin_commit_del_llamador():
    """Carril sin empresa (macro/gobierno): comportamiento ya cubierto, se fija."""
    engine = _memdb()
    svc = NewsService()
    with Session(engine) as db:
        svc._analyze_news(
            db,
            "La Fed mantiene los tipos y avisa de inflación persistente.",
            "Reserva Federal (oficial)",
            "https://www.federalreserve.gov/example.htm",
        )
    news, claims = _counts(engine)
    assert news == 1
    assert claims == 1
