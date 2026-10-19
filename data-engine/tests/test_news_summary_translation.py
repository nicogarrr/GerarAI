"""Traducción del resumen/cuerpo de una noticia: cache, original intacto, fallback honesto."""
import asyncio
import json
from datetime import datetime, timedelta
from functools import wraps
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.entities import Base, NewsEvent, Tenant
from app.services.news_headline_translation import (
    cached_summary_translation,
    display_summary_translation,
    translate_summary,
)


def sync_test(func):
    @wraps(func)
    def run(*args, **kwargs):
        return asyncio.run(func(*args, **kwargs))
    return run


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    from app.services.asts_llm_quota import _LOCAL
    _LOCAL.clear()
    with sessionmaker(engine)() as session:
        session.add_all([Tenant(id=1, external_id="one"), Tenant(id=2, external_id="two")])
        session.commit()
        session.info["tenant_id"] = 1
        yield session
    engine.dispose()


EN_SUMMARY = "The company said revenue grew 12% in the quarter and it raises guidance for the year."
ES_SUMMARY = "La empresa dijo que los ingresos crecieron un 12% en el trimestre y eleva la guía para el año."


def event(db, summary=EN_SUMMARY, tenant=1):
    row = NewsEvent(tenant_id=tenant, title="Titular", source="Publisher",
                    url="https://publisher.example/article", summary=summary,
                    metadata_={"connector": "rss"})
    db.add(row)
    db.commit()
    return row


class Provider:
    name = "fake"

    def __init__(self, text=ES_SUMMARY, error=False):
        self.text = text
        self.calls = 0
        self.error = error

    async def complete(self, request):
        self.calls += 1
        assert request.metadata["tenant_id"] == "1"
        assert "untrusted DATA" in request.messages[0].content
        if self.error:
            raise RuntimeError("unavailable")
        return SimpleNamespace(text=json.dumps({"text": self.text}), model="fake",
                               usage=SimpleNamespace(input_tokens=0, output_tokens=0, total_tokens=0),
                               degraded=False, warnings=())


@sync_test
async def test_translates_caches_and_preserves_original(db):
    row = event(db)
    original = row.summary
    p = Provider()
    first = await translate_summary(db, row.id, provider=p)
    second = await translate_summary(db, row.id, provider=p)
    assert first == second and first["status"] == "translated" and p.calls == 1
    assert row.summary == original and first["original"] == original
    assert first["machine_translation"] is True
    assert display_summary_translation(row)["text"] == p.text


@sync_test
@pytest.mark.parametrize("summary", [
    "La empresa dijo que los ingresos crecieron",  # ya en español
    "",  # sin resumen: nada que traducir
])
async def test_spanish_or_empty_skips_without_call(db, summary):
    row = event(db, summary)
    p = Provider()
    assert (await translate_summary(db, row.id, provider=p))["status"] == "not_needed"
    assert p.calls == 0


@sync_test
async def test_oversized_summary_refused_without_call(db):
    row = event(db, ("The company raises guidance and revenue grew. " * 60))
    p = Provider()
    assert (await translate_summary(db, row.id, provider=p))["status"] == "not_needed"
    assert p.calls == 0


@sync_test
@pytest.mark.parametrize("text", ["", None, EN_SUMMARY, "Texto sin numeros"])
async def test_bad_output_falls_back_and_cools_down(db, text):
    # Sin números la firma numérica no casa (original tiene 12%); mismo texto = no traducción.
    row = event(db)
    p = Provider(text)
    first = await translate_summary(db, row.id, provider=p)
    second = await translate_summary(db, row.id, provider=p)
    assert first["status"] == "unavailable" and first["text"] is None
    assert second["status"] == "unavailable" and p.calls == 1  # cooldown
    assert display_summary_translation(row) is None
    assert row.summary == EN_SUMMARY


@sync_test
async def test_provider_error_falls_back(db):
    row = event(db)
    p = Provider(error=True)
    result = await translate_summary(db, row.id, provider=p)
    assert result["status"] == "unavailable" and result["text"] is None
    assert row.summary == EN_SUMMARY
    assert cached_summary_translation(row)["status"] == "unavailable"


@sync_test
async def test_provider_error_reports_reason(db):
    # Un fallo del proveedor devuelve "unavailable" con reason clasificada y la
    # persiste en metadata para diagnóstico sin acceso a logs.
    row = event(db)
    p = Provider(error=True)
    result = await translate_summary(db, row.id, provider=p)
    assert result["status"] == "unavailable"
    assert result["reason"] == "provider"
    assert result["text"] is None
    db.refresh(row)
    record = row.metadata_["summary_translation"]
    assert record["status"] == "unavailable"
    assert record["failure"] == "provider"


@sync_test
async def test_rejected_output_reports_bad_output_reason(db):
    # El proveedor responde pero la salida no pasa las validaciones: la causa no
    # es el proveedor, es la salida rechazada.
    row = event(db)
    p = Provider("Texto sin numeros")  # el original tiene 12%: la firma no casa
    result = await translate_summary(db, row.id, provider=p)
    assert result["status"] == "unavailable"
    assert result["reason"] == "bad_output"
    db.refresh(row)
    assert row.metadata_["summary_translation"]["failure"] == "bad_output"


@sync_test
async def test_translated_result_has_no_reason(db):
    row = event(db)
    result = await translate_summary(db, row.id, provider=Provider())
    assert result["status"] == "translated"
    assert "reason" not in result


@sync_test
async def test_cooldown_reports_reason(db):
    row = event(db)
    p = Provider(error=True)
    await translate_summary(db, row.id, provider=p)
    second = await translate_summary(db, row.id, provider=p)
    assert second["status"] == "unavailable"
    assert second["reason"] == "cooldown"


class TimeoutProvider(Provider):
    async def complete(self, request):
        raise TimeoutError("provider timed out")


@sync_test
async def test_timeout_failure_cools_down_one_minute(db):
    # Timeout del proveedor: único fallo con reintento a 1 min (cada reintento
    # consume cuota diaria; el resto de fallos espera 10 min).
    row = event(db)
    await translate_summary(db, row.id, provider=TimeoutProvider())
    db.refresh(row)
    record = row.metadata_["summary_translation"]
    assert record["failure"] == "provider_timeout"
    delta = datetime.fromisoformat(record["retry_after"]) - datetime.fromisoformat(record["created_at"])
    assert delta <= timedelta(minutes=1)


@sync_test
async def test_provider_failure_cools_down_one_minute(db):
    # Fallo genérico de proveedor: cooldown corto (1 min); solo bad_output espera 10.
    row = event(db)
    await translate_summary(db, row.id, provider=Provider(error=True))
    db.refresh(row)
    record = row.metadata_["summary_translation"]
    assert record["failure"] == "provider"
    delta = datetime.fromisoformat(record["retry_after"]) - datetime.fromisoformat(record["created_at"])
    assert delta <= timedelta(minutes=1)


@sync_test
async def test_bad_output_cools_down_ten_minutes(db):
    # Salida rechazada: 10 min (reintentar no cambia el resultado).
    row = event(db)
    await translate_summary(db, row.id, provider=Provider("Texto sin numeros"))
    db.refresh(row)
    record = row.metadata_["summary_translation"]
    assert record["failure"] == "bad_output"
    delta = datetime.fromisoformat(record["retry_after"]) - datetime.fromisoformat(record["created_at"])
    assert delta >= timedelta(minutes=10)


class RateLimitedProvider(Provider):
    async def complete(self, request):
        from app.llm import ProviderHTTPError
        raise ProviderHTTPError("fake", 429)


@sync_test
async def test_rate_limited_reports_reason_and_short_cooldown(db):
    row = event(db)
    result = await translate_summary(db, row.id, provider=RateLimitedProvider())
    assert result["status"] == "unavailable"
    assert result["reason"] == "provider_rate_limited"
    db.refresh(row)
    record = row.metadata_["summary_translation"]
    assert record["failure"] == "provider_rate_limited"
    delta = datetime.fromisoformat(record["retry_after"]) - datetime.fromisoformat(record["created_at"])
    assert delta <= timedelta(minutes=1)


@sync_test
async def test_chain_falls_back_after_429(db, monkeypatch):
    # La cadena gratuita: un 429 del primer eslabón pasa al siguiente, que traduce.
    import app.services.public_headline_translation as pub
    monkeypatch.setattr(pub, "free_provider_chain", lambda: [(RateLimitedProvider(), "m1"), (Provider(), "m2")])
    row = event(db)
    result = await translate_summary(db, row.id)
    assert result["status"] == "translated"
    assert result["text"] == ES_SUMMARY
    db.refresh(row)
    assert row.metadata_["summary_translation"]["status"] == "translated"
