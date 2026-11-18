"""Whole-module branch contracts for bootstrap error handling and RAG first use.

All downstream model constructors are doubles: no model downloads or external
calls. The functions under test remain the real production implementations.
"""
import asyncio
import json
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import DataError
from starlette.requests import Request

import main
from app.services import hybrid_retrieval as hr
from app.services.rag import RAGIndex


def request():
    return Request({'type': 'http', 'method': 'GET', 'path': '/test', 'headers': []})


def test_finite_json_nested_containers_keep_json_strict_and_normal_values():
    value = {'bad': [float('nan'), float('inf'), -float('inf')],
             'normal': (1.25, None, True, 'texto')}
    result = main._finite_json(value)
    assert result == {'bad': ['nan', 'inf', '-inf'], 'normal': [1.25, None, True, 'texto']}
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize('exc,status', [(DataError('SELECT', {}, ValueError('range')), 422),
                                       (OverflowError('arithmetic'), 500)])
def test_database_error_handler_classifies_real_exception(exc, status, monkeypatch):
    from app.core import error_reporting
    monkeypatch.setattr(error_reporting, 'report_exception', Mock())
    response = asyncio.run(main.db_value_out_of_range_handler(request(), exc))
    assert response.status_code == status
    detail = json.loads(response.body)['detail']
    assert detail
    assert 'SELECT' not in detail
    if status == 422:
        assert detail == 'Valor fuera de rango para este campo.'
    else:
        assert 'ref:' in detail


def test_validation_handler_serializes_nonfinite_and_invalid_utf8():
    exc = RequestValidationError([{'loc': ('body', 'number'), 'type': 'finite_number',
        'msg': 'invalid', 'input': float('inf')}, {'loc': ('body',), 'type': 'bytes',
        'msg': 'invalid', 'input': b'\xff'}])
    response = asyncio.run(main.request_validation_error_handler(request(), exc))
    assert response.status_code == 422
    body = json.loads(response.body)
    assert body['detail'][0]['input'] == 'inf'
    assert body['detail'][1]['input'] == '\ufffd'


def test_security_middleware_passes_non_http_without_headers():
    called = []
    async def downstream(scope, receive, send):
        called.append(scope)
    scope = {'type': 'websocket'}
    asyncio.run(main.SecurityHeadersMiddleware(downstream)(scope, None, None))
    assert called == [scope]


@pytest.fixture
def fallback(monkeypatch):
    monkeypatch.setattr(RAGIndex, '_st_model', None)
    monkeypatch.setattr(RAGIndex, '_st_error', None)
    module = ModuleType('sentence_transformers')
    monkeypatch.setitem(sys.modules, 'sentence_transformers', module)
    return module


def test_warm_fallback_success_is_cached(fallback):
    model = object()
    constructor = Mock(return_value=model)
    fallback.SentenceTransformer = constructor
    assert RAGIndex.warm_fallback() is model
    assert RAGIndex.warm_fallback() is model
    constructor.assert_called_once_with('all-MiniLM-L6-v2')


def test_warm_fallback_failure_caches_same_exception(fallback):
    cause = ValueError('unavailable')
    constructor = Mock(side_effect=cause)
    fallback.SentenceTransformer = constructor
    with pytest.raises(RuntimeError, match='no disponible') as first:
        RAGIndex.warm_fallback()
    with pytest.raises(RuntimeError) as second:
        RAGIndex.warm_fallback()
    assert first.value is second.value
    assert first.value.__cause__ is cause
    constructor.assert_called_once()


def test_warm_fallback_rechecks_after_lock_acquired(fallback, monkeypatch):
    model = object()
    class PopulatedLock:
        def __enter__(self):
            RAGIndex._st_model = model
        def __exit__(self, *exc):
            pass
    monkeypatch.setattr(RAGIndex, '_st_lock', PopulatedLock())
    constructor = Mock(side_effect=AssertionError('model already loaded by other thread'))
    fallback.SentenceTransformer = constructor
    assert RAGIndex.warm_fallback() is model
    constructor.assert_not_called()


@pytest.mark.parametrize('existing,has_sparse', [(False, False), (True, False), (True, True)])
def test_ensure_hybrid_collection_configures_sparse_only_when_missing(monkeypatch, existing, has_sparse):
    from qdrant_client.models import SparseVectorParams

    from tests.test_rag_hybrid import FakeQdrant

    index = RAGIndex()
    index.settings = SimpleNamespace(rag_hybrid_enabled=True, rag_sparse_vector_name='bm25')
    client = FakeQdrant()
    monkeypatch.setattr(client, 'get_collections', lambda: SimpleNamespace(collections=[
        SimpleNamespace(name=index._collection())] if existing else []))
    monkeypatch.setattr(index, '_ensure_payload_indexes', Mock())
    check = Mock(return_value=has_sparse)
    ensure = Mock()
    monkeypatch.setattr(hr, 'collection_has_sparse', check)
    monkeypatch.setattr(hr, 'ensure_sparse_vector', ensure)
    index._ensure_collection(client)
    if not existing:
        assert isinstance(client.created[0][1]['sparse_vectors_config']['bm25'], SparseVectorParams)
        check.assert_not_called()
        ensure.assert_not_called()
    else:
        assert client.created == []
        check.assert_called_once_with(client, index._collection(), 'bm25')
        if has_sparse:
            ensure.assert_not_called()
        else:
            ensure.assert_called_once_with(client, index._collection(), 'bm25')
    index._ensure_payload_indexes.assert_called_once_with(client, index._collection())
