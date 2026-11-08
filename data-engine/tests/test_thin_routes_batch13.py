"""Huecos de cobertura en news (lote 13).

Medicion previa (mismo metodo, tests que referencian el modulo): news 62,6 %.
Se cubren: translate-external, /manual, /ingest, _is_off_topic,
_related_tickers_for_rows (ramas cluster/story/plana y su fallo), el endpoint
principal news_events (filtros ticker/tickers/lane, paginacion keyset entre
chunks, skips de portada, clusters 13F, absorcion de historias, carril social,
frescura macro y fallback de archivo), second-order y las traducciones.

Que NO se prueba aqui: nada de HTTP ni auth; ninguna base de datos real (el
SQL del feed se construye pero va contra una db falsa que devuelve chunks
programados: el filtrado SQL real, el keyset real y los indices parciales NO
se prueban); NewsService, los servicios de traduccion, related_for_events y
analyze_second_order van doblados (solo delegacion); los predicados de portada
(bufetes, visor, posicion, firma de historia) van doblados salvo que se diga.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.api.routes import news as n

FECHA = datetime(2026, 11, 8, 12, 0, 0, tzinfo=UTC)


def run_async(coro):
    return asyncio.run(coro)


def evento(id=1, metadata=None, source="Reuters", company_id=1, title="Titular"):
    return SimpleNamespace(
        id=id, date=FECHA, title=title, summary="Resumen", source=source,
        url="https://ejemplo.com/n", event_type="news", materiality_score=5,
        impact_direction=None, requires_update=False, metadata_=metadata or {},
    )


EMPRESA = SimpleNamespace(id=1, ticker="ASTS")


class DbFalsa:
    """db.execute(...).all() devuelve los chunks programados, en orden."""

    def __init__(self, chunks):
        self._chunks = list(chunks)

    def execute(self, stmt):
        chunk = self._chunks.pop(0) if self._chunks else []
        return SimpleNamespace(all=lambda: chunk)


def _aplanar_portada(monkeypatch):
    """Predicados de portada todos benignos; cada test los retuerce a gusto."""
    monkeypatch.setattr(n, "_is_off_topic", lambda e, c: False)
    monkeypatch.setattr(n, "is_viewer_link_only", lambda t, s: False)
    monkeypatch.setattr(n, "is_law_firm_solicitation", lambda h, s: False)
    monkeypatch.setattr(n, "is_position_change_headline", lambda h: False)
    monkeypatch.setattr(n, "original_headline", lambda e: e.title)
    monkeypatch.setattr(n, "display_translation", lambda e: None)
    monkeypatch.setattr(n, "display_summary_translation", lambda e: None)
    monkeypatch.setattr(n, "related_for_events", lambda db, items: {})
    monkeypatch.setattr(n, "event_signature", lambda e, c: {"sig"})
    monkeypatch.setattr(n, "exact_key", lambda h: h)

    class IndiceFalso:
        def __init__(self):
            self.groups = []

        def find(self, event, company, sig):
            return None

        def add(self, group):
            self.groups.append(group)
            return len(self.groups) - 1

    monkeypatch.setattr(n, "StoryClusterIndex", IndiceFalso)


# --- endpoints pequenos -------------------------------------------------------


def test_translate_externo_delega(monkeypatch):
    async def traduce(db, headline):
        return {"translation": headline.upper()}

    monkeypatch.setattr(n, "translate_external_headline", traduce)
    payload = n.ExternalHeadlineRequest(headline="hello world")
    assert run_async(n.translate_external(payload, db=Mock())) == {"translation": "HELLO WORLD"}


def test_manual_news_delega(monkeypatch):
    visto = {}
    monkeypatch.setattr(
        n,
        "NewsService",
        lambda: SimpleNamespace(
            analyze_manual_news=lambda db, text, source, url: visto.update(
                text=text, source=source, url=url) or "ok"
        ),
    )
    payload = SimpleNamespace(text="texto", source="manual", url=None)
    assert n.manual_news(payload, db=Mock()) == "ok"
    assert visto["text"] == "texto"


def test_ingest_news_delega(monkeypatch):
    monkeypatch.setattr(
        n,
        "NewsService",
        lambda: SimpleNamespace(ingest_news_items=lambda db, items, source: {"n": len(items)}),
    )
    payload = SimpleNamespace(items=[{"t": 1}, {"t": 2}], source="feed")
    assert n.ingest_news(payload, db=Mock()) == {"n": 2}


# --- _is_off_topic --------------------------------------------------------------


def test_off_topic_sin_empresa_es_falso():
    assert n._is_off_topic(evento(), None) is False


def test_off_topic_titular_no_de_fuente_es_falso():
    assert n._is_off_topic(evento(metadata={"headline_from_source": False}), EMPRESA) is False


def test_off_topic_nombre_estricto(monkeypatch):
    monkeypatch.setattr(n, "fails_strict_name", lambda c, texto: True)
    assert n._is_off_topic(evento(), EMPRESA) is True


def test_off_topic_solo_prefijo_ticker(monkeypatch):
    monkeypatch.setattr(n, "fails_strict_name", lambda c, texto: False)
    monkeypatch.setattr(n, "_only_ticker_prefix_mention", lambda c, t, s: True)
    assert n._is_off_topic(evento(), EMPRESA) is True


# --- _related_tickers_for_rows ---------------------------------------------------


def test_related_por_tipo_de_fila(monkeypatch):
    visto = {}

    def relaciona(db, items):
        visto["items"] = items
        return {1: [{"ticker": "ASTS"}]}

    monkeypatch.setattr(n, "related_for_events", relaciona)
    e = evento(1)
    grupo = SimpleNamespace(event=e, company=EMPRESA)
    rows = [("cluster", ("k",)), ("story", 0), (e, EMPRESA)]
    result = n._related_tickers_for_rows(Mock(), rows, {}, [grupo])
    # La fila cluster no entra en la tira; story y plana si.
    assert [item[0] for item in visto["items"]] == [1, 1]
    assert result == {1: [{"ticker": "ASTS"}]}


def test_related_fallo_no_tumba_el_feed(monkeypatch):
    def roto(db, items):
        raise ConnectionError("precios caidos")

    monkeypatch.setattr(n, "related_for_events", roto)
    e = evento(1)
    assert n._related_tickers_for_rows(Mock(), [(e, EMPRESA)], {}, []) == {}


# --- news_events: filtros --------------------------------------------------------


def test_feed_filtro_ticker_fila_plana(monkeypatch):
    _aplanar_portada(monkeypatch)
    db = DbFalsa([[(evento(9), EMPRESA)]])
    result = n.news_events(db=db, limit=10, offset=0, lane=None, ticker="asts", tickers=None)
    assert result[0]["id"] == 9
    assert result[0]["ticker"] == "ASTS"


def test_feed_tickers_csv_sanea(monkeypatch):
    _aplanar_portada(monkeypatch)
    db = DbFalsa([[(evento(9), EMPRESA)]])
    result = n.news_events(
        db=db, limit=10, offset=0, lane=None, ticker=None,
        tickers="ASTS, ,muy-largo-no-valido?,T.L",
    )
    assert result[0]["id"] == 9


def test_feed_tickers_todos_invalidos_no_rompe(monkeypatch):
    _aplanar_portada(monkeypatch)
    db = DbFalsa([[ ]])
    result = n.news_events(db=db, limit=10, offset=0, lane=None, ticker=None, tickers="??,!!")
    assert result == []


def test_feed_carril_empresa(monkeypatch):
    _aplanar_portada(monkeypatch)
    db = DbFalsa([[(evento(3), EMPRESA)]])
    result = n.news_events(db=db, limit=10, offset=0, lane="empresa", ticker=None, tickers=None)
    assert result[0]["id"] == 3


def test_feed_carril_gobierno(monkeypatch):
    _aplanar_portada(monkeypatch)
    db = DbFalsa([[(evento(4, metadata={"news_lane": "gobierno"}), None)]])
    result = n.news_events(db=db, limit=10, offset=0, lane="gobierno", ticker=None, tickers=None)
    assert result[0]["news_lane"] == "gobierno"


def test_feed_carril_macro_fresco(monkeypatch):
    _aplanar_portada(monkeypatch)
    db = DbFalsa([[(evento(5, metadata={"news_lane": "macro"}), None)]])
    result = n.news_events(db=db, limit=10, offset=0, lane="macro", ticker=None, tickers=None)
    assert result[0]["archive"] is False


def test_feed_macro_sin_frescura_sirve_archivo(monkeypatch):
    _aplanar_portada(monkeypatch)
    # Primer _scan (fresco) vacio; el fallback de archivo devuelve una fila.
    db = DbFalsa([[], [(evento(6, metadata={"news_lane": "macro"}), None)]])
    result = n.news_events(db=db, limit=10, offset=0, lane="macro", ticker=None, tickers=None)
    assert result[0]["archive"] is True
    assert result[0]["id"] == 6


# --- news_events: bucle de escaneo ------------------------------------------------


def test_feed_segunda_pagina_keyset(monkeypatch):
    # Primer chunk lleno (200) pero todo off-topic: se pide el siguiente chunk
    # con el keyset y el segundo viene vacio -> break.
    monkeypatch.setattr(n, "_is_off_topic", lambda e, c: True)
    chunk_lleno = [(evento(i), EMPRESA) for i in range(200)]
    db = DbFalsa([chunk_lleno, []])
    result = n.news_events(db=db, limit=10, offset=0, lane=None, ticker=None, tickers=None)
    assert result == []


def test_feed_salta_enlaces_de_visor(monkeypatch):
    _aplanar_portada(monkeypatch)
    monkeypatch.setattr(n, "is_viewer_link_only", lambda t, s: True)
    db = DbFalsa([[(evento(1), EMPRESA)]])
    assert n.news_events(db=db, limit=10, offset=0, lane=None, ticker=None, tickers=None) == []


def test_feed_salta_spam_de_bufetes(monkeypatch):
    _aplanar_portada(monkeypatch)
    monkeypatch.setattr(n, "is_law_firm_solicitation", lambda h, s: True)
    db = DbFalsa([[(evento(1), EMPRESA)]])
    assert n.news_events(db=db, limit=10, offset=0, lane=None, ticker=None, tickers=None) == []


def test_feed_salta_agencia_sin_empresa(monkeypatch):
    _aplanar_portada(monkeypatch)
    agencia = sorted(n.PRESS_WIRE_SOURCES)[0]
    db = DbFalsa([[(evento(1, source=agencia), None)]])
    assert n.news_events(db=db, limit=10, offset=0, lane=None, ticker=None, tickers=None) == []


def test_feed_social_entra_sin_cluster(monkeypatch):
    _aplanar_portada(monkeypatch)
    db = DbFalsa([[(evento(7, metadata={"news_lane": "social"}), EMPRESA)]])
    result = n.news_events(db=db, limit=10, offset=0, lane=None, ticker=None, tickers=None)
    assert result[0]["id"] == 7
    assert result[0]["coverage_count"] is None


def test_feed_cluster_13f_agrupa(monkeypatch):
    _aplanar_portada(monkeypatch)
    monkeypatch.setattr(n, "is_position_change_headline", lambda h: True)
    monkeypatch.setattr(
        n, "position_change_cluster_title", lambda ticker, source, count: f"{count} cambios"
    )
    db = DbFalsa([[(evento(1), EMPRESA), (evento(2), EMPRESA)]])
    result = n.news_events(db=db, limit=10, offset=0, lane=None, ticker=None, tickers=None)
    assert len(result) == 1
    assert result[0]["title"] == "2 cambios"
    assert result[0]["cluster_count"] == 2
    assert result[0]["headline_from_source"] is False


def test_feed_historia_absorbida_no_se_repite(monkeypatch):
    _aplanar_portada(monkeypatch)
    absorbidos = []
    monkeypatch.setattr(n, "absorb", lambda group, event: absorbidos.append(event.id))

    class IndiceConMatch:
        def __init__(self):
            self.groups = []
            self.llamadas = 0

        def find(self, event, company, sig):
            self.llamadas += 1
            return self.groups[0] if self.llamadas > 1 else None

        def add(self, group):
            self.groups.append(group)
            return len(self.groups) - 1

    monkeypatch.setattr(n, "StoryClusterIndex", IndiceConMatch)
    db = DbFalsa([[(evento(1), EMPRESA), (evento(2), EMPRESA)]])
    result = n.news_events(db=db, limit=10, offset=0, lane=None, ticker=None, tickers=None)
    assert absorbidos == [2]
    assert len(result) == 1


def test_feed_offset_salta_visibles(monkeypatch):
    _aplanar_portada(monkeypatch)
    db = DbFalsa([[(evento(1), EMPRESA), (evento(2), EMPRESA)]])
    result = n.news_events(db=db, limit=1, offset=1, lane=None, ticker="ASTS", tickers=None)
    assert [r["id"] for r in result] == [2]


# --- second order y traducciones ---------------------------------------------------


def test_second_order_inexistente_es_404():
    db = Mock()
    db.get.return_value = None
    with pytest.raises(HTTPException) as exc:
        n.second_order_hypotheses(5, use_llm=False, db=db)
    assert exc.value.status_code == 404


def test_second_order_delega(monkeypatch):
    monkeypatch.setattr(n, "analyze_second_order", lambda db, e, use_llm: {"evento": e.id})
    db = Mock()
    db.get.return_value = evento(8)
    assert n.second_order_hypotheses(8, use_llm=True, db=db) == {"evento": 8}


@pytest.mark.parametrize("funcion,servicio", [
    (n.translate_news_headline, "translate_headline"),
    (n.translate_news_summary, "translate_summary"),
])
def test_traducciones_happy_y_errores(monkeypatch, funcion, servicio):
    async def ok(db, event_id):
        return {"translated": event_id}

    monkeypatch.setattr(n, servicio, ok)
    assert run_async(funcion(5, db=Mock())) == {"translated": 5}

    async def sin_tenant(db, event_id):
        raise PermissionError("no tenant")

    monkeypatch.setattr(n, servicio, sin_tenant)
    with pytest.raises(HTTPException) as exc:
        run_async(funcion(5, db=Mock()))
    assert exc.value.status_code == 403

    async def no_hay(db, event_id):
        raise LookupError("no existe")

    monkeypatch.setattr(n, servicio, no_hay)
    with pytest.raises(HTTPException) as exc:
        run_async(funcion(5, db=Mock()))
    assert exc.value.status_code == 404


def test_feed_limite_llena_rows_a_media_chunk(monkeypatch):
    # Chunk completo (200) con limit=100: rows se llena a media chunk, no hay
    # break y el while sale por su condicion (175->253).
    _aplanar_portada(monkeypatch)
    chunk = [(evento(i), EMPRESA) for i in range(200)]
    db = DbFalsa([chunk])
    result = n.news_events(db=db, limit=100, offset=0, lane=None, ticker="ASTS", tickers=None)
    assert len(result) == 100
