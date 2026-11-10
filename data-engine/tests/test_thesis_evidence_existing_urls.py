"""_existing_document_urls: URLs ya dadas de alta, en una sola consulta y sin NULL."""
from __future__ import annotations

from app.services import thesis_evidence_service as svc


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _DB:
    def __init__(self, rows):
        self.rows = rows
        self.calls = 0
        self.info = {}

    def scalars(self, _stmt):
        self.calls += 1
        return _Scalars(self.rows)


def test_sin_urls_no_consulta():
    db = _DB(["x"])
    assert svc._existing_document_urls(db, []) == set()
    assert db.calls == 0


def test_una_consulta_y_descarta_null_y_repetidos(monkeypatch):
    monkeypatch.setattr(svc, "tenant_filters", lambda db, model: [])
    db = _DB(["https://a", None, "https://a", "https://b"])
    got = svc._existing_document_urls(db, ["https://a", "https://b", "https://c"])
    assert got == {"https://a", "https://b"} and db.calls == 1
