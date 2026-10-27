"""#22: si un padre no se resuelve, la cita se rellena con el siguiente candidato."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.services.knowledge_rag.retrieval import search_knowledge

from .knowledge_rag_helpers import FakeEmbedder


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class _Hit:
    id: str
    score: float
    payload: dict


def _payload(i: int) -> dict:
    parent_text = f"Padre {i}. El margen de seguridad numero {i} protege al inversor."
    quote = f"El margen de seguridad numero {i}"
    start = parent_text.index(quote)
    return {
        "text": quote,
        "parent_id": f"p{i}",
        "parent_text": parent_text,
        "char_start": start,
        "char_end": start + len(quote),
        "text_sha256": _sha(quote),
        "source_id": f"s{i}",
        "source_sha256": _sha(f"s{i}"),
        "title": f"Carta {i}",
        "source_uri": f"file:///carta{i}.pdf",
        "language": "es",
        "doc_type": "letter",
        "corpus": "cartas",
        "rights": "private",
    }


class _Store:
    def __init__(self, n: int) -> None:
        self.hits = [_Hit(f"c{i}", 1.0 - i / 100, _payload(i)) for i in range(n)]

    def search_dense(self, _vec, _flt, limit):
        return self.hits[:limit]

    def search_sparse(self, _vec, _flt, limit):
        return self.hits[:limit]


def _resolver(missing_parents: set[str], calls: list[list[str]]):
    def resolve(ids):
        calls.append(list(ids))
        out = {}
        for pid in ids:
            if pid in missing_parents:
                continue
            i = int(pid[1:])
            text = _payload(i)["parent_text"]
            out[pid] = (text, _sha(text))
        return out

    return resolve


def _search(store, resolver, top_k=3):
    return search_knowledge(
        "margen de seguridad",
        tenant_id=1,
        store=store,
        embedder=FakeEmbedder(),
        resolve_parents=resolver,
        top_k=top_k,
    )


def test_padre_no_resuelto_se_rellena_con_el_siguiente_candidato():
    calls: list[list[str]] = []
    result = _search(_Store(6), _resolver({"p1"}, calls))

    assert [c.parent_id for c in result.citations] == ["p0", "p2", "p3"]
    assert [c.number for c in result.citations] == [1, 2, 3]
    assert result.dropped_unverified == 1
    assert calls == [["p0", "p1", "p2"], ["p3"]]


def test_cita_que_no_verifica_tambien_se_rellena():
    store = _Store(5)
    store.hits[0].payload["text_sha256"] = "0" * 64  # hash roto
    calls: list[list[str]] = []
    result = _search(store, _resolver(set(), calls), top_k=2)

    assert [c.parent_id for c in result.citations] == ["p1", "p2"]
    assert result.dropped_unverified == 1


def test_caso_normal_una_sola_resolucion_de_padres():
    calls: list[list[str]] = []
    result = _search(_Store(6), _resolver(set(), calls))

    assert [c.parent_id for c in result.citations] == ["p0", "p1", "p2"]
    assert calls == [["p0", "p1", "p2"]]
    assert result.dropped_unverified == 0


def test_sin_candidatos_suficientes_devuelve_los_que_hay():
    calls: list[list[str]] = []
    result = _search(_Store(3), _resolver({"p0", "p2"}, calls))

    assert [c.parent_id for c in result.citations] == ["p1"]
    assert result.dropped_unverified == 2
