"""Los fallbacks opcionales de valoracion siguen devolviendo el mismo valor,
pero ya no tragan la excepcion sin rastro (avisar, no ocultar)."""

from __future__ import annotations

import logging
from types import SimpleNamespace

from app.services import declared_input_service as dis
from app.valuation import consensus_context
from app.valuation.engines import base, pre_revenue, standard_dcf


def _warnings(caplog, needle: str) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING and needle in r.getMessage()]


def test_consenso_que_falla_devuelve_none_y_avisa(caplog):
    def boom(_ticker):
        raise RuntimeError("fuente caida")

    with caplog.at_level(logging.WARNING):
        assert consensus_context.load_consensus(None, {"ticker": "ACME"}, loader=boom) is None
    assert _warnings(caplog, "ACME")


def test_input_declarado_ilegible_en_tasas_devuelve_none_y_avisa(caplog, monkeypatch):
    class Broken:
        def current(self, *args, **kwargs):
            raise RuntimeError("bd caida")

    monkeypatch.setattr(dis, "DeclaredInputService", Broken)
    db = SimpleNamespace(info={"tenant_id": 1})
    with caplog.at_level(logging.WARNING):
        assert base._declared_rate(db, 7, "wacc") is None
    assert _warnings(caplog, "company_id=7")


def test_input_declarado_ilegible_en_pre_revenue_devuelve_none_y_avisa(caplog, monkeypatch):
    class Broken:
        def current(self, *args, **kwargs):
            raise RuntimeError("bd caida")

    monkeypatch.setattr(pre_revenue, "DeclaredInputService", Broken)
    engine = pre_revenue.PreRevenueScenarioEngine()
    context = SimpleNamespace(
        db=SimpleNamespace(info={"tenant_id": 1}), company=SimpleNamespace(id=9), as_of=None
    )
    with caplog.at_level(logging.WARNING):
        assert engine._declared_margin_target(context) is None
    assert _warnings(caplog, "company_id=9")


def test_historial_fy_ilegible_devuelve_none_y_avisa(caplog, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("bd caida")

    monkeypatch.setattr(standard_dcf, "fy_history", boom)
    context = SimpleNamespace(db=object(), as_of=None)
    with caplog.at_level(logging.WARNING):
        assert standard_dcf._own_history(context, 5) is None
    assert _warnings(caplog, "company_id=5")
