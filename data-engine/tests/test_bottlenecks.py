from datetime import UTC, date, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.bottlenecks import list_bottlenecks, router
from app.core.database import Base, get_db
from app.models import (
    BottleneckSignal,
    Document,
    DocumentChunk,
    KnowledgeChunk,
    KnowledgeDocument,
    NewsEvent,
    Tenant,
)
from app.services.bottleneck_service import (
    MIN_SOURCES,
    Evidence,
    aggregate,
    extract_themes,
    refresh_signals,
    stored_evidence,
)


@pytest.mark.parametrize(
    "text,theme",
    [
        ("Chip supply constraints persist", "Semiconductores"),
        ("Escasez de cobre", "Minerales"),
        ("Electricity capacity is ample", None),
        ("Capacidad limitada de la red electrica", "Energía"),
        ("GPU delivery times have increased to 20 weeks", "Semiconductores"),
        ("Longer lead times for aircraft", "Industria aeroespacial"),
        ("Shipping backlog grows", "Transporte"),
        ("Data centers face limited capacity", "Centros de datos"),
        ("No chip shortages", None),
        ("No significant shortage of chips", None),
        ("Chip shortages are easing", None),
        ("Escasez de liquidez. La industria de chips crece", None),
        ("Escasez de talento", None),
        ("Chip capacity expands", None),
        ("Normal lead times for chips", None),
        ("Reduced shipping backlog", None),
    ],
)
def test_extraction(text, theme):
    assert extract_themes(text) == ({theme} if theme else set())


ABSENCE_OR_HYPOTHESIS = [
    "Chip shortages are not expected.",
    "The chip shortage did not materialize.",
    "If chip shortages occur, production could slow.",
    "Escasez de chips ya resuelta.",
    "The chip shortage was already resolved last quarter.",
    "Chip shortages have never been a problem here.",
    "Chip shortages might return next year.",
    "Analysts fear a chip shortage.",
    "La escasez de chips no se ha materializado.",
    "Si hay escasez de chips, la produccion se frenara.",
    "Chip shortage is behind us.",
    "A chip shortage is unlikely.",
    # Objecion del auditor (PR #1920): alivio anunciado o ya consumado no es escasez.
    "Chip shortage will ease by Q3.",
    "The chip shortage is expected to ease.",
    "Chip shortages ease as capacity returns.",
    "The GPU shortage has faded.",
    "Delivery times were 20 weeks in 2022 but are now normal.",
    "Supply constraints persist though the CEO expects supply to normalize.",
    # Elipsis de titular truncado: NO corta la frase (objecion auditor, PR #1920).
    "Chip shortage... The company expects supply to normalize.",
    "GPU shortage… suppliers say output will ease next quarter.",
]


@pytest.mark.parametrize("text", ABSENCE_OR_HYPOTHESIS)
def test_absence_relief_and_hypotheses_fail_closed(text):
    assert extract_themes(text) == set()


@pytest.mark.parametrize("text", ABSENCE_OR_HYPOTHESIS)
def test_absence_never_opens_detectado_through_aggregate(text):
    rows = [evidence("a", "publisher-a", text), evidence("b", "publisher-b", text, day=2)]
    result = aggregate(rows)["Semiconductores"]
    assert result["evidence_ids"] == [] and result["n_sources"] == 0


def test_auditor_mixed_sources_do_not_reach_threshold():
    rows = [
        evidence("a", "p-a", "Chip shortages are not expected."),
        evidence("b", "p-b", "The chip shortage did not materialize."),
    ]
    result = aggregate(rows)["Semiconductores"]
    assert result["n_sources"] == 0 and result["evidence_ids"] == []


def test_absence_stored_in_db_stays_nd_in_endpoint_model(db):
    for i, text in enumerate(ABSENCE_OR_HYPOTHESIS[:4]):
        db.add(NewsEvent(title=text, url=f"https://pub{i}.example/n", date=datetime(2026, 10, 3, tzinfo=UTC)))
    db.commit()
    refresh_signals(db)
    db.commit()
    assert all(s.status == "N/D" and s.evidence_ids == [] for s in list_bottlenecks(db).signals)


def test_real_constraints_still_detected_end_to_end(db):
    for i, text in enumerate(["Chip shortages persist", "Escasez de chips durante el trimestre"]):
        db.add(
            NewsEvent(title=text, url=f"https://real{i}.example/n", date=datetime(2026, 10, 3, tzinfo=UTC))
        )
    db.commit()
    refresh_signals(db)
    db.commit()
    assert list_bottlenecks(db).signals[0].status == "detectado"


def evidence(id, origin, text="Chip shortages persist", day=1, keys=()):
    return Evidence(id, text, datetime(2026, 10, day, tzinfo=UTC), origin, keys or (id,))


def test_independence_dates_and_duplicate_sources():
    rows = [
        evidence("k:1", "fund-a", keys=("doc:1",)),
        evidence("k:2", "fund-a", day=3, keys=("doc:1",)),
        evidence("n:1", "publisher-b", day=5),
        evidence("n:2", None, day=2),
    ]
    result = aggregate(rows)["Semiconductores"]
    assert result["n_sources"] == 2
    assert result["evidence_ids"] == ["k:1", "k:2", "n:1", "n:2"]
    assert result["first_seen"] == datetime(2026, 10, 1, tzinfo=UTC)
    assert result["last_seen"] == datetime(2026, 10, 5, tzinfo=UTC)
    assert aggregate(rows[:2])["Semiconductores"]["n_sources"] == 1
    assert aggregate([evidence("a", None), evidence("b", None)])["Semiconductores"]["n_sources"] == 0


def test_syndicated_copies_and_transitive_links():
    rows = [
        evidence("1", "a", keys=("url:a",)),
        evidence("2", "b", keys=("url:b",)),
        evidence("3", "c", keys=("url:a", "url:b")),
    ]
    assert aggregate(rows)["Semiconductores"]["n_sources"] == 1
    assert aggregate(list(reversed(rows)))["Semiconductores"]["n_sources"] == 1


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([Tenant(id=1, external_id="a"), Tenant(id=2, external_id="b")])
        session.commit()
        session.info["tenant_id"] = 1
        yield session
    engine.dispose()


def seed(db):
    doc = Document(
        title="Filing",
        source_type="filing",
        source_url="https://chips.example/filing",
        published_at=datetime(2026, 10, 1, tzinfo=UTC),
    )
    letter = KnowledgeDocument(
        title="Carta",
        document_type="fund_letter",
        author="Fondo A",
        publication_date=date(2026, 10, 2),
        status="ready",
    )
    unknown = KnowledgeDocument(title="Sin fecha", document_type="fund_letter", author="Fondo B")
    db.add_all([doc, letter, unknown])
    db.flush()
    db.add_all(
        [
            DocumentChunk(document_id=doc.id, chunk_index=0, text="Chip shortages persist"),
            KnowledgeChunk(
                knowledge_document_id=letter.id,
                chunk_index=0,
                content="Escasez de chips durante el trimestre",
            ),
            KnowledgeChunk(knowledge_document_id=unknown.id, chunk_index=0, content="Chip shortages"),
            NewsEvent(
                title="GPU delivery times extend to 40 weeks",
                url="https://chips.example/news",
                date=datetime(2026, 10, 3, tzinfo=UTC),
            ),
            NewsEvent(
                title="Chip shortages persist",
                url="https://copy.example/syndicated",
                date=datetime(2026, 10, 4, tzinfo=UTC),
            ),
        ]
    )
    db.commit()


def test_persistence_idempotency_status_and_reconciliation(db):
    seed(db)
    refresh_signals(db)
    db.commit()
    row = db.scalar(select(BottleneckSignal).where(BottleneckSignal.theme == "Semiconductores"))
    assert row is not None
    assert row.n_sources == 2  # same publisher + syndicated exact copy count once
    assert len(row.evidence_ids) == 4  # undated letter excluded
    assert list_bottlenecks(db).signals[0].status == "detectado"
    assert all(s.status == "N/D" for s in list_bottlenecks(db).signals[1:])
    original_id = row.id
    refresh_signals(db)
    db.commit()
    assert (
        db.scalar(select(BottleneckSignal).where(BottleneckSignal.theme == "Semiconductores")).id
        == original_id
    )
    for chunk in db.scalars(select(KnowledgeChunk)):
        db.delete(chunk)
    refresh_signals(db)
    db.commit()
    assert list_bottlenecks(db).signals[0].status == "N/D"
    assert row.n_sources == 1


def test_empty_missing_context_and_tenant_isolation(db):
    seed(db)
    refresh_signals(db)
    db.commit()
    db.info["tenant_id"] = 2
    assert all(s.status == "N/D" and s.evidence_ids == [] for s in list_bottlenecks(db).signals)
    refresh_signals(db)
    db.commit()
    assert all(s.n_sources == 0 for s in list_bottlenecks(db).signals)
    db.info.clear()
    assert all(s.evidence_ids == [] for s in list_bottlenecks(db).signals)
    with pytest.raises(ValueError):
        refresh_signals(db)


def test_endpoint_read_only_and_typed_openapi(db):
    app = FastAPI()
    app.include_router(router, prefix="/api/bottlenecks")
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        response = client.get("/api/bottlenecks")
        assert response.status_code == 200
        assert len(response.json()["signals"]) == 6
        assert all(s["status"] == "N/D" for s in response.json()["signals"])
        # El umbral vigente viaja en el payload: la UI etiqueta «n de min_sources»
        # con el numero real, nunca hardcodeado.
        assert response.json()["min_sources"] == MIN_SOURCES
    assert db.scalars(select(BottleneckSignal)).all() == []
    assert "BottleneckSignalOut" in app.openapi()["components"]["schemas"]


def test_worker_commits_and_hourly_job(db, monkeypatch):
    from app.workers import dramatiq_app, scheduler

    monkeypatch.setattr(dramatiq_app, "_session", lambda *args: db)
    monkeypatch.setattr(db, "close", lambda: None)
    seed(db)
    result = getattr(dramatiq_app.refresh_bottlenecks, "fn")(1, "owner")  # noqa: B009
    assert result["status"] == "ok"
    assert (
        db.scalar(select(BottleneckSignal).where(BottleneckSignal.theme == "Semiconductores")).n_sources == 2
    )
    job = scheduler.build_scheduler().get_job("bottleneck_refresh")
    assert job is not None and job.trigger.interval.total_seconds() == 3600


def test_publisher_subdomains_tracking_and_cross_lane_copy(db):
    seed(db)
    db.add(
        NewsEvent(
            title="Chips face capacity constraints this month",
            url="https://markets.chips.example/story?utm_source=other",
            date=datetime(2026, 10, 5, tzinfo=UTC),
        )
    )
    db.commit()
    refresh_signals(db)
    db.commit()
    assert list_bottlenecks(db).signals[0].n_sources == 2


def test_migration_upgrade_downgrade():
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect

    path = Path(__file__).parents[1] / "alembic/versions/0056_bottleneck_signal.py"
    spec = importlib.util.spec_from_file_location("migration_bottleneck", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == "0055_telegram_chat_binding"
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        module.op = Operations(MigrationContext.configure(conn))
        module.upgrade()
        assert "bottleneck_signal" in inspect(conn).get_table_names()
        columns = {c["name"] for c in inspect(conn).get_columns("bottleneck_signal")}
        assert columns == {"id", "tenant_id", "theme", "evidence_ids", "first_seen", "last_seen", "n_sources"}
        module.downgrade()
        assert "bottleneck_signal" not in inspect(conn).get_table_names()
    engine.dispose()


def test_rebuild_clears_removed_evidence(db):
    seed(db)
    refresh_signals(db)
    db.commit()
    for model in (DocumentChunk, KnowledgeChunk, NewsEvent):
        for row in db.scalars(select(model)):
            db.delete(row)
    db.commit()
    refresh_signals(db)
    db.commit()
    assert all(
        s.evidence_ids == [] and s.first_seen is None and s.last_seen is None and s.status == "N/D"
        for s in list_bottlenecks(db).signals
    )


def test_chunk_parent_must_share_tenant(db):
    foreign = Document(
        tenant_id=2,
        title="Foreign",
        source_type="filing",
        published_at=datetime(2026, 10, 1, tzinfo=UTC),
        source_url="https://foreign.example/filing",
    )
    db.info.clear()
    db.add(foreign)
    db.flush()
    db.add(DocumentChunk(tenant_id=1, document_id=foreign.id, chunk_index=0, text="Chip shortages persist"))
    db.commit()
    db.info["tenant_id"] = 1
    refresh_signals(db)
    db.commit()
    assert all(s.evidence_ids == [] for s in list_bottlenecks(db).signals)


def test_run_endpoint_enqueues_manual_sweep_without_calling_any_model(db, monkeypatch):
    from app.workers import dramatiq_app

    sent = []

    class _Message:
        message_id = "mid-1"

    def fake_send(tenant_id, user_id):
        sent.append((tenant_id, user_id))
        return _Message()

    monkeypatch.setattr(dramatiq_app.discover_bottlenecks, "send", fake_send)
    db.info["user_id"] = "owner"
    app = FastAPI()
    app.include_router(router, prefix="/api/bottlenecks")
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        response = client.post("/api/bottlenecks/discoveries/run")
        assert response.status_code == 202
        assert response.json() == {"status": "queued", "message_id": "mid-1"}
        # Solo encola: el GET sigue respondiendo desde lo persistido, sin llamadas.
        assert client.get("/api/bottlenecks/discoveries").status_code == 200
    assert sent == [(1, "owner")]
    assert db.scalars(select(BottleneckSignal)).all() == []


def test_discoveries_expose_theme_status_and_last_signal(db):
    """Un candidato guardado persiste aunque su tema caiga bajo el umbral:
    la API expone si el tema sigue detectado y la fecha de su ultima senal."""
    from datetime import date as dt_date

    from app.models import BottleneckDiscovery

    seed(db)
    refresh_signals(db)
    db.commit()
    last_seen = db.scalar(select(BottleneckSignal).where(
        BottleneckSignal.theme == "Semiconductores")).last_seen
    db.add_all([
        # Tema detectado (Semiconductores llega a MIN_SOURCES con el seed).
        BottleneckDiscovery(theme="Semiconductores", ticker="NVDA", reasoning="h",
                            evidence_ids=[], model="m", day=dt_date(2026, 10, 9),
                            created_at=datetime(2026, 10, 9, tzinfo=UTC), n_sources=2),
        # Tema bajo umbral (Minerales no tiene evidencias en el seed).
        BottleneckDiscovery(theme="Minerales", ticker="BHP", reasoning="h",
                            evidence_ids=[], model="m", day=dt_date(2026, 10, 9),
                            created_at=datetime(2026, 10, 9, tzinfo=UTC), n_sources=0),
        # Tema sin fila de senal (fuera del universo actual, historico).
        BottleneckDiscovery(theme="Histórico", ticker="X", reasoning="h",
                            evidence_ids=[], model="m", day=dt_date(2026, 10, 9),
                            created_at=datetime(2026, 10, 9, tzinfo=UTC), n_sources=0),
    ])
    db.commit()
    app = FastAPI()
    app.include_router(router, prefix="/api/bottlenecks")
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        items = {i["theme"]: i for i in client.get("/api/bottlenecks/discoveries").json()["items"]}
    assert items["Semiconductores"]["theme_detected"] is True
    assert items["Semiconductores"]["theme_last_seen"] is not None
    assert items["Minerales"]["theme_detected"] is False
    assert items["Histórico"]["theme_detected"] is False
    assert items["Histórico"]["theme_last_seen"] is None

def test_news_summary_counts_as_evidence_text(db):
    """El carril de noticias analiza tambien el resumen guardado (coste 0):
    la escasez que solo aparece en el cuerpo resumido ya no se pierde."""
    db.add(
        NewsEvent(
            title="Semiconductors weekly recap",
            summary="GPU delivery times extend to 40 weeks as capacity constraints persist.",
            url="https://pub-summary.example/n1",
            date=datetime(2026, 10, 6, tzinfo=UTC),
        )
    )
    db.commit()
    texts = [e.text for e in stored_evidence(db, db.info["tenant_id"])]
    assert any("40 weeks" in t for t in texts)
    refresh_signals(db)
    db.commit()
    signal = db.scalar(select(BottleneckSignal).where(BottleneckSignal.theme == "Semiconductores"))
    assert signal.n_sources == 1  # una fuente: aun no detectado, pero ya cuenta


def test_news_summary_negation_stays_fail_closed(db):
    """El resumen pasa por las mismas guardas (negacion/alivio/hipotesis)."""
    db.add(
        NewsEvent(
            title="Chips outlook",
            summary="No chip shortages expected this quarter, suppliers say.",
            url="https://pub-neg.example/n1",
            date=datetime(2026, 10, 6, tzinfo=UTC),
        )
    )
    db.commit()
    refresh_signals(db)
    db.commit()
    signal = db.scalar(select(BottleneckSignal).where(BottleneckSignal.theme == "Semiconductores"))
    assert signal.n_sources == 0


def test_discoveries_flag_portfolio_and_watchlist(db):
    """El candidato declara si el tenant ya lo tiene en cartera o seguimiento."""
    from datetime import date as dt_date
    from decimal import Decimal

    from app.models import BottleneckDiscovery, Company, Portfolio, Position, WatchItem

    db.add_all([
        Company(id=90, ticker="NVDA", name="NVIDIA", exchange="NASDAQ",
                company_type="large_cap", valuation_model="dcf"),
        Company(id=91, ticker="BHP", name="BHP", exchange="ASX",
                company_type="large_cap", valuation_model="dcf"),
    ])
    db.flush()
    db.add(Portfolio(id=90, name="Main"))
    db.flush()
    db.add(Position(portfolio_id=90, company_id=90, quantity=Decimal("3")))
    db.add(WatchItem(symbol="bhp"))  # minusculas: la comparacion ignora mayusculas
    db.add_all([
        BottleneckDiscovery(theme="Semiconductores", ticker="NVDA", reasoning="h",
                            evidence_ids=[], model="m", day=dt_date(2026, 10, 9),
                            created_at=datetime(2026, 10, 9, tzinfo=UTC), n_sources=2),
        BottleneckDiscovery(theme="Minerales", ticker="BHP", reasoning="h",
                            evidence_ids=[], model="m", day=dt_date(2026, 10, 9),
                            created_at=datetime(2026, 10, 9, tzinfo=UTC), n_sources=0),
        BottleneckDiscovery(theme="Energía", ticker="XOM", reasoning="h",
                            evidence_ids=[], model="m", day=dt_date(2026, 10, 9),
                            created_at=datetime(2026, 10, 9, tzinfo=UTC), n_sources=0),
    ])
    db.commit()
    app = FastAPI()
    app.include_router(router, prefix="/api/bottlenecks")
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        items = {i["ticker"]: i for i in client.get("/api/bottlenecks/discoveries").json()["items"]}
    assert items["NVDA"]["in_portfolio"] is True and items["NVDA"]["in_watchlist"] is False
    assert items["BHP"]["in_portfolio"] is False and items["BHP"]["in_watchlist"] is True
    assert items["XOM"]["in_portfolio"] is False and items["XOM"]["in_watchlist"] is False


def test_discoveries_flag_recent_insider_activity(db):
    """Badge de insider solo con transaccion en los ultimos 90 dias; ni dato
    antiguo ni sin datos muestran nada (ausencia != ausencia de actividad)."""
    from datetime import date as dt_date

    from app.models import BottleneckDiscovery, InsiderFiling, InsiderTransaction

    db.add(InsiderFiling(accession_number="0001", form="4", issuer_cik="1",
                         issuer_ticker="NVDA", parser_version="v1"))
    db.flush()
    filing_id = db.scalar(select(InsiderFiling.id))
    today = datetime.now(UTC).date()
    db.add_all([
        InsiderTransaction(fingerprint="fp1", filing_id=filing_id, accession_number="0001",
                           form="4", issuer_ticker="NVDA", tx_date=str(today)),
        InsiderTransaction(fingerprint="fp2", filing_id=filing_id, accession_number="0001",
                           form="4", issuer_ticker="BHP", tx_date="2020-01-01"),
        InsiderTransaction(fingerprint="fp3", filing_id=filing_id, accession_number="0001",
                           form="4", issuer_ticker="XOM", tx_date="fecha rara"),
    ])
    db.add_all([
        BottleneckDiscovery(theme="Semiconductores", ticker="NVDA", reasoning="h",
                            evidence_ids=[], model="m", day=dt_date(2026, 10, 9),
                            created_at=datetime(2026, 10, 9, tzinfo=UTC), n_sources=2),
        BottleneckDiscovery(theme="Minerales", ticker="BHP", reasoning="h",
                            evidence_ids=[], model="m", day=dt_date(2026, 10, 9),
                            created_at=datetime(2026, 10, 9, tzinfo=UTC), n_sources=0),
        BottleneckDiscovery(theme="Energía", ticker="XOM", reasoning="h",
                            evidence_ids=[], model="m", day=dt_date(2026, 10, 9),
                            created_at=datetime(2026, 10, 9, tzinfo=UTC), n_sources=0),
        BottleneckDiscovery(theme="Transporte", ticker="FDX", reasoning="h",
                            evidence_ids=[], model="m", day=dt_date(2026, 10, 9),
                            created_at=datetime(2026, 10, 9, tzinfo=UTC), n_sources=0),
    ])
    db.commit()
    app = FastAPI()
    app.include_router(router, prefix="/api/bottlenecks")
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        items = {i["ticker"]: i for i in client.get("/api/bottlenecks/discoveries").json()["items"]}
    assert items["NVDA"]["recent_insider_activity"] is True   # hoy
    assert items["BHP"]["recent_insider_activity"] is False   # 2020: fuera de ventana
    assert items["XOM"]["recent_insider_activity"] is False   # fecha ilegible
    assert items["FDX"]["recent_insider_activity"] is False   # sin datos


def test_discoveries_flag_recent_insider_activity_formato_us(db):
    """El parser acepta MM/DD/YYYY: el prefiltro SQL no puede quedarse las
    fechas US recientes fuera (se acotan por año, no por orden lexico)."""
    from datetime import date as dt_date
    from datetime import timedelta as dt_td

    from app.models import BottleneckDiscovery, InsiderFiling, InsiderTransaction

    db.add(InsiderFiling(accession_number="0001", form="4", issuer_cik="1",
                         issuer_ticker="NVDA", parser_version="v1"))
    db.flush()
    filing_id = db.scalar(select(InsiderFiling.id))
    today = datetime.now(UTC).date()
    reciente_us = (today - dt_td(days=30)).strftime("%m/%d/%Y")
    db.add_all([
        InsiderTransaction(fingerprint="fp1", filing_id=filing_id, accession_number="0001",
                           form="4", issuer_ticker="NVDA", tx_date=reciente_us),
        InsiderTransaction(fingerprint="fp2", filing_id=filing_id, accession_number="0001",
                           form="4", issuer_ticker="BHP", tx_date="01/15/2020"),
    ])
    db.add_all([
        BottleneckDiscovery(theme="Semiconductores", ticker="NVDA", reasoning="h",
                            evidence_ids=[], model="m", day=dt_date(2026, 10, 9),
                            created_at=datetime(2026, 10, 9, tzinfo=UTC), n_sources=2),
        BottleneckDiscovery(theme="Minerales", ticker="BHP", reasoning="h",
                            evidence_ids=[], model="m", day=dt_date(2026, 10, 9),
                            created_at=datetime(2026, 10, 9, tzinfo=UTC), n_sources=0),
    ])
    db.commit()
    app = FastAPI()
    app.include_router(router, prefix="/api/bottlenecks")
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        items = {i["ticker"]: i for i in client.get("/api/bottlenecks/discoveries").json()["items"]}
    assert items["NVDA"]["recent_insider_activity"] is True   # MM/DD/YYYY reciente
    assert items["BHP"]["recent_insider_activity"] is False   # MM/DD/YYYY vieja


def test_discoveries_insider_prefiltro_sql(db):
    """Perf: el DISTINCT de insider_transactions leia la tabla ENTERA sin cota
    de fecha (372 ms medidos en el barrido 2026-10-31). Debe llevar prefiltro
    por tx_date (superset; el parseo exacto sigue en Python)."""
    from sqlalchemy import event

    from app.models import InsiderFiling, InsiderTransaction

    db.add(InsiderFiling(accession_number="0001", form="4", issuer_cik="1",
                         issuer_ticker="NVDA", parser_version="v1"))
    db.flush()
    filing_id = db.scalar(select(InsiderFiling.id))
    today = datetime.now(UTC).date()
    db.add(InsiderTransaction(fingerprint="fp1", filing_id=filing_id, accession_number="0001",
                              form="4", issuer_ticker="NVDA", tx_date=str(today)))
    db.commit()
    engine = db.get_bind()
    statements: list[str] = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if "insider_transactions" in statement and "DISTINCT" in statement.upper():
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    app = FastAPI()
    app.include_router(router, prefix="/api/bottlenecks")
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            assert client.get("/api/bottlenecks/discoveries").status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert statements, "consulta DISTINCT de insider no encontrada"
    assert "tx_date >=" in statements[0], "sin prefiltro SQL por tx_date"
