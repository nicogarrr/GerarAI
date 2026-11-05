"""Opt-out operativo de ingesta de documentos (document_ingest_exclusions).

5-nov-2026: Nico pidio quitar KRKNF de su cuenta; el bloqueo "10:KRKNF" frena
su reencolado en tenant 10 sin tocar a tenant 2 (IBKR), que la conserva.
"""
from __future__ import annotations

from app.workers import dramatiq_app
from app.workers.dramatiq_app import _document_ingest_excluded


def _set(monkeypatch, raw: str):
    monkeypatch.setattr(
        dramatiq_app.settings, "document_ingest_exclusions", raw, raising=False
    )


def test_sin_exclusiones_nada_bloqueado(monkeypatch):
    _set(monkeypatch, "")
    assert not _document_ingest_excluded(10, "KRKNF")


def test_bloqueo_scoped_por_tenant(monkeypatch):
    _set(monkeypatch, "10:KRKNF")
    assert _document_ingest_excluded(10, "KRKNF")
    assert not _document_ingest_excluded(2, "KRKNF"), "tenant 2 (IBKR) se preserva"
    assert not _document_ingest_excluded(10, "ASTS")


def test_bloqueo_global_sin_tenant(monkeypatch):
    _set(monkeypatch, "KRKNF")
    assert _document_ingest_excluded(10, "KRKNF")
    assert _document_ingest_excluded(2, "KRKNF")


def test_formato_roto_no_rompe_el_encolado(monkeypatch):
    _set(monkeypatch, "xx:KRKNF, ,10:")
    assert not _document_ingest_excluded(10, "KRKNF")
    _set(monkeypatch, " 10:krknf ")
    assert _document_ingest_excluded(10, "KRKNF"), "case y espacios normalizados"


def test_varias_entradas(monkeypatch):
    _set(monkeypatch, "10:KRKNF,2:PNG.V")
    assert _document_ingest_excluded(10, "KRKNF")
    assert _document_ingest_excluded(2, "PNG.V")
    assert not _document_ingest_excluded(2, "KRKNF")
