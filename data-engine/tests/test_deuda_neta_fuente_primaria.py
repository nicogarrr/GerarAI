"""Deuda neta: la presentación oficial antes que el agregador, un solo ejercicio.

Antes (main): una deuda neta guardada de Yahoo ganaba aunque el filing del emisor trajera deuda total y
caja de un cierre compatible. Eurofins (ERF.PA): cuenta de resultados ESEF 2024 con deuda neta de Yahoo
2025 (3.204,9 M) en vez de la ESEF 2024 (3.610,3 − 613,9 = 2.996,4 M). Ahora se deriva de la oficial y la
del agregador queda en ``excluded_present``. Si la deuda oficial es de otro alcance (menos de la mitad que
la del agregador en el mismo ejercicio: BN, «Borrowings» corporativos), no se cambia y se avisa.
"""
from decimal import Decimal

import pytest

from app.models.entities import FinancialFact
from app.valuation.financial_snapshot import FinancialSnapshot, FinancialSnapshotBuilder


def _f(metric, period, value, source, fid, unit="EUR"):
    return FinancialFact(id=fid, metric=metric, period=period, value=Decimal(str(value)), unit=unit,
                         fiscal_year=int(period[:4]), fiscal_quarter="FY", source_type=source, confidence=Decimal("0.9"))


ANCHOR = _f("revenue", "2024-12-31:FY", 6_951e6, "ESEF", 1)


def _snap(net_debt):
    return FinancialSnapshot(as_of_period=ANCHOR.period, fiscal_year=2024, fiscal_quarter="FY",
                             income_statement=ANCHOR.period, facts={"revenue": ANCHOR, "net_debt": net_debt})


def test_erf_deuda_neta_oficial_del_mismo_ejercicio():
    yahoo_nd = _f("net_debt", "2025-12-31:FY", 3_204.9e6, "YAHOO_FUNDAMENTALS", 10)
    debt = [_f("total_debt", "2025-12-31:FY", 4_432e6, "YAHOO_FUNDAMENTALS", 11),
            _f("total_debt", "2024-12-31:FY", 3_610.3e6, "ESEF", 12)]
    cash = [_f("cash_and_equivalents", "2025-12-31:FY", 791.2e6, "YAHOO_FUNDAMENTALS", 13),
            _f("cash_and_equivalents", "2024-12-31:FY", 613.9e6, "ESEF", 14)]
    snap = _snap(yahoo_nd)
    FinancialSnapshotBuilder._prefer_primary_net_debt(snap, ANCHOR, debt, cash)
    assert snap.value("net_debt") == pytest.approx(2_996.4e6)
    assert snap.balance_sheet == "2024-12-31:FY"
    assert snap.derived["net_debt"] == [12, 14]
    kept = snap.excluded_present[-1]
    assert kept["reason"] == "primary_source_available" and kept["value"] == pytest.approx(3_204.9e6)


def test_alcance_distinto_no_se_cambia():
    yahoo_nd = _f("net_debt", "2025-12-31:FY", 243_370e6, "YAHOO_FUNDAMENTALS", 20, unit="USD")
    anchor = _f("revenue", "2025-12-31:FY", 75_100e6, "SEC", 21, unit="USD")
    debt = [_f("total_debt", "2025-12-31:FY", 259_612e6, "YAHOO_FUNDAMENTALS", 22, unit="USD"),
            _f("total_debt", "2025-12-31:FY", 14_301e6, "SEC", 23, unit="USD")]
    cash = [_f("cash_and_equivalents", "2025-12-31:FY", 16_242e6, "SEC", 24, unit="USD")]
    snap = FinancialSnapshot(as_of_period=anchor.period, fiscal_year=2025, facts={"revenue": anchor, "net_debt": yahoo_nd})
    FinancialSnapshotBuilder._prefer_primary_net_debt(snap, anchor, debt, cash)
    assert snap.value("net_debt") == pytest.approx(243_370e6)
    assert any("different scope" in w for w in snap.warnings)


def test_deuda_neta_oficial_no_se_toca():
    sec_nd = _f("net_debt", "2024-12-31:FY", 100e6, "ESEF", 30)
    snap = _snap(sec_nd)
    FinancialSnapshotBuilder._prefer_primary_net_debt(
        snap, ANCHOR, [_f("total_debt", "2024-12-31:FY", 500e6, "ESEF", 31)],
        [_f("cash_and_equivalents", "2024-12-31:FY", 50e6, "ESEF", 32)])
    assert snap.facts["net_debt"] is sec_nd


def test_sin_partidas_oficiales_se_queda_el_agregador():
    yahoo_nd = _f("net_debt", "2025-12-31:FY", 3_204.9e6, "YAHOO_FUNDAMENTALS", 40)
    snap = _snap(yahoo_nd)
    FinancialSnapshotBuilder._prefer_primary_net_debt(
        snap, ANCHOR, [_f("total_debt", "2025-12-31:FY", 4_432e6, "YAHOO_FUNDAMENTALS", 41)], [])
    assert snap.facts["net_debt"] is yahoo_nd
