"""Huecos de cobertura en knowledge (lote 12).

Medicion previa (mismo metodo, tests que referencian el modulo): knowledge
45,7 %. Se cubren todos los endpoints de la biblioteca con db y servicios
doblados: chat, colecciones (defaults, lista, crear con 409/422), limite de
subida, documentos (lista, busqueda, get, patch ticker, upload, delete,
chunks), extraccion de principios (404, job activo, dispatch y su fallo),
jobs (lista, get), principios (lista, action con merge/decide/409, revision
con 400/422/409) y el validador de espacios.

Refuerzo (deuda del auditor): el alta del job de extraccion asserta los
campos persistidos (objeto capturado en el Mock de db.add, NO una BD
real), la cronologia add -> commit -> send con un spy de orden, los dos
commit y el send al actor con tenant/user; el
fallo de la cola asserta el job marcado "failed" con su error; las
colecciones assertan la llamada al servicio con sus argumentos.

Que NO se prueba aqui: nada de HTTP ni auth; ninguna base de datos real
(las consultas SQL se construyen pero van contra una db doblada: el
filtrado SQL real NO se prueba); KnowledgeLibraryService,
ClaimIntelligenceService, resolve_page_context, los actores dramatiq y el
LLM van doblados (solo delegacion); el upload lee un fichero falso en
memoria, nunca disco; y run_in_threadpool esta doblado: NADA de hilos
reales.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.api.routes import knowledge as k

COLLECTION = SimpleNamespace(
    id=1, name="Cartas", slug="cartas", description="", collection_type="custom", metadata_={}
)


def run_async(coro):
    return asyncio.run(coro)


def _db():
    db = Mock()
    db.info = {"tenant_id": 1, "user_id": 2}
    return db


def _job_ns(**kw):
    base = dict(
        id=5, job_type="knowledge_principle_extraction", entity_type="knowledge_document",
        entity_id=3, status="queued", progress_current=0, progress_total=1, result={},
        error=None, started_at=None, completed_at=None, created_at=None, updated_at=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _threadpool_inline(monkeypatch):
    def fake(fn, *args, **kwargs):
        async def _coro():
            return fn(*args, **kwargs)

        return _coro()

    monkeypatch.setattr(k, "run_in_threadpool", fake)


# --- chat -------------------------------------------------------------------


def test_chat_biblioteca_delega_y_sin_contexto(monkeypatch):
    _threadpool_inline(monkeypatch)
    monkeypatch.setattr(k, "resolve_page_context", lambda db, page: None)
    from app.services import async_bridge, knowledge_chat

    monkeypatch.setattr(async_bridge, "run_from_any_context", lambda x: x)
    monkeypatch.setattr(knowledge_chat, "ask_library", lambda db, **f: {"answer": "ok"})
    payload = k.LibraryQuestion(question="que dice buffett del moat")
    result = run_async(k.chat_library(payload, db=_db()))
    assert result == {"answer": "ok", "context": None}


def test_chat_biblioteca_eco_del_contexto(monkeypatch):
    _threadpool_inline(monkeypatch)
    pagina = SimpleNamespace(echo=lambda: {"ticker": "ASTS"})
    monkeypatch.setattr(k, "resolve_page_context", lambda db, page: pagina)
    from app.services import async_bridge, knowledge_chat

    monkeypatch.setattr(async_bridge, "run_from_any_context", lambda x: x)
    monkeypatch.setattr(knowledge_chat, "ask_library", lambda db, **f: {"answer": "ok"})
    payload = k.LibraryQuestion(question="que dice buffett del moat")
    result = run_async(k.chat_library(payload, db=_db()))
    assert result["context"] == {"ticker": "ASTS"}


# --- colecciones --------------------------------------------------------------


def test_instalar_colecciones_por_defecto(monkeypatch):
    instaladas = Mock(return_value=[COLLECTION])
    monkeypatch.setattr(
        k,
        "KnowledgeLibraryService",
        lambda: SimpleNamespace(ensure_default_collections=instaladas),
    )
    db = _db()
    result = k.install_default_collections(db=db)
    assert result[0]["slug"] == "cartas"
    instaladas.assert_called_once_with(db)


def test_lista_colecciones():
    db = _db()
    db.scalars.return_value.all.return_value = [COLLECTION]
    result = k.list_collections(db=db)
    assert result[0]["name"] == "Cartas"


def test_crear_coleccion(monkeypatch):
    creada = Mock(return_value=COLLECTION)
    monkeypatch.setattr(
        k,
        "KnowledgeLibraryService",
        lambda: SimpleNamespace(create_collection=creada),
    )
    payload = k.CollectionCreate(
        name="Cartas", description="d", collection_type="custom",
    )
    db = _db()
    assert k.create_collection(payload, db=db)["slug"] == "cartas"
    creada.assert_called_once_with(
        db, name="Cartas", description="d", collection_type="custom",
    )


def test_crear_coleccion_duplicada_es_409(monkeypatch):
    def existe(db, **kw):
        raise k.KnowledgeCollectionExistsError("ya existe")

    monkeypatch.setattr(
        k, "KnowledgeLibraryService", lambda: SimpleNamespace(create_collection=existe)
    )
    with pytest.raises(HTTPException) as exc:
        k.create_collection(k.CollectionCreate(name="Cartas"), db=_db())
    assert exc.value.status_code == 409


def test_crear_coleccion_sin_slug_es_422(monkeypatch):
    def sin_slug(db, **kw):
        raise ValueError("no slug")

    monkeypatch.setattr(
        k, "KnowledgeLibraryService", lambda: SimpleNamespace(create_collection=sin_slug)
    )
    with pytest.raises(HTTPException) as exc:
        k.create_collection(k.CollectionCreate(name="!!"), db=_db())
    assert exc.value.status_code == 422


def test_ingesta_async_encola_corpus(monkeypatch):
    from app.workers import dramatiq_app

    enviado = {}

    class ActorFalso:
        def send(self, **kwargs):
            enviado.update(kwargs)
            return SimpleNamespace(message_id="m1")

    monkeypatch.setattr(dramatiq_app, "ingest_letters_corpus", ActorFalso())
    result = k.ingest_corpus_async(db=_db())
    assert enviado == {"tenant_id": 1, "user_id": 2}
    assert result["broker_message_id"] == "m1"


# --- subida -------------------------------------------------------------------


class _UploadFalso:
    def __init__(self, chunks, filename="carta.pdf", content_type="application/pdf"):
        self._chunks = list(chunks)
        self.filename = filename
        self.content_type = content_type

    async def read(self, n=-1):
        return self._chunks.pop(0) if self._chunks else b""


def test_lectura_subida_pequena():
    file = _UploadFalso([b"hola"])
    assert run_async(k._read_upload_limited(file)) == b"hola"


def test_lectura_subida_que_pasa_del_limite(monkeypatch):
    monkeypatch.setattr(k, "MAX_DOCUMENT_BYTES", 3)
    file = _UploadFalso([b"ab", b"cd"])
    with pytest.raises(ValueError, match="15MB"):
        run_async(k._read_upload_limited(file))


def test_upload_tipo_no_soportado_es_400():
    payload = dict(
        title="Carta 2024", document_type="video", collection_id=None, author=None,
        source_url=None, publication_date=None, language="es", ticker=None,
        file=_UploadFalso([b"x"]), db=_db(),
    )
    with pytest.raises(HTTPException) as exc:
        run_async(k.upload_document(**payload))
    assert exc.value.status_code == 400


def test_upload_feliz_pasa_todo_al_servicio(monkeypatch):
    _threadpool_inline(monkeypatch)
    visto = {}
    monkeypatch.setattr(
        k,
        "KnowledgeLibraryService",
        lambda: SimpleNamespace(ingest_bytes=lambda db, **kw: visto.update(kw) or {"id": 1}),
    )
    monkeypatch.setattr(k, "normalize_knowledge_ticker", lambda t: "ASTS")
    result = run_async(k.upload_document(
        title="Carta 2024", document_type="fund_letter", collection_id=1, author="Numantia",
        source_url=None, publication_date=None, language="es", ticker="asts",
        file=_UploadFalso([b"pdf"]), db=_db(),
    ))
    assert result == {"id": 1}
    assert visto["ticker"] == "ASTS"
    assert visto["language"] == "es"
    assert visto["content"] == b"pdf"


def test_upload_rechazo_del_servicio_es_400_con_ref(monkeypatch):
    _threadpool_inline(monkeypatch)

    def rechaza(db, **kw):
        raise ValueError("pdf ilegible")

    monkeypatch.setattr(
        k, "KnowledgeLibraryService", lambda: SimpleNamespace(ingest_bytes=rechaza)
    )
    monkeypatch.setattr(k, "normalize_knowledge_ticker", lambda t: None)
    with pytest.raises(HTTPException) as exc:
        run_async(k.upload_document(
            title="Carta 2024", document_type="fund_letter", collection_id=None, author=None,
            source_url=None, publication_date=None, language="es", ticker=None,
            file=_UploadFalso([b"x"]), db=_db(),
        ))
    assert exc.value.status_code == 400
    assert "ref" in exc.value.detail


def test_upload_fallo_interno_es_502(monkeypatch):
    _threadpool_inline(monkeypatch)

    def roto(db, **kw):
        raise ConnectionError("llm caido")

    monkeypatch.setattr(
        k, "KnowledgeLibraryService", lambda: SimpleNamespace(ingest_bytes=roto)
    )
    monkeypatch.setattr(k, "normalize_knowledge_ticker", lambda t: None)
    with pytest.raises(HTTPException) as exc:
        run_async(k.upload_document(
            title="Carta 2024", document_type="fund_letter", collection_id=None, author=None,
            source_url=None, publication_date=None, language="es", ticker=None,
            file=_UploadFalso([b"x"]), db=_db(),
        ))
    assert exc.value.status_code == 502


# --- documentos ----------------------------------------------------------------


def test_lista_documentos_delega(monkeypatch):
    monkeypatch.setattr(
        k.KnowledgeLibraryService, "list_documents", staticmethod(lambda db, **kw: [{"id": 1}])
    )
    result = k.list_documents(
        collection_id=1, limit=10, offset=0, document_type=None, status=None,
        ticker=None, db=_db(),
    )
    assert result == [{"id": 1}]


def test_buscar_documentos_delega(monkeypatch):
    monkeypatch.setattr(
        k.KnowledgeLibraryService, "search_documents",
        staticmethod(lambda db, q, limit, offset: {"items": [], "q": q}),
    )
    result = k.search_documents(q="moat", limit=10, offset=0, db=_db())
    assert result["q"] == "moat"


def test_get_documento_inexistente_es_404(monkeypatch):
    monkeypatch.setattr(
        k.KnowledgeLibraryService, "get_document", staticmethod(lambda db, i: None)
    )
    with pytest.raises(HTTPException) as exc:
        k.get_document(5, db=_db())
    assert exc.value.status_code == 404


def test_patch_ticker_documento_inexistente_es_404():
    db = _db()
    db.get.return_value = None
    with pytest.raises(HTTPException) as exc:
        k.update_document_ticker(5, k.DocumentTickerUpdate(ticker="ASTS"), db=db)
    assert exc.value.status_code == 404


def test_patch_ticker_feliz(monkeypatch):
    monkeypatch.setattr(
        k.KnowledgeLibraryService, "set_document_ticker",
        staticmethod(lambda db, doc, t: {"id": doc.id, "ticker": t}),
    )
    db = _db()
    db.get.return_value = SimpleNamespace(id=5)
    result = k.update_document_ticker(5, k.DocumentTickerUpdate(ticker="ASTS"), db=db)
    assert result == {"id": 5, "ticker": "ASTS"}


def test_patch_ticker_invalido_es_400(monkeypatch):
    def malo(db, doc, t):
        raise ValueError("ticker desconocido")

    monkeypatch.setattr(k.KnowledgeLibraryService, "set_document_ticker", staticmethod(malo))
    db = _db()
    db.get.return_value = SimpleNamespace(id=5)
    with pytest.raises(HTTPException) as exc:
        k.update_document_ticker(5, k.DocumentTickerUpdate(ticker="NOPE"), db=db)
    assert exc.value.status_code == 400


def test_borrar_documento_inexistente_es_404():
    db = _db()
    db.get.return_value = None
    with pytest.raises(HTTPException) as exc:
        k.delete_document(5, db=db)
    assert exc.value.status_code == 404


def test_borrar_documento_feliz(monkeypatch):
    borrados = []
    monkeypatch.setattr(
        k.KnowledgeLibraryService, "delete_document",
        staticmethod(lambda db, doc: borrados.append(doc.id)),
    )
    db = _db()
    db.get.return_value = SimpleNamespace(id=5)
    result = k.delete_document(5, db=db)
    assert result.status_code == 204
    assert borrados == [5]


def test_borrar_coleccion_inexistente_es_404():
    db = _db()
    db.get.return_value = None
    with pytest.raises(HTTPException) as exc:
        k.delete_collection(5, db=db)
    assert exc.value.status_code == 404


def test_borrar_coleccion_con_documentos_es_409():
    db = _db()
    db.get.return_value = SimpleNamespace(id=5)
    db.scalar.return_value = 3
    with pytest.raises(HTTPException) as exc:
        k.delete_collection(5, db=db)
    assert exc.value.status_code == 409


def test_borrar_coleccion_vacia_feliz(monkeypatch):
    borradas = []
    monkeypatch.setattr(
        k.KnowledgeLibraryService, "delete_collection",
        staticmethod(lambda db, c: borradas.append(c.id)),
    )
    db = _db()
    db.get.return_value = SimpleNamespace(id=5)
    db.scalar.return_value = 0
    result = k.delete_collection(5, db=db)
    assert result.status_code == 204
    assert borradas == [5]


def test_chunks_documento_inexistente_es_404():
    db = _db()
    db.get.return_value = None
    with pytest.raises(HTTPException) as exc:
        k.document_chunks(5, limit=10, offset=0, db=db)
    assert exc.value.status_code == 404


def test_chunks_devuelve_la_lista():
    chunk = SimpleNamespace(
        id=1, knowledge_document_id=5, chunk_index=0, content="texto",
        page_number=1, section_title="s", token_count=10, source_locator=None, metadata_={},
    )
    db = _db()
    db.get.return_value = SimpleNamespace(id=5)
    db.scalars.return_value.all.return_value = [chunk]
    result = k.document_chunks(5, limit=10, offset=0, db=db)
    assert result[0]["content"] == "texto"


# --- extraccion de principios y jobs -------------------------------------------


def test_extract_documento_inexistente_es_404():
    db = _db()
    db.get.return_value = None
    with pytest.raises(HTTPException) as exc:
        k.extract_principles(5, db=db)
    assert exc.value.status_code == 404


def test_extract_con_job_activo_devuelve_el_job():
    db = _db()
    db.get.return_value = SimpleNamespace(id=5)
    db.scalar.return_value = _job_ns(status="running")
    result = k.extract_principles(5, db=db)
    assert result["status"] == "running"
    db.add.assert_not_called()


def test_extract_encola_job_nuevo(monkeypatch):
    from app.workers import dramatiq_app

    enviados = Mock()
    enviados.send.return_value = SimpleNamespace(message_id="m9")
    monkeypatch.setattr(dramatiq_app, "extract_knowledge_principles", enviados)
    db = _db()
    db.get.return_value = SimpleNamespace(id=5)
    db.scalar.return_value = None
    orden = Mock()
    orden.attach_mock(db.add, "add")
    orden.attach_mock(db.commit, "commit")
    orden.attach_mock(enviados.send, "send")
    result = k.extract_principles(5, db=db)
    # Cronologia: el job queda commiteado ANTES de encolar; si el worker lo
    # recoge al instante, el registro ya existe en BD.
    secuencia = [llamada[0] for llamada in orden.mock_calls]
    assert secuencia.index("add") < secuencia.index("commit")
    assert secuencia.index("commit") < secuencia.index("send")
    # El job se persiste ANTES de encolar: estado y campos tal cual quedan.
    job = db.add.call_args.args[0]
    assert isinstance(job, k.ProcessingJob)
    assert job.job_type == "knowledge_principle_extraction"
    assert job.entity_type == "knowledge_document"
    assert job.entity_id == 5
    assert job.status == "queued"
    db.add.assert_called_once_with(job)
    assert db.commit.call_count == 2  # alta del job + broker_message_id
    assert db.refresh.call_count == 2
    enviados.send.assert_called_once()
    assert enviados.send.call_args.args == (job.id,)
    assert enviados.send.call_args.kwargs == {"tenant_id": 1, "user_id": 2}
    assert job.result == {"broker_message_id": "m9"}
    assert result["result"] == {"broker_message_id": "m9"}


def test_extract_sin_cola_marca_fallido_y_503(monkeypatch):
    from app.workers import dramatiq_app

    class ActorRoto:
        def send(self, *a, **kw):
            raise ConnectionError("broker caido")

    monkeypatch.setattr(dramatiq_app, "extract_knowledge_principles", ActorRoto())
    db = _db()
    db.get.return_value = SimpleNamespace(id=5)
    db.scalar.return_value = None
    with pytest.raises(HTTPException) as exc:
        k.extract_principles(5, db=db)
    assert exc.value.status_code == 503
    # El fallo de la cola queda persistido en el job (lo lee GET /jobs/{id}).
    job = db.add.call_args.args[0]
    assert job.status == "failed"
    assert job.error == "Queue dispatch failed: ConnectionError"
    assert db.commit.call_count == 2  # alta + marcado de fallo
    assert exc.value.detail["job_id"] == job.id


def test_lista_jobs_devuelve_mapeo():
    db = _db()
    db.scalars.return_value.all.return_value = [_job_ns()]
    result = k.list_jobs(document_id=None, limit=10, db=db)
    assert result[0]["job_type"] == "knowledge_principle_extraction"


def test_get_job_inexistente_es_404():
    db = _db()
    db.get.return_value = None
    with pytest.raises(HTTPException) as exc:
        k.get_job(5, db=db)
    assert exc.value.status_code == 404


def test_get_job_de_otro_tipo_es_404():
    db = _db()
    db.get.return_value = _job_ns(job_type="otro")
    with pytest.raises(HTTPException) as exc:
        k.get_job(5, db=db)
    assert exc.value.status_code == 404


def test_get_job_feliz():
    db = _db()
    db.get.return_value = _job_ns()
    assert k.get_job(5, db=db)["id"] == 5


# --- principios ------------------------------------------------------------------


def test_lista_principios_con_filtros():
    db = _db()
    db.scalars.return_value.all.return_value = []
    assert k.list_principles(status="proposed", collection_id=1, limit=10, db=db) == []


def _revision_ns():
    return SimpleNamespace(
        id=7, knowledge_document_id=1, knowledge_chunk_id=2, collection_id=1,
        principle="p", principle_fingerprint="f", semantic_duplicate_of_id=None,
        canonical_principle_id=None, version=1, superseded_by_id=None, category="c",
        application_conditions=[], exceptions=[], applies_to_company_ids=None,
        exact_fragment=None, page_number=None, author=None, confidence=None,
        status="proposed", approved_by=None, approved_at=None, metadata_={},
    )


def test_action_principio_inexistente_es_404():
    db = _db()
    db.get.return_value = None
    with pytest.raises(HTTPException) as exc:
        k.action_principle(7, k.PrincipleAction(action="approve"), db=db)
    assert exc.value.status_code == 404


def test_action_merge_sin_canonico_es_409():
    db = _db()
    db.get.side_effect = [_revision_ns(), None]
    with pytest.raises(HTTPException) as exc:
        k.action_principle(
            7, k.PrincipleAction(action="merge", canonical_principle_id=9), db=db
        )
    assert exc.value.status_code == 409


def test_action_merge_feliz(monkeypatch):
    monkeypatch.setattr(
        k,
        "KnowledgeLibraryService",
        lambda: SimpleNamespace(merge_principle=lambda db, p, canonical, actor: p),
    )
    db = _db()
    db.get.side_effect = [_revision_ns(), _revision_ns()]
    result = k.action_principle(
        7, k.PrincipleAction(action="merge", canonical_principle_id=9), db=db
    )
    assert result["id"] == 7


def test_action_decide_feliz(monkeypatch):
    monkeypatch.setattr(
        k,
        "KnowledgeLibraryService",
        lambda: SimpleNamespace(decide_principle=lambda db, p, action, actor: p),
    )
    db = _db()
    db.get.return_value = _revision_ns()
    result = k.action_principle(7, k.PrincipleAction(action="approve"), db=db)
    assert result["status"] == "proposed"


def test_action_conflicto_es_409(monkeypatch):
    def conflicto(db, p, action, actor):
        raise ValueError("ya decidido")

    monkeypatch.setattr(
        k, "KnowledgeLibraryService", lambda: SimpleNamespace(decide_principle=conflicto)
    )
    db = _db()
    db.get.return_value = _revision_ns()
    with pytest.raises(HTTPException) as exc:
        k.action_principle(7, k.PrincipleAction(action="reject"), db=db)
    assert exc.value.status_code == 409


def test_revision_sin_cambios_es_400():
    db = _db()
    db.get.return_value = _revision_ns()
    with pytest.raises(HTTPException) as exc:
        k.revise_principle(7, k.PrincipleRevision(), db=db)
    assert exc.value.status_code == 400


def test_revision_empresas_desconocidas_es_422():
    db = _db()
    db.get.return_value = _revision_ns()
    db.scalars.return_value = iter([1])
    with pytest.raises(HTTPException) as exc:
        k.revise_principle(7, k.PrincipleRevision(applies_to_company_ids=[1, 2, 2]), db=db)
    assert exc.value.status_code == 422
    assert "2" in exc.value.detail


def test_revision_feliz_dedup_empresas(monkeypatch):
    visto = {}
    monkeypatch.setattr(
        k,
        "KnowledgeLibraryService",
        lambda: SimpleNamespace(
            revise_principle=lambda db, p, changes, actor: visto.update(changes) or p
        ),
    )
    db = _db()
    db.get.return_value = _revision_ns()
    db.scalars.return_value = iter([1, 2])
    result = k.revise_principle(7, k.PrincipleRevision(applies_to_company_ids=[1, 2, 2]), db=db)
    assert visto["applies_to_company_ids"] == [1, 2]
    assert result["id"] == 7


def test_revision_conflicto_es_409(monkeypatch):
    def conflicto(db, p, changes, actor):
        raise ValueError("version vieja")

    monkeypatch.setattr(
        k, "KnowledgeLibraryService", lambda: SimpleNamespace(revise_principle=conflicto)
    )
    db = _db()
    db.get.return_value = _revision_ns()
    with pytest.raises(HTTPException) as exc:
        k.revise_principle(7, k.PrincipleRevision(principle="nuevo texto"), db=db)
    assert exc.value.status_code == 409


def test_validador_recorta_antes_de_medir():
    """Los espacios se recortan antes de min_length: '  abc  ' vale 'abc'."""
    assert k.PrincipleRevision(principle="  abc  ").principle == "abc"


# --- metadatos de subida, paginas y ramas finales ----------------------------


def test_metadatos_idioma_no_soportado():
    with pytest.raises(ValueError, match="language"):
        k.validate_upload_metadata(document_type="book", language="fr", source_url=None)


def test_metadatos_url_valida_normaliza():
    _, _, url = k.validate_upload_metadata(
        document_type="book", language="en", source_url="https://example.com/carta"
    )
    assert url.startswith("https://example.com/")


def test_metadatos_url_invalida():
    with pytest.raises(ValueError, match="source_url"):
        k.validate_upload_metadata(document_type="book", language="en", source_url="no-url")


def test_metadatos_url_que_pasa_de_mil():
    larga = "https://example.com/" + "a" * 1010
    with pytest.raises(ValueError, match="source_url"):
        k.validate_upload_metadata(document_type="book", language="en", source_url=larga)


def test_documents_page_agrega_totales(monkeypatch):
    monkeypatch.setattr(
        k.KnowledgeLibraryService, "list_documents",
        staticmethod(lambda db, limit, offset: [{"id": 1}]),
    )
    db = _db()
    db.scalar.return_value = 7
    db.execute.return_value.all.return_value = [(1, 3), (None, 4)]
    result = k.documents_page(limit=10, offset=0, db=db)
    assert result == {"items": [{"id": 1}], "total": 7, "collection_counts": {"1": 3}}


def test_get_documento_feliz(monkeypatch):
    monkeypatch.setattr(
        k.KnowledgeLibraryService, "get_document", staticmethod(lambda db, i: {"id": i})
    )
    assert k.get_document(5, db=_db()) == {"id": 5}


def test_lista_jobs_filtra_por_documento():
    db = _db()
    db.scalars.return_value.all.return_value = []
    assert k.list_jobs(document_id=3, limit=10, db=db) == []


def test_principles_page_sin_filtro():
    db = _db()
    db.scalars.return_value.all.return_value = [_revision_ns()]
    db.scalar.side_effect = [4, 2]
    result = k.principles_page(status=None, limit=10, offset=0, db=db)
    assert result["total"] == 4
    assert result["proposed_total"] == 2
    assert result["items"][0]["id"] == 7


def test_principles_page_con_estado():
    db = _db()
    db.scalars.return_value.all.return_value = []
    db.scalar.side_effect = [0, 0]
    result = k.principles_page(status="approved", limit=10, offset=0, db=db)
    assert result["items"] == []


def test_lista_principios_sin_filtros():
    db = _db()
    db.scalars.return_value.all.return_value = []
    assert k.list_principles(status=None, collection_id=None, limit=10, db=db) == []


def test_lista_principios_solo_estado():
    db = _db()
    db.scalars.return_value.all.return_value = []
    assert k.list_principles(status="proposed", collection_id=None, limit=10, db=db) == []


def test_lista_principios_solo_coleccion():
    db = _db()
    db.scalars.return_value.all.return_value = []
    assert k.list_principles(status=None, collection_id=2, limit=10, db=db) == []


def test_revision_principio_inexistente_es_404():
    db = _db()
    db.get.return_value = None
    with pytest.raises(HTTPException) as exc:
        k.revise_principle(7, k.PrincipleRevision(principle="nuevo texto"), db=db)
    assert exc.value.status_code == 404
