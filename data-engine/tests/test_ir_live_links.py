"""Enlace oficial al directo: fecha exacta y forma estricta, o no hay enlace."""

from __future__ import annotations

import pytest

from app.services import ir_live_links as ill

META_WEBCAST = "https://events.q4inc.com/attendee/132342320"
ASTS_WEBCAST = "https://event.choruscall.com/mediaframe/webcast.html?webcastid=QKToBNQI"


def test_enlace_verificado_con_fecha_exacta():
    assert ill.live_link_for("META", "2026-10-21") == {
        "kind": "webcast",
        "url": META_WEBCAST,
        "source": "https://investor.atmeta.com/investor-events/event-details/2026/Q3-2026-Earnings-Call/default.aspx",
    }
    assert ill.live_link_for("ASTS", "2026-11-09")["url"] == ASTS_WEBCAST


def test_ticker_minusculas_y_otra_fecha_o_ticker_sin_enlace():
    assert ill.live_link_for("meta", "2026-10-21")["url"] == META_WEBCAST
    assert ill.live_link_for("META", "2026-10-22") is None
    assert ill.live_link_for("ZZZZ", "2026-10-21") is None


def test_json_ausente_es_sin_enlace(tmp_path, monkeypatch):
    monkeypatch.setattr(ill, "_DATA_FILE", tmp_path / "no_existe.json")
    ill._links.cache_clear()
    try:
        assert ill.live_link_for("META", "2026-10-21") is None
    finally:
        ill._links.cache_clear()


def test_json_invalido_es_sin_enlace(tmp_path, monkeypatch):
    bad = tmp_path / "ir_live_links.json"
    bad.write_text("{no es json", encoding="utf-8")
    monkeypatch.setattr(ill, "_DATA_FILE", bad)
    ill._links.cache_clear()
    try:
        assert ill.live_link_for("META", "2026-10-21") is None
    finally:
        ill._links.cache_clear()


@pytest.mark.parametrize("entry", [
    {"kind": "webcast", "url": "http://inseguro.example.com", "source": "https://ok.example.com"},
    {"kind": "grabacion", "url": "https://ok.example.com", "source": "https://ok.example.com"},
    {"kind": "webcast", "url": "https://ok.example.com"},
    "no-es-un-dict",
])
def test_forma_inesperada_nunca_enlaza(monkeypatch, entry):
    monkeypatch.setattr(ill, "_links", lambda: {"FAKE": {"2026-01-01": entry}})
    assert ill.live_link_for("FAKE", "2026-01-01") is None
