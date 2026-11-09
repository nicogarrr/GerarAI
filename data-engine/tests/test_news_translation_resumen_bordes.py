"""news_headline_translation: bordes del resumen + equivalencia numerica.

Cubiertas (medido en frio sobre main): 432 (sin tenant), 435 (evento
inexistente), 447 (busy en vuelo), 453 (presupuesto), 456-459 (fila
bloqueada -> busy), 463-465 (cache en el slot), 467-469 (cooldown en el
slot), 472-474 (not_needed en el slot), 489 (cadena vacia), 494 y 526-531
(cuota agotada -> 'quota' por la via del except exterior), 534-536 (huella
cambiada) y 617/620/622-623 de _scaled_amount_equivalent.

Misma tecnica que test_news_translation_bordes.py: scalar con contador que en
la relectura escribe el cambio con commit real a SQLite (simula el cambio
concurrente que populate_existing lee; el conteo se filtra por statement de
news_events porque can_spend tambien consulta por db.scalar); cuota local con
_LOCAL fresco via monkeypatch (restaura el dict original); LLM siempre doblado.

NO prueba (declarado): el LLM real (proveedor y cadena doblados; reserve_quota
solo usa Redis con is_production, False aqui — asts_llm_quota.py:71);
SUMMARY_TOTAL_SECONDS=0 no se repite (misma rama ya cubierta en el titular).
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

EN_SUMMARY = "The company said revenue grew 12% in the quarter and it raises guidance for the year."
ES_SUMMARY = "La empresa dijo que los ingresos crecieron un 12% en el trimestre y eleva la guía para el año."


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


def event(db, summary=EN_SUMMARY, tenant=1):
    row = NewsEvent(tenant_id=tenant, title="Titular", source="Publisher",
                    url="https://publisher.example/article", summary=summary,
                    metadata_={"connector": "rss"})
    db.add(row)
    db.commit()
    return row


class Provider:
    name = "fake"

    def __init__(self, text=ES_SUMMARY):
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

    def _scalar(stmt, *args, **kwargs):
        # Solo la relectura de NewsEvent (can_spend consulta otras tablas).
        if "news_events" in str(stmt).lower():
            llamadas["n"] += 1
            if llamadas["n"] == 2:
                cambio()
        return scalar_real(stmt, *args, **kwargs)

    monkeypatch.setattr(db, "scalar", _scalar)
    return llamadas


@sync_test
async def test_resumen_sin_tenant_es_permission_error(db):
    """Linea 432."""
    row = event(db)
    db.info.clear()
    with pytest.raises(PermissionError):
        await nht.translate_summary(db, row.id, provider=Provider())


@sync_test
async def test_resumen_evento_inexistente_es_lookup_error(db):
    """Linea 435."""
    with pytest.raises(LookupError):
        await nht.translate_summary(db, 999999, provider=Provider())


@sync_test
async def test_resumen_busy_si_ya_en_vuelo(db, monkeypatch):
    """Linea 447: la clave (tenant, -evento) ya esta en vuelo -> busy."""
    row = event(db)
    monkeypatch.setattr(nht, "_inflight", {(1, -row.id)})
    p = Provider()
    res = await nht.translate_summary(db, row.id, provider=p)
    assert res["status"] == "busy" and res["reason"] == "busy"
    assert p.calls == 0


@sync_test
async def test_resumen_presupuesto_agotado(db, monkeypatch):
    """Linea 453: can_spend False -> unavailable 'budget', sin llamada."""
    from app.services.budget import BudgetController

    row = event(db)
    monkeypatch.setattr(BudgetController, "can_spend", lambda *args: False)
    p = Provider()
    res = await nht.translate_summary(db, row.id, provider=p)
    assert res["status"] == "unavailable" and res["reason"] == "budget"
    assert p.calls == 0


@sync_test
async def test_resumen_fila_bloqueada_es_busy(db, monkeypatch):
    """Lineas 456-459: skip_locked devuelve None -> busy trazado."""
    row = event(db)
    scalar_real = db.scalar
    llamadas = {"n": 0}

    def _scalar_bloqueado(stmt, *args, **kwargs):
        # Solo la relectura de NewsEvent (can_spend consulta otras tablas).
        if "news_events" in str(stmt).lower():
            llamadas["n"] += 1
            if llamadas["n"] == 2:
                return None
        return scalar_real(stmt, *args, **kwargs)

    monkeypatch.setattr(db, "scalar", _scalar_bloqueado)
    res = await nht.translate_summary(db, row.id, provider=Provider())
    assert res["status"] == "busy" and res["reason"] == "busy"


@sync_test
async def test_resumen_cache_traducida_aparece_en_el_slot(db, monkeypatch):
    """Lineas 463-465: la cache aparece entre la primera lectura y el slot."""
    row = event(db)

    def _aparece_cache():
        row.metadata_ = {**row.metadata_, "summary_translation": {
            "fingerprint": nht.summary_fingerprint(EN_SUMMARY),
            "status": "translated", "text": ES_SUMMARY,
            "target_language": "es", "machine_translation": True,
            "created_at": datetime.now(UTC).isoformat(),
        }}
        db.commit()

    _scalar_que_cambia(db, monkeypatch, _aparece_cache)
    p = Provider()
    res = await nht.translate_summary(db, row.id, provider=p)
    assert res["status"] == "translated" and res["text"] == ES_SUMMARY
    assert p.calls == 0


@sync_test
async def test_resumen_cooldown_en_el_slot_es_busy(db, monkeypatch):
    """Lineas 467-469: cooldown activo descubierto en el slot -> busy."""
    row = event(db)

    def _aparece_cooldown():
        row.metadata_ = {**row.metadata_, "summary_translation": {
            "fingerprint": nht.summary_fingerprint(EN_SUMMARY),
            "status": "unavailable", "failure": "provider", "chain_failures": 1,
            "retry_after": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
        }}
        db.commit()

    _scalar_que_cambia(db, monkeypatch, _aparece_cooldown)
    p = Provider()
    res = await nht.translate_summary(db, row.id, provider=p)
    assert res["status"] == "busy" and res["reason"] == "busy"
    assert p.calls == 0


@sync_test
async def test_resumen_not_needed_en_el_slot(db, monkeypatch):
    """Lineas 472-474: la relectura trae un resumen demasiado corto."""
    row = event(db)

    def _acorta_resumen():
        row.summary = "ab"
        db.commit()

    _scalar_que_cambia(db, monkeypatch, _acorta_resumen)
    p = Provider()
    res = await nht.translate_summary(db, row.id, provider=p)
    assert res["status"] == "not_needed"
    assert p.calls == 0


@sync_test
async def test_resumen_cadena_vacia_clasifica_provider(db, monkeypatch):
    """Linea 489: sin eslabones verificados -> RuntimeError -> 'provider'."""
    row = event(db)
    monkeypatch.setattr(pub, "free_provider_chain", lambda: [])
    res = await nht.translate_summary(db, row.id, provider=None)
    assert res["status"] == "unavailable" and res["reason"] == "provider"


@sync_test
async def test_resumen_cuota_agotada_clasifica_quota(db, monkeypatch):
    """Lineas 494 y 526-531: cuota denegada -> RuntimeError 'request limit'
    -> except exterior -> rollback -> 'quota', sin llamada al proveedor."""
    row = event(db)
    monkeypatch.setattr(nht, "reserve_quota", lambda *a, **k: {"allowed": False})
    p = Provider()
    res = await nht.translate_summary(db, row.id, provider=p)
    assert res["status"] == "unavailable" and res["reason"] == "quota"
    assert p.calls == 0


@sync_test
async def test_resumen_huella_cambiada_tras_traducir(db, monkeypatch):
    """Lineas 534-536: el resumen cambia durante la traduccion -> 'changed'
    y la traduccion se descarta."""
    row = event(db)
    original_real = nht.original_summary
    llamadas = {"n": 0}

    def _original_que_cambia(ev):
        llamadas["n"] += 1
        if llamadas["n"] >= 3:
            return "Completely different summary written concurrently."
        return original_real(ev)

    monkeypatch.setattr(nht, "original_summary", _original_que_cambia)
    p = Provider()
    res = await nht.translate_summary(db, row.id, provider=p)
    assert res["status"] == "unavailable" and res["reason"] == "changed"
    assert p.calls == 1
    assert nht.cached_summary_translation(row) is None


def test_equivalencia_cantidades_distintas_rechaza():
    """Misma divisa, cantidad distinta -> no equivalente (trazado: sale por
    el guarda de cantidades, 613-614)."""
    assert nht._scaled_amount_equivalent(
        "$72 billion", "73.000 millones de dólares") is False


def test_equivalencia_marca_de_dimension_en_residual_rechaza():
    """Linea 617: queda un '%' suelto fuera de la cantidad -> no equivalente."""
    assert nht._scaled_amount_equivalent(
        "$72 billion, up 5%", "72.000 millones de dólares, un 5% más") is False


def test_equivalencia_numero_ambiguo_falla_cerrado():
    """Linea 620: '+ 5' (signo, espacio, digito) es ambiguo -> no equivalente
    aunque la cantidad principal cuadre."""
    assert nht._scaled_amount_equivalent(
        "$72 billion in + 5 stores",
        "72.000 millones de dólares en 5 tiendas") is False


def test_equivalencia_entrada_no_texto_falla_cerrado():
    """Lineas 622-623: entrada de tipo no texto -> except defensivo -> False."""
    assert nht._scaled_amount_equivalent(None, "72.000 millones de dólares") is False
