"""Primer uso de dependencias diferidas, aislado de imports de otros tests."""
from tests.test_pdf_lazy_import import _run


def test_lazy_globals_and_configured_reranker(monkeypatch):
    from types import SimpleNamespace

    import pytest

    from app.services import rag
    from app.services.knowledge_rag import runtime

    monkeypatch.delitem(vars(rag), "QdrantClient", raising=False)
    rag.clear_qdrant_pool()
    client = rag.get_qdrant_client('http://127.0.0.1:6333')
    assert rag.get_qdrant_client('http://127.0.0.1:6333') is client
    client.close()
    rag.clear_qdrant_pool()
    with pytest.raises(AttributeError):
        rag.__getattr__('unknown_attribute')
    runtime._reranker.cache_clear()
    processors = runtime.make_postprocessors(SimpleNamespace(knowledge_rag_reranker_model='local-test'), 3)
    assert len(processors) == 1
    assert processors[0].top_n == 3
    assert processors[0].reranker.model == 'local-test'
    assert processors[0].reranker._encoder is None
    runtime._reranker.cache_clear()



def test_qdrant_first_call_without_attribute_access():
    result = _run('''
import sys
from app.services import rag
assert 'qdrant_client' not in sys.modules
assert 'QdrantClient' not in vars(rag)
# Constructor real con destino loopback, sin ejecutar consultas.
client = rag.get_qdrant_client('http://127.0.0.1:6333')
assert rag.get_qdrant_client('http://127.0.0.1:6333') is client
assert 'QdrantClient' in vars(rag)
client.close()
rag.clear_qdrant_pool()
try:
    rag.__getattr__('unknown_attribute')
except AttributeError:
    pass
else:
    raise AssertionError('El atributo desconocido debe fallar')
''')
    assert result.returncode == 0, result.stderr


def test_retrieval_first_call_and_disabled_reranker():
    result = _run('''
import sys
from types import SimpleNamespace
from app.services.knowledge_rag.retrieval import search_knowledge
from app.services.knowledge_rag.runtime import make_postprocessors
assert 'llama_index' not in sys.modules
assert make_postprocessors(SimpleNamespace(knowledge_rag_reranker_model=''), 2) == []
assert 'llama_index' not in sys.modules
class Store:
    def search_dense(self, *args): return []
    def search_sparse(self, *args): return []
class Embedder:
    def dense_query(self, query): return [1.0]
    def sparse_query(self, query): return None
result = search_knowledge('consulta', tenant_id=1, store=Store(), embedder=Embedder(), resolve_parents=lambda ids: {})
assert result.citations == []
assert 'llama_index' in sys.modules
''')
    assert result.returncode == 0, result.stderr
