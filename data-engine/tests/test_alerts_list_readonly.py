"""GET /api/alerts: filtro de snooze correcto y respuesta sin mutar el ORM."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.routes.alerts import list_alerts
from app.models.entities import Base, Company, ResearchAlert


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _seed(db: Session) -> dict[str, ResearchAlert]:
    company = Company(
        ticker="AAPL", name="Apple", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.flush()
    now = datetime.now(UTC)
    alerts = {}
    for key, status, until in [
        ("open", "open", None),
        ("future", "snoozed", now + timedelta(hours=2)),
        ("indefinite", "snoozed", None),
        ("expired", "snoozed", now - timedelta(hours=2)),
    ]:
        alert = ResearchAlert(
            company_id=company.id, alert_type="price_above", severity="high",
            title=f"AAPL {key}", message="m", fingerprint=f"fp-{key}",
            channels=["in_app"], status=status, snoozed_until=until,
        )
        db.add(alert)
        alerts[key] = alert
    db.commit()
    return alerts


def test_snooze_indefinite_stays_hidden_and_expired_reappears(db):
    _seed(db)
    result = list_alerts(ticker=None, status=None, include_snoozed=False, limit=100, db=db)
    by_title = {a.title: a for a in result}

    assert "AAPL open" in by_title
    # Snooze activo (futuro) e indefinido (sin fecha): ocultos por defecto.
    assert "AAPL future" not in by_title
    assert "AAPL indefinite" not in by_title
    # Snooze caducado: reaparece como 'open' derivado.
    assert by_title["AAPL expired"].status == "open"
    assert by_title["AAPL expired"].snoozed_until is None

    # Con include_snoozed=True salen todas.
    everything = list_alerts(ticker=None, status=None, include_snoozed=True, limit=100, db=db)
    assert {a.title for a in everything} == {
        "AAPL open", "AAPL future", "AAPL indefinite", "AAPL expired",
    }


def test_list_alerts_includes_ticker_for_actionable_history(db):
    """F146: el historial de disparos necesita el ticker para enlazar a la
    investigacion; alertas sin compania devuelven ticker=None, nunca inventado."""
    _seed(db)
    result = list_alerts(ticker=None, status=None, include_snoozed=True, limit=100, db=db)
    tickers = {out.title: out.ticker for out in result}
    assert tickers == {
        "AAPL open": "AAPL",
        "AAPL future": "AAPL",
        "AAPL indefinite": "AAPL",
        "AAPL expired": "AAPL",
    }
    orphan = ResearchAlert(
        company_id=None, alert_type="red_team", severity="medium",
        title="sin compania", message="m", fingerprint="fp-orphan",
        channels=["in_app"], status="open",
    )
    db.add(orphan)
    db.commit()
    result = list_alerts(ticker=None, status=None, include_snoozed=True, limit=100, db=db)
    by_title = {out.title: out for out in result}
    assert by_title["sin compania"].ticker is None


def test_list_alerts_orders_by_real_last_trigger(db):
    """F146: un re-disparo reciente de huella antigua debe salir primero."""
    from app.services.review_alert_service import ReviewAlertService

    service = ReviewAlertService()
    first = service.emit_alert(
        db, company_id=None, alert_type="system", severity="medium",
        title="huella antigua", message="m", fingerprint_parts=["old"],
    )
    service.emit_alert(
        db, company_id=None, alert_type="system", severity="medium",
        title="huella nueva", message="m", fingerprint_parts=["new"],
    )
    # Re-disparo de la huella antigua: su created_at es el mas viejo pero su
    # ultimo disparo es el mas reciente.
    retriggered = service.emit_alert(
        db, company_id=None, alert_type="system", severity="high",
        title="huella antigua", message="m2", fingerprint_parts=["old"],
    )
    assert retriggered.id == first.id
    result = list_alerts(ticker=None, status=None, include_snoozed=True, limit=100, db=db)
    assert [out.title for out in result][:2] == ["huella antigua", "huella nueva"]


def test_list_alerts_exposes_last_triggered_at(db):
    """F146: la hora del disparo que ve la UI sale de last_triggered_at."""
    _seed(db)
    result = list_alerts(ticker=None, status=None, include_snoozed=True, limit=100, db=db)
    for out in result:
        assert out.last_triggered_at is None or out.last_triggered_at >= out.created_at


def test_get_never_mutates_the_orm_rows(db):
    alerts = _seed(db)
    list_alerts(ticker=None, status=None, include_snoozed=False, limit=100, db=db)
    db.expire_all()

    expired = db.scalar(select(ResearchAlert).where(ResearchAlert.id == alerts["expired"].id))
    # La fila sigue como estaba: el GET no escribe (ni commit ni dirty flush).
    assert expired.status == "snoozed"
    assert expired.snoozed_until is not None


def test_list_alerts_resolves_source_url(db):
    """F172: la URL de la fuente sale de metadata.source_url (insider) o del
    NewsEvent enlazado via metadata.news_event_id (filing/noticia); sin URL
    conocida queda None, nunca inventada."""
    from app.models.entities import NewsEvent

    company = Company(
        ticker="AAPL", name="Apple", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.flush()
    event = NewsEvent(
        company_id=company.id, title="AAPL 8-K",
        url="https://www.sec.gov/Archives/edgar/data/1/0001.htm",
    )
    db.add(event)
    db.flush()
    cases = [
        ("insider", {"source_url": "https://www.sec.gov/form4/1"}, "https://www.sec.gov/form4/1"),
        ("filing", {"news_event_id": event.id}, event.url),
        ("sin-fuente", {}, None),
    ]
    for key, metadata, _expected in cases:
        db.add(ResearchAlert(
            company_id=company.id, alert_type="filing", severity="medium",
            title=f"AAPL {key}", message="m", fingerprint=f"fp-src-{key}",
            channels=["in_app"], status="open", metadata_=metadata,
        ))
    db.commit()

    result = list_alerts(ticker=None, status=None, include_snoozed=True, limit=100, db=db)
    urls = {a.title: a.source_url for a in result}
    for key, _metadata, expected in cases:
        assert urls[f"AAPL {key}"] == expected


@pytest.mark.parametrize(
    "bad_url",
    [
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "/relative/path",
        "notaurl",
        "",
        "ftp://example.com/doc",
        "https://[broken/path",
        "https://@/bad",
        "https://:443/path",
    ],
)
def test_list_alerts_source_url_rejects_unsafe_schemes(db, bad_url):
    """F172: source_url alimenta el href de un <a target="_blank">; cualquier
    esquema que no sea http/https absoluto (javascript:, data:, relativo,
    vacio) sale como None tanto desde metadata.source_url como de NewsEvent.url."""
    from app.models.entities import NewsEvent

    company = Company(
        ticker="AAPL", name="Apple", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.flush()
    event = NewsEvent(company_id=company.id, title="t", url=bad_url)
    db.add(event)
    db.flush()
    db.add(ResearchAlert(
        company_id=company.id, alert_type="insider", severity="medium",
        title="meta", message="m", fingerprint=f"fp-bad-meta-{bad_url[:8]}",
        channels=["in_app"], status="open", metadata_={"source_url": bad_url},
    ))
    db.add(ResearchAlert(
        company_id=company.id, alert_type="filing", severity="medium",
        title="news", message="m", fingerprint=f"fp-bad-news-{bad_url[:8]}",
        channels=["in_app"], status="open", metadata_={"news_event_id": event.id},
    ))
    db.commit()

    result = list_alerts(ticker=None, status=None, include_snoozed=True, limit=100, db=db)
    urls = {a.title: a.source_url for a in result}
    assert urls["meta"] is None
    assert urls["news"] is None


def test_list_alerts_source_url_accepts_absolute_http(db):
    """F172: una URL absoluta http/https con host sí sale como enlace, tanto
    desde metadata.source_url como desde NewsEvent.url."""
    from app.models.entities import NewsEvent

    company = Company(
        ticker="AAPL", name="Apple", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.flush()
    good = "https://www.sec.gov/Archives/edgar/data/1/0001.htm"
    event = NewsEvent(company_id=company.id, title="t", url=good)
    db.add(event)
    db.flush()
    db.add(ResearchAlert(
        company_id=company.id, alert_type="filing", severity="medium",
        title="news-ok", message="m", fingerprint="fp-ok-news",
        channels=["in_app"], status="open", metadata_={"news_event_id": event.id},
    ))
    db.commit()

    result = list_alerts(ticker=None, status=None, include_snoozed=True, limit=100, db=db)
    assert result[0].source_url == good


def test_list_alerts_over_http_serves_rows_and_sanitizes():
    """F172: el endpoint HTTP real GET /api/alerts responde 200 con las filas
    (regresión: un helper mal insertado entre el decorador y list_alerts
    dejaba el listado roto aunque la llamada directa pasara) y expone
    source_url ya sanitizado."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    # TestClient sirve la app en otro hilo: StaticPool comparte la unica
    # conexion entre hilos (con :memory: cada conexion seria una BD vacia).
    from sqlalchemy.pool import StaticPool

    from app.api.routes import alerts as alerts_module
    from app.core.database import get_db
    from app.models.entities import NewsEvent

    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.info["tenant_id"] = "tenant-test"
    db = session

    company = Company(
        ticker="AAPL", name="Apple", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.flush()
    event = NewsEvent(
        company_id=company.id, title="t",
        url="https://www.sec.gov/Archives/edgar/data/1/0001.htm",
    )
    db.add(event)
    db.flush()
    db.add(ResearchAlert(
        company_id=company.id, alert_type="filing", severity="medium",
        title="http-ok", message="m", fingerprint="fp-http-ok",
        channels=["in_app"], status="open", metadata_={"news_event_id": event.id},
    ))
    db.add(ResearchAlert(
        company_id=company.id, alert_type="insider", severity="medium",
        title="http-bad", message="m", fingerprint="fp-http-bad",
        channels=["in_app"], status="open", metadata_={"source_url": "javascript:alert(1)"},
    ))
    db.commit()

    app = FastAPI()
    app.include_router(alerts_module.router, prefix="/api/alerts")
    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    client = TestClient(app)

    response = client.get("/api/alerts")
    assert response.status_code == 200, response.text
    rows = {row["title"]: row for row in response.json()}
    assert rows["http-ok"]["source_url"] == event.url
    assert rows["http-bad"]["source_url"] is None


def test_filing_card_fields_come_from_linked_source_not_alert_creation(db):
    from app.models.entities import NewsEvent
    company = Company(ticker="V", name="Visa", exchange="NYSE", currency="USD",
                      company_type="holding", valuation_model="unassigned")
    db.add(company); db.flush()
    event = NewsEvent(tenant_id="tenant-test", company_id=company.id,
                      title="8-K presentado ante SEC", source="SEC", url="https://www.sec.gov/x",
                      summary="Documento", date=datetime(2025, 10, 28, tzinfo=UTC),
                      metadata_={"date_source": "source", "source_headline": "V 8-K filed 2025-10-28"})
    db.add(event); db.flush()
    db.add(ResearchAlert(company_id=company.id, alert_type="news_material_update",
                         severity="medium", title="Review required: news material update",
                         message="No structural thesis node matched", fingerprint="visa-filing",
                         channels=["in_app"], status="open", metadata_={"news_event_id": event.id}))
    db.commit()
    row = next(a for a in list_alerts(ticker=None, status=None, include_snoozed=True, limit=100, db=db)
               if a.fingerprint == "visa-filing")
    assert row.company_name == "Visa" and row.event_form == "8-K"
    assert row.event_date.date().isoformat() == "2025-10-28"
    assert row.source_url == "https://www.sec.gov/x"


def test_orphan_insider_identity_comes_from_exact_transaction(db):
    from app.models.entities import InsiderFiling, InsiderTransaction

    filing = InsiderFiling(
        accession_number="identity-test", form="4", issuer_cik="123",
        issuer_ticker="ZU", issuer_name="Source issuer", parser_version="v1",
    )
    db.add(filing)
    db.flush()
    tx = InsiderTransaction(
        fingerprint="identity-fp", filing_id=filing.id, accession_number="identity-test",
        form="4", issuer_ticker="ZU",
    )
    db.add(tx)
    alert = ResearchAlert(
        company_id=None, alert_type="insider_big_buy", severity="high",
        title="Not identity evidence AAPL", message="m", fingerprint="identity-alert",
        channels=["in_app"], status="open", metadata_={"tx_fingerprint": "identity-fp"},
    )
    db.add(alert)
    db.commit()
    result = list_alerts(ticker=None, status=None, include_snoozed=True, limit=100, db=db)
    out = next(row for row in result if row.id == alert.id)
    assert out.ticker == "ZU"
    assert out.company_name == "Source issuer"
    assert out.company_id is None
    assert not db.dirty


def test_orphan_insider_metadata_ticker_without_invented_name(db):
    alert = ResearchAlert(
        company_id=None, alert_type="insider_cluster_buy", severity="high",
        title="Unrelated text", message="m", fingerprint="metadata-identity-alert",
        channels=["in_app"], status="open", metadata_={"issuer_ticker": "ZU"},
    )
    db.add(alert)
    db.commit()
    result = list_alerts(ticker=None, status=None, include_snoozed=True, limit=100, db=db)
    out = next(row for row in result if row.id == alert.id)
    assert out.ticker == "ZU"
    assert out.company_name is None


def test_orphan_insider_never_borrows_identity_from_another_tenant(db):
    from app.models.entities import InsiderFiling, InsiderTransaction

    filing = InsiderFiling(
        accession_number="other-tenant", form="4", issuer_cik="999",
        issuer_ticker="PRIVATE", issuer_name="Other tenant issuer", parser_version="v1",
    )
    original_tenant = db.info["tenant_id"]
    db.info["tenant_id"] = "other-tenant"
    db.add(filing)
    db.flush()
    db.add(InsiderTransaction(
        fingerprint="shared-fp", filing_id=filing.id, accession_number="other-tenant",
        form="4", issuer_ticker="PRIVATE",
    ))
    db.commit()
    db.info["tenant_id"] = original_tenant
    alert = ResearchAlert(
        company_id=None, alert_type="insider_big_buy", severity="high",
        title="PRIVATE is only text", message="m", fingerprint="own-tenant-alert",
        channels=["in_app"], status="open", metadata_={"tx_fingerprint": "shared-fp"},
    )
    db.add(alert)
    db.commit()
    out = next(row for row in list_alerts(
        ticker=None, status=None, include_snoozed=True, limit=100, db=db
    ) if row.id == alert.id)
    assert out.ticker is None
    assert out.company_name is None


@pytest.mark.parametrize('legacy', [{}, {'deliveries': {'in_app': {'status': 'failed'}}}])
def test_deliveries_read_authoritative_rows_without_mutating_legacy_metadata(db, legacy):
    from app.models import AlertDelivery
    alerts = _seed(db)
    alert = alerts['open']
    alert.metadata_ = legacy
    db.add(AlertDelivery(alert_id=alert.id, tenant_id=alert.tenant_id,
                         channel='in_app', status='delivered', attempts=1))
    db.commit()
    result = list_alerts(ticker=None, status=None, include_snoozed=True, limit=100, db=db)
    out = next(row for row in result if row.id == alert.id)
    assert out.metadata['deliveries']['in_app']['status'] == 'delivered'
    assert alert.metadata_ == legacy
    assert 'telegram' not in out.metadata['deliveries']
    assert not db.dirty


def test_legacy_novo_headline_is_not_presented_as_nvidia_alert(db):
    from app.models import NewsEvent
    company = Company(ticker='NVDA', name='NVIDIA Corp', exchange='NASDAQ', currency='USD',
                      company_type='standard', valuation_model='standard_dcf')
    db.add(company)
    db.flush()
    for i, title in enumerate(['Novo Trades at Less Than 12 Times Earnings', 'NVIDIA unveils new chip']):
        event = NewsEvent(company_id=company.id, title=f'NVDA {title}', summary=title,
                          source='Yahoo', date=datetime.now(UTC), metadata_={'source_headline': title})
        db.add(event)
        db.flush()
        db.add(ResearchAlert(company_id=company.id, alert_type='news_material_update',
                            severity='high', title=title, message='m', channels=['in_app'],
                            fingerprint=f'issuer-{i}', status='open', metadata_={'news_event_id': event.id}))
    db.commit()
    out = list_alerts(ticker=None, status=None, include_snoozed=True, limit=100, db=db)
    assert [row.title for row in out] == ['NVIDIA unveils new chip']
    assert db.query(ResearchAlert).count() == 2  # No destructive cleanup from a GET.
    assert not db.dirty


@pytest.mark.parametrize("status,include_snoozed", [(None, False), ("open", False), (None, True)])
def test_product_feed_omits_ops_before_limit_preserving_daily_digest(db, status, include_snoozed):
    from sqlalchemy import func
    now = datetime.now(UTC)
    for kind, title, metadata, stamp in [
        ("daily_digest", "Resumen de cartera", {}, now - timedelta(hours=1)),
        ("typesafe_credit_exhausted", "Legacy ops", {}, now),
        ("provider_incident", "Marked ops", {"audience":"internal_ops"}, now),
    ]:
        db.add(ResearchAlert(company_id=None, alert_type=kind, title=title,
                             message="m", fingerprint=kind, severity="high", status="open",
                             channels=["in_app"], metadata_=metadata, last_triggered_at=stamp))
    db.commit()
    before = db.scalar(select(func.count()).select_from(ResearchAlert))
    result = list_alerts(ticker=None, status=status, include_snoozed=include_snoozed, limit=1, db=db)
    assert [item.title for item in result] == ["Resumen de cartera"]
    assert result[0].ticker is None
    # Read-only projection: operations history remains for internal diagnosis.
    assert db.scalar(select(func.count()).select_from(ResearchAlert)) == before == 3
    assert not db.dirty


def test_alerts_timing_solo_con_flag(db, caplog, monkeypatch):
    """Diagnostico: el desglose por tramos (consulta principal, companies,
    news, insider, deliveries, DTO) solo se emite con ALERTS_TIMING=1.
    Perfil local 2026-10-31: handler ~17,6 ms con 100 alertas sin tramo
    dominante; prod p50 263 ms -> hace falta el desglose en prod."""
    import logging

    _seed(db)
    with caplog.at_level(logging.INFO, logger="app.api.routes.alerts"):
        list_alerts(ticker=None, status=None, include_snoozed=False, limit=100, db=db)
    assert not [r for r in caplog.records if r.getMessage().startswith("alerts_timing")]

    monkeypatch.setenv("ALERTS_TIMING", "1")
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="app.api.routes.alerts"):
        list_alerts(ticker=None, status=None, include_snoozed=False, limit=100, db=db)
    records = [r for r in caplog.records if r.getMessage().startswith("alerts_timing")]
    assert len(records) == 1
    msg = records[0].getMessage()
    for tramo in ("query_ms", "companies_ms", "news_ms", "insider_ms", "deliveries_ms", "dto_ms", "total_ms", "alerts="):
        assert tramo in msg, f"falta {tramo} en el desglose"
