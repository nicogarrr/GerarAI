"""_document_urls_ingested: dedup de encolado por URL en LOTE (una SELECT
por empresa y pasada en refresh_sec_filings / refresh_ir_pages).

Antes: una SELECT por candidato (medido en SQLite: 3 empresas x 8 docs
nuevos = 24 SELECTs sobre documents). Ahora: 1 por empresa. El conjunto
devuelto es el mismo que el del helper por URL: misma fuente (source_url),
mismos filtros de tenant, mismo troceo por tope de bind params.

Harness: SQLite real + before_cursor_execute. NO MEDIDO: Postgres real.
"""

from types import SimpleNamespace

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.services.feed_ingestion_service as feed
from app.models.entities import Base, Company, Document
from app.workers import dramatiq_app as actors
from app.workers.dramatiq_app import _document_url_ingested, _document_urls_ingested

URL = "https://krakenrobotics.com/news-releases/comunicado-1"


def _session() -> Session:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.info["tenant_id"] = "tenant-test"
    company = Company(
        ticker="KRKNF", name="Kraken Robotics", exchange="TSXV", currency="CAD",
        sector="Tech", industry="Robotics", cik=None, company_type="operating",
        valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=[],
    )
    session.add(company)
    session.flush()
    session.add(Document(
        company_id=company.id, title="Comunicado 1", source_type="ir_news",
        source_url=URL, metadata_={}, tenant_id="tenant-test",
    ))
    session.commit()
    return session


def test_lote_devuelve_solo_las_ingeridas_del_tenant():
    db = _session()
    known = _document_urls_ingested(db, [URL, "https://otra.example.com/nueva"])
    assert known == {URL}


def test_lote_respeta_tenant():
    db = _session()
    db.info["tenant_id"] = "otro-tenant"
    assert _document_urls_ingested(db, [URL]) == set()


def test_lote_vacio_o_sin_urls_no_consulta():
    db = _session()
    statements: list[str] = []

    def capture(conn, cur, stmt, params, ctx, many):
        statements.append(stmt)

    event.listen(db.get_bind(), "before_cursor_execute", capture)
    try:
        assert _document_urls_ingested(db, []) == set()
        assert _document_urls_ingested(db, [None, "", None]) == set()
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)
    selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
    assert selects == []


def test_lote_equivale_al_helper_por_url():
    db = _session()
    urls = [URL, "https://otra.example.com/nueva", "https://sec.gov/x"]
    batch = _document_urls_ingested(db, urls)
    for url in urls:
        assert (url in batch) is _document_url_ingested(db, url)


def test_lote_dedup_entrada_y_troceo():
    db = _session()
    # 1201 candidatos con duplicados: fuerza 2 troces tras dedup interno y
    # el resultado sigue siendo exacto.
    urls = [f"https://sec.gov/doc-{i}" for i in range(600)]
    urls = urls + urls + [f"https://sec.gov/doc-{i}" for i in range(601)]
    known = _document_urls_ingested(db, urls)
    assert known == set()


def _counting_session(monkeypatch, n_companies=3, n_items=8):
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = "tenant-test"
    for i in range(n_companies):
        db.add(Company(
            ticker=f"T{i}", name=f"Co {i}", exchange="NYSE", currency="USD",
            sector="Tech", industry="SW", cik=str(1000 + i), company_type="operating",
            valuation_model="unassigned", special_sources=[], special_risks=[],
            factor_tags=[],
        ))
    db.commit()
    statements: list[str] = []
    event.listen(
        engine, "before_cursor_execute",
        lambda conn, cur, stmt, params, ctx, many: statements.append(stmt),
    )
    companies = [SimpleNamespace(ticker=f"T{i}", cik=str(1000 + i)) for i in range(n_companies)]
    items = [
        SimpleNamespace(url=f"https://sec.gov/doc-{i}-{j}", title=f"F {i}-{j}",
                        published_at=None, metadata=None)
        for i in range(n_companies)
        for j in range(n_items)
    ]

    class Service:
        async def poll_sec(self, cik, *, ticker, limit):
            i = int(ticker[1:])
            return SimpleNamespace(
                items=items[i * n_items:(i + 1) * n_items], errors=[], status="ok"
            )

        def ingest_news_result(self, *a, **k):
            return {"created": 0}

    monkeypatch.setattr(actors, "_session", lambda *a: db)
    monkeypatch.setattr(actors, "_companies", lambda *a: companies)
    monkeypatch.setattr(actors, "_redis_client", lambda: None)
    monkeypatch.setattr(actors.settings, "sec_document_jobs_enabled", True)
    monkeypatch.setattr(actors, "_document_ingest_excluded", lambda *a: False)
    monkeypatch.setattr(actors.process_document, "send", lambda *a, **k: None)
    monkeypatch.setattr(actors.refresh_sec_filings, "send", lambda **k: None)
    monkeypatch.setattr(feed, "FeedIngestionService", Service)
    return db, statements


def test_refresh_sec_filings_una_select_de_dedup_por_empresa(monkeypatch):
    db, statements = _counting_session(monkeypatch, n_companies=3, n_items=8)
    result = actors.refresh_sec_filings.fn(tenant_id=1, user_id="u")
    doc_selects = [s for s in statements if "FROM DOCUMENTS" in s.upper()]
    assert result["documents_queued"] == 24
    # Antes del lote: 24 (una por candidato). Ahora: 3 (una por empresa).
    assert len(doc_selects) == 3


def test_refresh_sec_filings_todas_conocidas_siguen_saltando(monkeypatch):
    db, statements = _counting_session(monkeypatch, n_companies=2, n_items=4)
    company = db.query(Company).filter_by(ticker="T0").one()
    for j in range(4):
        db.add(Document(
            company_id=company.id, title=f"F 0-{j}", source_type="sec_filing",
            source_url=f"https://sec.gov/doc-0-{j}", metadata_={}, tenant_id="tenant-test",
        ))
    db.commit()
    result = actors.refresh_sec_filings.fn(tenant_id=1, user_id="u")
    assert result["documents_queued"] == 4  # solo los 4 de T1
    assert result["documents_skipped_known"] == 4  # los 4 de T0
