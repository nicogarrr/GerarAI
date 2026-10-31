"""El embedder se carga una vez por proceso y el warmup es fail-open."""
import sys
import types

from app.services import hybrid_retrieval as hr


def _fake(monkeypatch, counter):
    module = types.ModuleType("fastembed")

    class FakeDense:
        def __init__(self, model):
            counter["n"] += 1

        def embed(self, texts, batch_size=None):
            return [[0.1, 0.2] for _ in texts]

    module.TextEmbedding = FakeDense
    monkeypatch.setitem(sys.modules, "fastembed", module)


def test_dense_model_is_loaded_once_per_process(monkeypatch):
    counter = {"n": 0}
    _fake(monkeypatch, counter)
    hr.clear_model_cache()
    hr.embed_dense(["a"])
    hr.embed_dense(["b"])
    hr.embed_dense(["c"])
    assert counter["n"] == 1


def test_warm_models_loads_model_and_is_fail_open(monkeypatch):
    counter = {"n": 0}
    _fake(monkeypatch, counter)
    hr.clear_model_cache()
    assert hr.warm_models() is True
    hr.embed_dense(["x"])
    assert counter["n"] == 1
    monkeypatch.setitem(sys.modules, "fastembed", None)
    hr.clear_model_cache()
    assert hr.warm_models() is False


def test_st_fallback_builds_model_once_under_concurrency(monkeypatch):
    import threading
    import time

    from app.services.rag import RAGIndex

    built = {"n": 0}

    class FakeST:
        def __init__(self, name):
            built["n"] += 1
            time.sleep(0.2)  # ventana para que otro hilo entre a la vez

    module = types.ModuleType("sentence_transformers")
    module.SentenceTransformer = FakeST
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)
    monkeypatch.setattr(RAGIndex, "_st_model", None)

    barrier = threading.Barrier(4)
    results = []

    def worker():
        barrier.wait()
        results.append(RAGIndex()._embedder())

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert built["n"] == 1
    assert len({id(r) for r in results}) == 1


def test_warm_fallback_builds_st_model_once_and_embedder_reuses_it(monkeypatch):
    from app.services.rag import RAGIndex

    built = {"n": 0}

    class FakeST:
        def __init__(self, name):
            built["n"] += 1

    module = types.ModuleType("sentence_transformers")
    module.SentenceTransformer = FakeST
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)
    monkeypatch.setattr(RAGIndex, "_st_model", None)

    first = RAGIndex.warm_fallback()
    second = RAGIndex.warm_fallback()
    via_instance = RAGIndex.__new__(RAGIndex)._embedder()
    assert first is second is via_instance
    assert built["n"] == 1
