"""Analistas: cada texto en castellano del servicio viaja con un codigo estable.

La app en ingles pintaba tal cual las notas y la fuente del precio de
referencia («fuente de mercado, precio al obtener los datos», «Solo hay
consenso agregado...»). El front traduce por codigo; los campos de texto se
mantienen por compatibilidad.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from app.services import analyst_targets_service as svc


def _rec(firm: str, when: datetime, target: float) -> dict:
    return {"firm": firm, "date": when, "rating": "Buy", "action": "Maintains", "price_target": target, "prior_target": None}


def _get(monkeypatch, payload):
    monkeypatch.setattr(svc, "_fetch_sync", payload if callable(payload) else (lambda symbol: payload))
    return asyncio.run(svc.AnalystTargetsService().get("TEST"))


def test_precio_de_referencia_lleva_codigo_estable(monkeypatch) -> None:
    result = _get(monkeypatch, {"records": [], "consensus": {"current": 50.0, "mean": 60.0}})
    assert result.reference_price == 50.0
    assert result.reference_price_source_code == "market_at_fetch"
    assert result.reference_price_source == "fuente de mercado, precio al obtener los datos"


def test_sin_precio_de_referencia_no_hay_codigo(monkeypatch) -> None:
    result = _get(monkeypatch, {"records": [], "consensus": {}})
    assert result.reference_price is None and result.reference_price_source_code is None


def test_cada_nota_lleva_su_codigo(monkeypatch) -> None:
    only = _get(monkeypatch, {"records": [], "consensus": {"current": 5.5, "mean": 9.0}})
    assert only.note_code == "consensus_only" and only.note

    empty = _get(monkeypatch, {"records": [], "consensus": {}})
    assert empty.note_code == "no_targets" and empty.note

    def boom(symbol):
        raise RuntimeError("yahoo caido")

    failed = _get(monkeypatch, boom)
    assert failed.status == "unavailable" and failed.note_code == "fetch_failed" and failed.note

    etf = _get(monkeypatch, {"records": [], "consensus": {}, "quote_type": "etf"})
    assert etf.status == "empty" and etf.note_code == "not_equity" and etf.instrument_type == "ETF"
    assert etf.note and "ETF" in etf.note


def test_con_filas_no_hay_nota_ni_codigo(monkeypatch) -> None:
    when = datetime.now() - timedelta(days=3)
    result = _get(monkeypatch, {"records": [_rec("TD Cowen", when, 90.0)], "consensus": {"current": 50.0}})
    assert result.rows
    assert result.note is None and result.note_code is None
