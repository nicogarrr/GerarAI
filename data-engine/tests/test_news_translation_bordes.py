"""news_headline_translation: bordes del titular medidos en frio sobre main.

Cubiertas: 247 (clasifica por tipo), 275 (busy en vuelo), 295-297 (cache
traducida que aparece en el slot), 298-301 (cooldown en el slot -> busy),
303-306 (not_needed en el slot), 321 (cadena vacia), 335-336 (deadline
agotado antes del primer intento), 365-367 (huella cambiada tras traducir)
y 408 (cache de resumen con texto vacio -> None).

Tecnica: el scalar con contador simula el cambio concurrente entre la primera
lectura y la relectura del slot (populate_existing): la segunda llamada
escribe el cambio con commit real a SQLite antes de releer. La cuota corre en
local con _LOCAL fresco via monkeypatch (restaura el dict original, nunca
clear). BudgetController real contra SQLite (gasto 0 -> puede gastar).

NO prueba (declarado): el cluster del resumen (432-536) ni
_scaled_amount_equivalent (617-623) — siguiente PR del mismo modulo. El LLM
real nunca: proveedor y cadena gratuita doblados; reserve_quota solo usa
Redis cuando is_production (aqui False, verificado en asts_llm_quota.py:71).
"""
import asyncio
import json
from datetime import UTC, datetime, timedelta
from functools import wraps
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.services.news_headline_translation as nht
import app.services.public_headline_translation as pub
from app.models.entities import Base, NewsEvent, Tenant

TITULO = "Η εταιρεία ανακοινώνει αποτελέσματα 2026"
TRADUCCION = "La empresa anuncia resultados 2026"


def sync_test(func):
    @wraps(func)
    def run(*args, **kwargs):
        return asyncio.run(func(*args, **kwargs))
    return run


@pytest.fixture(autouse=True)
def _cuota_local_limpia(monkeypatch):
    """_LOCAL fresco por test; monkeypatch restaura el dict original."""
    import app.services.asts_llm_quota as quota

    monkeypatch.setattr(quota, "_LOCAL", {})


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(engine)() as session:
        session.add_all([Tenant(id=1, external_id="one"), Tenant(id=2, external_id="two")])
        session.commit()
        session.info["tenant_id"] = 1
        yield session
    engine.dispose()


def event(db, title=TITULO, tenant=1, summary="resumen sin traducir"):
    row = NewsEvent(tenant_id=tenant, title=title, source="Publisher",
                    url="https://publisher.example/article", summary=summary,
                    metadata_={"source_headline": title, "connector": "rss"})
    db.add(row)
    db.commit()
    return row


class Provider:
    name = "fake"

    def __init__(self, text=TRADUCCION):
        self.text = text
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        return SimpleNamespace(
            text=json.dumps({"text": self.text}), model="fake",
            usage=SimpleNamespace(input_tokens=0, output_tokens=0, total_tokens=0),
            degraded=False, warnings=())


def _scalar_que_cambia(db, monkeypatch, cambio):
    """Primera lectura intacta; en la relectura del slot aplica `cambio` y
    commitea para que populate_existing lo vea."""
    scalar_real = db.scalar
    llamadas = {"n": 0}

    def _scalar(*args, **kwargs):
        llamadas["n"] += 1
        if llamadas["n"] == 2:
            cambio()
        return scalar_real(*args, **kwargs)

    monkeypatch.setattr(db, "scalar", _scalar)
    return llamadas


def test_clasifica_fallo_desconocido_por_nombre_de_tipo():
    """Linea 247: ni 429, ni timeout, ni RuntimeError -> el nombre del tipo."""
    assert nht._classify_translation_failure(ValueError("boom")) == "ValueError"


def test_cache_resumen_none_con_texto_vacio(db):
    """Linea 408: status translated pero texto vacio -> cache invalida."""
    row = event(db)
    row.metadata_ = {**row.metadata_, "summary_translation": {
        "fingerprint": nht.summary_fingerprint(nht.original_summary(row)),
        "status": "translated", "text": "   ",
    }}
    assert nht.cached_summary_translation(row) is None


@sync_test
async def test_titular_busy_si_ya_en_vuelo(db, monkeypatch):
    """Linea 275: la clave (tenant, evento) ya esta en vuelo -> busy."""
    row = event(db)
    monkeypatch.setattr(nht, "_inflight", {(1, row.id)})
    p = Provider()
    res = await nht.translate_headline(db, row.id, provider=p)
    assert res["status"] == "busy" and res["reason"] == "busy"
    assert p.calls == 0


@sync_test
async def test_titular_cache_traducida_aparece_en_el_slot(db, monkeypatch):
    """Lineas 295-297: la cache aparece entre la primera lectura y el slot."""
    row = event(db)

    def _aparece_cache():
        row.metadata_ = {**row.metadata_, "headline_translation": {
            "fingerprint": nht.fingerprint(TITULO), "status": "translated",
            "text": TRADUCCION, "target_language": "es",
            "machine_translation": True,
            "created_at": datetime.now(UTC).isoformat(),
        }}
        db.commit()

    _scalar_que_cambia(db, monkeypatch, _aparece_cache)
    p = Provider()
    res = await nht.translate_headline(db, row.id, provider=p)
    assert res["status"] == "translated" and res["text"] == TRADUCCION
    assert p.calls == 0


@sync_test
async def test_titular_cooldown_en_el_slot_es_busy(db, monkeypatch):
    """Lineas 298-301: cooldown activo descubierto en el slot -> busy."""
    row = event(db)

    def _aparece_cooldown():
        row.metadata_ = {**row.metadata_, "headline_translation": {
            "fingerprint": nht.fingerprint(TITULO), "status": "unavailable",
            "failure": "provider", "chain_failures": 1,
            "retry_after": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
        }}
        db.commit()

    _scalar_que_cambia(db, monkeypatch, _aparece_cooldown)
    p = Provider()
    res = await nht.translate_headline(db, row.id, provider=p)
    assert res["status"] == "busy" and res["reason"] == "busy"
    assert p.calls == 0


@sync_test
async def test_titular_not_needed_en_el_slot(db, monkeypatch):
    """Lineas 303-306: la relectura trae headline_from_source=False."""
    row = event(db)

    def _marca_de_fuente():
        row.metadata_ = {**row.metadata_, "headline_from_source": False}
        db.commit()

    _scalar_que_cambia(db, monkeypatch, _marca_de_fuente)
    p = Provider()
    res = await nht.translate_headline(db, row.id, provider=p)
    assert res["status"] == "not_needed"
    assert p.calls == 0


@sync_test
async def test_titular_cadena_vacia_clasifica_provider(db, monkeypatch):
    """Linea 321: sin eslabones verificados -> RuntimeError -> 'provider'."""
    row = event(db)
    monkeypatch.setattr(pub, "free_provider_chain", lambda: [])
    res = await nht.translate_headline(db, row.id, provider=None)
    assert res["status"] == "unavailable" and res["reason"] == "provider"


@sync_test
async def test_titular_deadline_agotado_antes_del_primer_intento(db, monkeypatch):
    """Lineas 335-336: presupuesto de tiempo agotado -> provider_timeout y el
    proveedor no llega a llamarse."""
    row = event(db)
    monkeypatch.setattr(nht, "HEADLINE_TOTAL_SECONDS", 0)
    p = Provider()
    res = await nht.translate_headline(db, row.id, provider=p)
    assert res["status"] == "unavailable" and res["reason"] == "provider_timeout"
    assert p.calls == 0


@sync_test
async def test_titular_huella_cambiada_tras_traducir(db, monkeypatch):
    """Lineas 365-367: el titular cambia durante la traduccion -> 'changed'
    y la traduccion se descarta (nunca se cachea contra otro original)."""
    row = event(db)
    original_real = nht.original_headline
    llamadas = {"n": 0}

    def _original_que_cambia(ev):
        llamadas["n"] += 1
        if llamadas["n"] >= 3:
            return "Τίτλος εντελώς αλλαγμένος τώρα"
        return original_real(ev)

    monkeypatch.setattr(nht, "original_headline", _original_que_cambia)
    p = Provider()
    res = await nht.translate_headline(db, row.id, provider=p)
    assert res["status"] == "unavailable" and res["reason"] == "changed"
    assert p.calls == 1
    assert nht.cached_translation(row) is None
