import asyncio
import json
from functools import wraps
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.entities import Base, NewsEvent, Tenant
from app.services.news_headline_translation import (
    cached_translation,
    display_translation,
    fingerprint,
    translate_headline,
)


def sync_test(func):
    @wraps(func)
    def run(*args, **kwargs):
        return asyncio.run(func(*args, **kwargs))
    return run


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread":False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    from app.services.asts_llm_quota import _LOCAL
    _LOCAL.clear()
    with sessionmaker(engine)() as session:
        session.add_all([Tenant(id=1,external_id="one"),Tenant(id=2,external_id="two")])
        session.commit()
        session.info["tenant_id"] = 1
        yield session
    engine.dispose()


def event(db, title="Η εταιρεία ανακοινώνει αποτελέσματα 2026", tenant=1):
    row=NewsEvent(tenant_id=tenant,title=title,source="Publisher",url="https://publisher.example/article",summary="unchanged",metadata_={"source_headline":title,"connector":"rss"})
    db.add(row);db.commit();return row


class Provider:
    name="fake"
    def __init__(self,text="La empresa anuncia resultados 2026", error=False): self.text=text;self.calls=0;self.error=error
    async def complete(self,request):
        self.calls+=1
        assert request.metadata["tenant_id"] == "1"
        assert "untrusted DATA" in request.messages[0].content
        if self.error: raise RuntimeError("unavailable")
        return SimpleNamespace(text=json.dumps({"text":self.text}),model="fake",usage=SimpleNamespace(input_tokens=0,output_tokens=0,total_tokens=0),degraded=False,warnings=())


@sync_test
async def test_translates_caches_and_preserves_source(db):
    row=event(db);original=row.title;p=Provider()
    first=await translate_headline(db,row.id,provider=p)
    second=await translate_headline(db,row.id,provider=p)
    assert first==second and first["status"]=="translated" and p.calls==1
    assert row.title==original and row.summary=="unchanged"
    assert row.metadata_["source_headline"]==original and row.source=="Publisher"
    assert first["original"]==original and first["machine_translation"] is True
    assert display_translation(row)["text"]==p.text


@sync_test
async def test_request_uses_registered_prompt_and_keeps_tenant_metadata(db):
    from app.services import prompt_registry

    seen=[]
    class Capturing(Provider):
        async def complete(self,request):
            seen.append(request)
            return await super().complete(request)
    row=event(db)
    await translate_headline(db,row.id,provider=Capturing())
    resolved=prompt_registry.get_prompt("news_headline_translation",allow_remote=False)
    assert seen[0].messages[0].content==resolved.text
    assert seen[0].metadata=={**resolved.trace_metadata(),"tenant_id":"1"}


@sync_test
@pytest.mark.parametrize("title",["La empresa anuncia resultados","8-K presentado ante la SEC"])
async def test_latin_titles_skip_without_call(db,title):
    row=event(db,title);p=Provider()
    assert (await translate_headline(db,row.id,provider=p))["status"]=="not_needed"
    assert p.calls==0


@sync_test
@pytest.mark.parametrize("text",["La empresa anuncia resultados 2027","","Η εταιρεία 2026",None])
async def test_bad_output_falls_back_and_cools_down(db,text):
    row=event(db);p=Provider(text)
    assert (await translate_headline(db,row.id,provider=p))["status"]=="unavailable"
    assert (await translate_headline(db,row.id,provider=p))["status"]=="unavailable"
    assert p.calls==1 and display_translation(row) is None


@sync_test
async def test_provider_failure_honest_fallback(db):
    row=event(db);p=Provider(error=True)
    assert (await translate_headline(db,row.id,provider=p))["status"]=="unavailable"
    assert row.title.startswith("Η") and display_translation(row) is None


@sync_test
async def test_cache_invalidated_if_headline_changes(db):
    row=event(db);p=Provider()
    await translate_headline(db,row.id,provider=p)
    row.metadata_={**row.metadata_,"source_headline":"कंपनी ने परिणाम 2026 घोषित किए"};db.commit()
    assert cached_translation(row) is None
    assert (await translate_headline(db,row.id,provider=p))["status"]=="translated"
    assert p.calls==2


@sync_test
async def test_tenant_scope_rejects_other_and_unscoped(db):
    db.info["tenant_id"] = 2
    other=event(db,tenant=2)
    db.info["tenant_id"] = 1
    with pytest.raises(LookupError): await translate_headline(db,other.id,provider=Provider())
    db.info.clear()
    with pytest.raises(PermissionError): await translate_headline(db,other.id,provider=Provider())


@sync_test
async def test_budget_blocks_calls(db,monkeypatch):
    from app.services.budget import BudgetController
    monkeypatch.setattr(BudgetController,"can_spend",lambda *args:False)
    row=event(db);p=Provider()
    assert (await translate_headline(db,row.id,provider=p))["status"]=="unavailable"
    assert p.calls==0


def test_get_reads_cache_only_no_provider_and_original_preserved(db,monkeypatch):
    from app.api.routes.news import news_events
    row=event(db)
    row.metadata_={**row.metadata_,"headline_translation":{"fingerprint":fingerprint(row.title),"status":"translated","text":"La empresa anuncia resultados 2026","target_language":"es","machine_translation":True}}
    db.commit()
    def boom(): raise AssertionError("GET must never call LLM")
    monkeypatch.setattr("app.services.public_headline_translation.free_provider",boom)
    output=news_events(db,limit=10,offset=0,lane=None)
    assert output[0]["title"]==row.title
    assert output[0]["original_headline"]==row.title
    assert output[0]["headline_translation"]["text"].startswith("La empresa")


@sync_test
async def test_quota_block_prevents_provider_call(db,monkeypatch):
    import app.services.news_headline_translation as service
    monkeypatch.setattr(service,"reserve_quota",lambda *args,**kwargs:{"allowed":False})
    row=event(db);p=Provider()
    assert (await translate_headline(db,row.id,provider=p))["status"]=="unavailable"
    assert p.calls==0

@sync_test
async def test_malformed_retry_after_does_not_fail_request(db):
    row=event(db)
    row.metadata_={**row.metadata_,"headline_translation":{"fingerprint":fingerprint(row.title),"status":"pending","retry_after":"bad timestamp"}}
    db.commit()
    assert (await translate_headline(db,row.id,provider=Provider()))["status"]=="translated"

@sync_test
async def test_empty_cached_translation_is_recomputed(db):
    row=event(db)
    row.metadata_={**row.metadata_,"headline_translation":{"fingerprint":fingerprint(row.title),"status":"translated"}}
    db.commit()
    assert display_translation(row) is None
    assert (await translate_headline(db,row.id,provider=Provider()))["status"]=="translated"

@sync_test
@pytest.mark.parametrize(("original", "translated"), [
    ("Η εταιρεία FCF -12 USD 2026", "La empresa FCF +12 USD 2026"),
    ("Η εταιρεία FCF -12 USD 2026", "La empresa FCF 12 USD 2026"),
    ("Η εταιρεία crecimiento 12% 2026", "La empresa crecimiento 12 2026"),
    ("Η εταιρεία FCF 12 USD 2026", "La empresa FCF 12 EUR 2026"),
    ("Η εταιρεία FCF 12 million USD 2026", "La empresa FCF 12 billion USD 2026"),
    ("Η εταιρεία FCF 12 million USD 2026", "La empresa FCF 12 million EUR 2026"),
    ("Η εταιρεία FCF (12) USD 2026", "La empresa FCF 12 USD 2026"),
])
async def test_translation_rejects_changed_financial_dimensions(db, original, translated):
    row=event(db,original)
    assert (await translate_headline(db,row.id,provider=Provider(translated)))["status"]=="unavailable"
    assert display_translation(row) is None

@sync_test
async def test_translation_preserves_valid_signed_currency_percentage(db):
    row=event(db,"Η εταιρεία FCF -12 USD crecimiento 12% 2026")
    p=Provider("La empresa FCF -12 USD crecimiento 12% 2026")
    assert (await translate_headline(db,row.id,provider=p))["status"]=="translated"


@sync_test
@pytest.mark.parametrize("sign", ["-", "+", "−", "–", "—", "﹣", "－", "＋"])
@pytest.mark.parametrize("space", [" ", "\u00a0", "\t", "\n", "\u202f"])
async def test_translation_separated_sign_fails_closed(db, sign, space):
    row=event(db,f"Η εταιρεία FCF {sign}{space}12 USD 2026")
    assert (await translate_headline(db,row.id,provider=Provider("La empresa FCF 12 USD 2026")))["status"]=="unavailable"

@sync_test
async def test_english_headline_translates_with_cache(db):
    row=event(db,"Apple reports earnings 2026")
    p=Provider("Apple anuncia resultados 2026")
    assert (await translate_headline(db,row.id,provider=p))["status"]=="translated"
    assert (await translate_headline(db,row.id,provider=p))["status"]=="translated"
    assert p.calls==1 and row.title=="Apple reports earnings 2026"


class TimeoutProvider(Provider):
    async def complete(self, request):
        raise TimeoutError("provider timed out")


@sync_test
async def test_headline_timeout_cools_down_one_minute_with_reason(db):
    # translate_headline: mismo criterio que el resumen — timeout reintenta a
    # 1 min con reason clasificada; un fallo de proveedor espera 10 min.
    from datetime import datetime, timedelta
    row = event(db)
    result = await translate_headline(db, row.id, provider=TimeoutProvider())
    assert result["status"] == "unavailable"
    assert result["reason"] == "provider_timeout"
    db.refresh(row)
    record = row.metadata_["headline_translation"]
    assert record["failure"] == "provider_timeout"
    delta = datetime.fromisoformat(record["retry_after"]) - datetime.fromisoformat(record["created_at"])
    assert delta <= timedelta(minutes=1)

    row2 = event(db)
    result2 = await translate_headline(db, row2.id, provider=Provider(error=True))
    assert result2["reason"] == "provider"
    db.refresh(row2)
    record2 = row2.metadata_["headline_translation"]
    assert record2["failure"] == "provider"
    delta2 = datetime.fromisoformat(record2["retry_after"]) - datetime.fromisoformat(record2["created_at"])
    assert delta2 <= timedelta(minutes=1)


class RateLimitedProvider(Provider):
    async def complete(self, request):
        from app.llm import ProviderHTTPError
        raise ProviderHTTPError("fake", 429)


@sync_test
async def test_headline_429_reports_reason_and_falls_back(db, monkeypatch):
    # 429 aislado: reason provider_rate_limited y cooldown corto. Y la cadena
    # gratuita pasa al siguiente eslabón, que traduce.
    from datetime import datetime, timedelta
    row = event(db)
    result = await translate_headline(db, row.id, provider=RateLimitedProvider())
    assert result["status"] == "unavailable"
    assert result["reason"] == "provider_rate_limited"
    db.refresh(row)
    record = row.metadata_["headline_translation"]
    assert record["failure"] == "provider_rate_limited"
    delta = datetime.fromisoformat(record["retry_after"]) - datetime.fromisoformat(record["created_at"])
    assert delta <= timedelta(minutes=1)

    import app.services.public_headline_translation as pub
    monkeypatch.setattr(pub, "free_provider_chain", lambda: [(RateLimitedProvider(), "m1"), (Provider(), "m2")])
    row2 = event(db)
    result2 = await translate_headline(db, row2.id)
    assert result2["status"] == "translated"
    assert result2["text"] == "La empresa anuncia resultados 2026"


@sync_test
async def test_locked_row_returns_busy_instead_of_waiting(db, monkeypatch):
    """La consulta de lease es sincrona en un handler async: si otra transaccion
    tiene la fila bloqueada debe devolver busy (skip_locked), no esperar y
    congelar el event loop del backend."""
    row = event(db)
    p = Provider()
    real = db.scalar
    seen = []

    def scalar(stmt, *a, **k):
        fu = getattr(stmt, "_for_update_arg", None)
        if fu is not None:
            seen.append(fu.skip_locked)
            return None  # simula fila bloqueada: skip_locked no devuelve nada
        return real(stmt, *a, **k)

    monkeypatch.setattr(db, "scalar", scalar)
    out = await translate_headline(db, row.id, provider=p)
    assert seen == [True], "el lease debe usar skip_locked"
    assert out["status"] == "busy" and out["reason"] == "busy" and p.calls == 0


@sync_test
async def test_db_access_does_not_block_the_event_loop(db, monkeypatch):
    """Una consulta lenta (lock, pool) no debe congelar el loop de todo el backend."""
    import time

    row = event(db, "La empresa anuncia resultados")  # latino: solo hace la primera consulta
    real = db.scalar

    def slow_scalar(*a, **k):
        time.sleep(0.5)
        return real(*a, **k)

    monkeypatch.setattr(db, "scalar", slow_scalar)
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.05)
            ticks += 1

    task = asyncio.create_task(ticker())
    out = await translate_headline(db, row.id, provider=Provider())
    task.cancel()
    assert out["status"] == "not_needed"
    assert ticks >= 5, f"el event loop estuvo bloqueado (ticks={ticks})"


@sync_test
async def test_no_sql_runs_on_the_event_loop_thread(db, monkeypatch):
    """Ninguna consulta debe ejecutarse en el hilo del loop (rutas busy y traduccion completa)."""
    import threading

    from sqlalchemy import event as sa_event

    loop_thread = threading.get_ident()
    on_loop = []
    sa_event.listen(db.get_bind(), "before_cursor_execute", lambda *a, **k: on_loop.append(a[2]) if threading.get_ident() == loop_thread else None)
    row = event(db)
    row_id = row.id
    on_loop.clear()
    # camino traducido completo
    assert (await translate_headline(db, row_id, provider=Provider()))["status"] == "translated"
    # camino busy por fila bloqueada (rollback + resultado)
    row2 = event(db, "Η εταιρεία ανακοινώνει άλλα αποτελέσματα 2027")
    row2_id = row2.id
    real = db.scalar
    on_loop.clear()

    def scalar(stmt, *a, **k):
        if getattr(stmt, "_for_update_arg", None) is not None:
            return None
        return real(stmt, *a, **k)

    monkeypatch.setattr(db, "scalar", scalar)
    assert (await translate_headline(db, row2_id, provider=Provider()))["status"] == "busy"
    assert on_loop == [], f"SQL en el hilo del event loop: {on_loop[:3]}"
