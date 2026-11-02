import asyncio
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, NewsEvent, Tenant
from app.services.connectors import subtel
from app.services.subtel_news import persist_decrees

FIXTURE = Path(__file__).parent / "fixtures/subtel"


def test_real_register_identity_and_dates():
    rows = subtel.parse_register((FIXTURE / "request-10872.html").read_text())
    assert len(rows) == 1
    row = rows[0]
    assert row["decree_number"] == 1209
    assert row["request_date"] == "2026-01-28"
    assert row["decree_date"] == "2026-10-15"
    assert row["publication_date"] is None
    assert "publico.subtel.gob.cl" in row["pdf_url"]


@pytest.mark.parametrize("url", [
    "http://publico.subtel.gob.cl/dwldDocSubtel/view?rutaArchivo=/ofpartes/Decretos/Exentos/2026/26de_1209.pdf",
    "https://evil.invalid/dwldDocSubtel/view?rutaArchivo=/ofpartes/Decretos/Exentos/2026/26de_1209.pdf",
    "https://publico.subtel.gob.cl@evil.invalid/dwldDocSubtel/view?rutaArchivo=x",
    "https://publico.subtel.gob.cl/dwldDocSubtel/view?rutaArchivo=../../secret",
    "https://publico.subtel.gob.cl/dwldDocSubtel/view?rutaArchivo=/ofpartes/Decretos/Exentos/2026/26de_1209.pdf&next=http://localhost",
])
def test_reject_untrusted_downloads(url):
    with pytest.raises(ValueError):
        subtel.official_pdf_url(url)


def test_fetch_real_pdf_and_register():
    seen = []
    def handler(request):
        seen.append(str(request.url))
        body = ((FIXTURE / "request-10872.html").read_bytes() if "getSolicitudes" in request.url.path
                else (FIXTURE / "decree-1209.pdf").read_bytes())
        return httpx.Response(200, content=body)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await subtel.fetch_decrees(client)
    rows = asyncio.run(run())
    assert len(seen) == 2
    assert all(httpx.URL(url).host == subtel.HOST for url in seen)
    assert "1.990" in rows[0]["text"]
    assert len(rows[0]["sha256"]) == 64


@pytest.mark.parametrize("status,body", [(302,b""),(200,b"not a pdf"),(200,b"x" * (subtel.MAX_BYTES + 1))])
def test_reject_redirect_bad_content_and_size(status, body):
    def handler(request):
        if "getSolicitudes" in request.url.path:
            return httpx.Response(200, content=(FIXTURE / "request-10872.html").read_bytes())
        return httpx.Response(status, content=body, headers={"location": "http://localhost"})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await subtel.fetch_decrees(client)
    with pytest.raises((ValueError, httpx.HTTPStatusError)):
        asyncio.run(run())


def test_tenant_idempotence_and_no_alert_or_thesis_mutation():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    rows = subtel.parse_register((FIXTURE / "request-10872.html").read_text())
    with Session(engine) as db:
        db.add_all([Tenant(id=1,external_id="one"),Tenant(id=2,external_id="two"),
                    Company(ticker="ASTS",name="AST SpaceMobile",exchange="NASDAQ",currency="USD",
                            company_type="pre_revenue",valuation_model="dcf")])
        db.commit()
        with pytest.raises(RuntimeError):
            persist_decrees(db, rows, datetime.now(UTC))
        for tenant in (1,2):
            db.info["tenant_id"] = tenant
            assert persist_decrees(db, rows, datetime.now(UTC)) == 1
            assert persist_decrees(db, rows, datetime.now(UTC)) == 0
            event = db.scalar(select(NewsEvent))
            assert event.tenant_id == tenant
            assert not event.requires_update and not event.affected_thesis
            assert event.metadata_["no_new_alerts"]
            assert event.metadata_["regulatory_evidence"]["publication_date"] is None
    engine.dispose()


def test_pending_or_other_issuer_is_not_concession():
    html = (FIXTURE / "request-10872.html").read_text()
    assert subtel.parse_register(html.replace("AST SpaceMobile Chile SpA", "Other company")) == []
    assert subtel.parse_register(html.replace("Número: 1209", "Número: pendiente")) == []
    assert subtel.parse_register(html.replace("26de_1209.pdf", "26de_9999.pdf")) == []


def test_actor_one_fetch_and_tenant_failures_are_visible(monkeypatch):
    from app.services import subtel_news
    from app.workers import dramatiq_app as workers
    calls, sessions = [], []
    class DB:
        def __init__(self, tenant):
            self.info = {"tenant_id": tenant}
            self.closed = False
        def close(self):
            self.closed = True
        def rollback(self):
            pass
    def session(tenant, user):
        db = DB(tenant)
        sessions.append(db)
        return db
    async def fetch(client=None):
        calls.append("fetch")
        return [{"marker": "official"}]
    def persist(db, rows, fetched_at):
        assert rows == [{"marker": "official"}]
        if db.info["tenant_id"] == 2:
            raise ValueError("isolated failure")
        return 1
    monkeypatch.setattr(workers, "_redis_client", lambda: None)
    monkeypatch.setattr(workers, "tenant_contexts", lambda: [(1,"one"),(2,"two")])
    monkeypatch.setattr(workers, "_session", session)
    monkeypatch.setattr(subtel, "fetch_decrees", fetch)
    monkeypatch.setattr(subtel_news, "persist_decrees", persist)
    result = workers.refresh_subtel_decrees()
    assert calls == ["fetch"]
    assert result["status"] == "partial" and result["created"] == 1
    assert result["errors"] == [{"tenant_id": 2,"type": "ValueError"}]
    assert all(db.closed for db in sessions)
