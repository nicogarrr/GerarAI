"""Semgrep «money-none-to-zero» a 0: un importe que falta es N/D con su motivo, nunca un 0 inventado.

Antes (main 9fffa4194, 8-nov-2026): 15 hallazgos de Semgrep; cada test de abajo falla con aquel código.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from app.services import expert_bench as eb
from app.services.expert_team import sotp_rules
from app.services.expert_team import thesis_v2 as T
from app.services.expert_team.sotp_narrative import sotp_markers


def _annual(**metrics):
    return {"annual": {m: {str(y): {"value": v * 1e6} for y, v in vals.items()} for m, vals in metrics.items()}}


# ---------------------------------------------------------------- tesis v2: reparto (kill switch e historial)


def test_reparto_sin_dividendos_ni_recompras_es_nd_no_cero():
    ratio, missing = T.payout_ratio({"net_income": 100.0, "dividends": None, "buybacks": None})
    assert ratio is None and missing == ["dividendos", "recompras"]
    assert T.payout_text(ratio, missing) == "N/D (sin dividendos ni recompras en los filings)"


def test_reparto_con_una_parte_es_cota_inferior_y_lo_dice():
    ratio, missing = T.payout_ratio({"net_income": 100.0, "dividends": 40.0, "buybacks": None})
    assert ratio == pytest.approx(0.4) and missing == ["recompras"]
    assert T.payout_text(ratio, missing).startswith("≥ ") and "sin recompras" in T.payout_text(ratio, missing)
    # Un 0 declarado sí es un dato: no se marca como hueco.
    ratio, missing = T.payout_ratio({"net_income": 100.0, "dividends": 40.0, "buybacks": 0.0})
    assert ratio == pytest.approx(0.4) and missing == []


def test_historial_conserva_el_cero_declarado_y_el_hueco_como_none():
    cites = _annual(revenue={2025: 1000}, net_income={2025: 100}, dividends_paid={2025: -0.0})
    row = T.history_rows(cites, "pb", {})[-1]
    assert row["dividends"] == 0.0  # antes: abs(0 or 0.0) or None → None
    assert row["buybacks"] is None


def test_roic_sin_deuda_es_nd_con_el_motivo():
    cites = _annual(revenue={2025: 1000}, operating_income={2025: 200}, net_income={2025: 150})
    points = {"total_equity": {2025: 800.0}, "total_debt": {}, "cash_and_equivalents": {2025: 100.0}}
    row = T.history_rows(cites, "pe", points)[-1]
    # antes: capital invertido = 800 + 0 − 100 y ROIC 21 % con una deuda 0 inventada
    assert row["roic"] is None and row["roic_missing"] == ["deuda"]
    assert T.roic_text(row) == "N/D (falta deuda)"


# ---------------------------------------------------------------- benchmark de expertos


def test_deuda_neta_reconstruida_necesita_deuda_y_caja():
    val = {"starting_point": {"price": 10.0, "shares_diluted": 1.0, "net_debt": 50.0},
           "citations": {"total_debt": {"value": 80e6}}}
    out = eb.source_check(val)["net_debt"]
    # antes: 80 − 0 = 80 «reconstruida» con una caja 0 inventada
    assert out["rebuilt_from_citations"] is None and out["rebuilt_missing"] == ["caja"]
    assert out["abs_diff_m"] is None


def test_coste_desconocido_no_cuenta_como_cero():
    out = eb.cost_by_role([{"role": "analista", "cost_eur": 0.02}, {"role": "analista", "cost_eur": None}])
    assert out["analista"]["calls"] == 2
    assert out["analista"]["cost_eur"] == pytest.approx(0.02)
    assert out["analista"]["cost_unknown_calls"] == 1


# ---------------------------------------------------------------- SOTP


def test_acciones_nuevas_sin_acciones_de_hoy_es_nd():
    m = sotp_markers({"currency": "USD", "shares_current": None}, {"shares_diluted": 120.0})
    # antes: 120 − 0 = 120 M de acciones «nuevas»
    assert m["dilution.new_shares"] == sotp_markers({"currency": "USD", "shares_current": None},
                                                    {"shares_diluted": None})["dilution.new_shares"]
    assert "120" not in m["dilution.new_shares"]


def test_quema_sin_caja_no_inventa_ampliacion():
    anchors = {"burns_cash": True, "annual_burn_millions": 50.0, "cash_millions": None,
               "short_term_investments_millions": None, "price": 5.0, "ticker": "X", "sbc_millions": None}
    items = [d for d in sotp_rules.code_dilution(anchors, 5) if "quema" in d["label"]]
    # antes: liquidez 0 → ampliación de toda la quema (50 × años ÷ precio)
    assert items == []
    assert "caja" in (sotp_rules.burn_gap_unknown(anchors) or "")
    anchors["cash_millions"] = 1000.0
    assert sotp_rules.burn_gap_unknown(anchors) is None


def test_ficha_mayoria_caja_ignora_filas_sin_cifra():
    from app.services.user_sotp_service import _mostly_cash

    assert _mostly_cash({"value_per_share": 10.0, "rows": [{"name": "Caja menos deuda", "value_per_share": None}]}) is None
    out = _mostly_cash({"value_per_share": 10.0, "rows": [{"name": "Caja menos deuda", "value_per_share": 8.0}]})
    assert out and out["share"] == pytest.approx(0.8)


# ---------------------------------------------------------------- TIR point-in-time


def test_arnes_pit_sin_caja_descarta_la_fecha_con_motivo():
    from datetime import date

    from app.valuation import irr_pit_backtest as bt

    rows = {"Revenues": 1000e6, "NetIncomeLoss": 200e6, "WeightedAverageNumberOfDilutedSharesOutstanding": 100e6}
    payload = {"facts": {"us-gaap": {
        k: {"units": {("shares" if "Shares" in k else "USD"): [
            {"start": "2015-01-01", "end": "2015-12-31", "val": v, "filed": "2016-02-20", "form": "10-K"}]}}
        for k, v in rows.items()}}}
    t = date(2016, 6, 30)
    with pytest.raises(ValueError, match="caja sin dato"):
        bt.build_inputs(bt.as_of(bt.facts_from_companyfacts(payload), t), t=t, price=30.0, splits=[], financial=True)


# ---------------------------------------------------------------- Companies House


def test_pistas_de_filial_sin_cache_lo_registran_y_lo_dicen(caplog, monkeypatch):
    import app.services.company_alias_sources as cas
    from app.services.companies_house_evidence import subsidiary_hints

    def boom(_db):
        raise RuntimeError("tabla de alias no disponible")

    monkeypatch.setattr(cas, "load_cached", boom)
    notes: list[str] = []
    with caplog.at_level(logging.WARNING):
        out = subsidiary_hints(None, SimpleNamespace(ticker="CGEO.L", id=1), None, notes=notes)
    assert out == []
    assert notes and "tabla de alias no disponible" in notes[0]
    assert any("CGEO.L" in r.getMessage() for r in caplog.records)
