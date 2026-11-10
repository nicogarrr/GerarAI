"""Bordes de public_headline_translation no cubiertos por las suites existentes.

Cubre: free_provider_chain (cadena vacia y completa), estado busy con los dos
slots ocupados, barrido de entradas expiradas y desalojo al llegar a 512. El
estado global (_cache) se restaura en cada test; nada toca red ni proveedores
reales (LLM simulado con objetos falsos).

Nota de cobertura: la rama 137-138 (recheck de cache que acierta tras el
`async with _slots`) es inalcanzable en un solo event loop: cuando el semaforo
esta agotado, `_slots.locked()` ya devuelve busy en la linea 132, y adquirir un
slot libre no cede el control, asi que ninguna otra tarea puede rellenar la
cache entre ambas lecturas. Se deja sin cubrir a proposito.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from app.services import public_headline_translation as pht
from app.services.news_headline_translation import fingerprint

TEXTO = "カタカナのヘッドライン"


@pytest.fixture
def cache_limpia():
    snapshot = dict(pht._cache)
    pht._cache.clear()
    yield
    pht._cache.clear()
    pht._cache.update(snapshot)


def _db():
    return SimpleNamespace(info={"tenant_id": 1})


def _provider_falso(name="fake"):
    return SimpleNamespace(name=name)


def test_free_provider_chain_vacia(monkeypatch):
    monkeypatch.setattr(pht, "free_provider", lambda: (None, None))
    import app.llm.chat_provider as cp

    monkeypatch.setattr(cp, "_groq_backup", lambda settings, _: None)
    monkeypatch.setattr(cp, "_gemini_backup", lambda settings, _: None)
    assert pht.free_provider_chain() == []


def test_free_provider_chain_completa(monkeypatch):
    principal = _provider_falso("principal")
    groq = _provider_falso("groq")
    gemini = _provider_falso("gemini")
    monkeypatch.setattr(pht, "free_provider", lambda: (principal, "m0"))
    import app.llm.chat_provider as cp

    monkeypatch.setattr(cp, "_groq_backup", lambda settings, _: groq)
    monkeypatch.setattr(cp, "_gemini_backup", lambda settings, _: gemini)
    chain = pht.free_provider_chain()
    assert chain == [
        (principal, "m0"),
        (groq, cp.GROQ_MODEL),
        (gemini, cp.GEMINI_MODEL),
        (gemini, cp.GEMINI_MODEL_2),
    ]


def test_free_provider_chain_backups_mal_configurados(monkeypatch):
    principal = _provider_falso("principal")
    monkeypatch.setattr(pht, "free_provider", lambda: (principal, "m0"))
    import app.llm.chat_provider as cp

    def roto(settings, _):
        raise ValueError("sin clave")

    monkeypatch.setattr(cp, "_groq_backup", roto)
    monkeypatch.setattr(cp, "_gemini_backup", roto)
    assert pht.free_provider_chain() == [(principal, "m0")]


def test_translate_busy_con_los_dos_slots_ocupados(cache_limpia):
    async def run():
        await pht._slots.acquire()
        await pht._slots.acquire()
        try:
            return await pht.translate_external_headline(_db(), TEXTO)
        finally:
            pht._slots.release()
            pht._slots.release()

    result = asyncio.run(asyncio.wait_for(run(), timeout=10))
    assert result["status"] == "busy"
    assert result["text"] is None and result["original"] == TEXTO


def test_translate_barre_expiradas(cache_limpia, monkeypatch):
    # 510 vivas + 1 expirada: sin desalojo, solo el barrido puede quitarla.
    monkeypatch.setattr(pht, "free_provider_chain", lambda: [])
    ahora = time.monotonic()
    for i in range(510):
        pht._cache[(1000 + i, f"fp{i}")] = (ahora + 1000, {"status": "unavailable"})
    pht._cache[(2, "expirada")] = (ahora - 1, {"status": "unavailable"})
    assert len(pht._cache) == 511

    result = asyncio.run(pht.translate_external_headline(_db(), TEXTO))

    assert result["status"] == "unavailable"
    assert (2, "expirada") not in pht._cache
    assert len(pht._cache) == 511
    ttl = pht._cache[(1, fingerprint(TEXTO))][0] - time.monotonic()
    assert 590 < ttl <= 600


def test_translate_desaloja_la_mas_antigua_en_512(cache_limpia, monkeypatch):
    monkeypatch.setattr(pht, "free_provider_chain", lambda: [])
    ahora = time.monotonic()
    for i in range(512):
        pht._cache[(1000 + i, f"fp{i}")] = (ahora + 1000, {"status": "unavailable"})
    assert len(pht._cache) == 512

    result = asyncio.run(pht.translate_external_headline(_db(), TEXTO))

    assert result["status"] == "unavailable"
    assert (1000, "fp0") not in pht._cache
    assert len(pht._cache) == 512
    assert (1, fingerprint(TEXTO)) in pht._cache
