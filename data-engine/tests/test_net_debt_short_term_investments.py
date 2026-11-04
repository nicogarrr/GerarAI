"""Deuda neta: las inversiones financieras a corto plazo también restan.

PLTR (31/12/2025) presenta 1.424 M de caja y 5.753 M en valores negociables
(MarketableSecuritiesCurrent). FMP (netDebt) y Yahoo («Net Debt») dan la deuda
neta como deuda − caja, así que el puente del DCF usaba −1.194 M en vez de
−6.948 M. Reglas probadas para todas las empresas:
- Si la deuda neta resuelta es exactamente deuda − caja del mismo cierre y
  divisa, se restan las inversiones a corto plazo (hecho DERIVED con fuentes).
- Si la fuente ya trae otra definición, o las inversiones son de otro cierre u
  otra divisa, no se toca nada ni se resta dos veces.
- La ingesta trae la métrica de FMP, SEC (US-GAAP) e IFRS/ESEF, y no la emite
  donde la caja SEC ya salió del tag combinado caja + inversiones.
"""

import pytest

from app.services import financial_ingestion_service as fis
from app.valuation.financial_snapshot import FinancialSnapshotBuilder
from tests.test_tesis_huecos_puente import _company, _fact, db  # noqa: F401


def _pltr_like(db, source="FMP", net_debt=-1194.458e6, sti=5753.0e6, sti_period="2025-12-31:FY", sti_unit="USD"):
    company = _company(db, ticker="PLTRX", name="Palantir-like", exchange="NASDAQ", currency="USD")
    _fact(db, company, "revenue", 4475.4e6, "2025-12-31:FY", source=source, unit="USD")
    _fact(db, company, "free_cash_flow", 2100.591e6, "2025-12-31:FY", source=source, unit="USD")
    _fact(db, company, "shares_diluted", 2.56e9, "2025-12-31:FY", source=source, unit="shares")
    _fact(db, company, "cash_and_equivalents", 1423.796e6, "2025-12-31:FY", source=source, unit="USD")
    _fact(db, company, "total_debt", 229.338e6, "2025-12-31:FY", source=source, unit="USD")
    if net_debt is not None:
        _fact(db, company, "net_debt", net_debt, "2025-12-31:FY", source=source, unit="USD")
    if sti is not None:
        _fact(db, company, "short_term_investments", sti, sti_period, source=source, unit=sti_unit)
    return company


def test_deuda_neta_solo_caja_resta_las_inversiones_a_corto(db):
    company = _pltr_like(db)
    snap = FinancialSnapshotBuilder().build(db, company)
    net = snap.facts["net_debt"]
    assert round(float(net.value) / 1e6, 3) == -6947.458
    assert net.source_type == "DERIVED" and net.is_reported is False
    assert len(snap.derived["net_debt"]) == 2
    assert any("inversiones" in w for w in snap.warnings)
    assert "net_debt" not in snap.missing_inputs


def test_deuda_neta_derivada_tambien_resta_las_inversiones(db):
    # Sin hecho net_debt: la derivada deuda − caja también descuenta inversiones.
    company = _pltr_like(db, source="SEC", net_debt=None)
    snap = FinancialSnapshotBuilder().build(db, company)
    assert round(float(snap.facts["net_debt"].value) / 1e6, 3) == -6947.458
    assert len(snap.derived["net_debt"]) == 3  # deuda, caja e inversiones


def test_deuda_neta_con_otra_definicion_no_se_toca(db):
    # La fuente ya da una deuda neta que no es deuda − caja (p.ej. ya neta de
    # inversiones): no se adivina ni se resta dos veces.
    company = _pltr_like(db, net_debt=-6947.458e6)
    snap = FinancialSnapshotBuilder().build(db, company)
    assert round(float(snap.facts["net_debt"].value) / 1e6, 3) == -6947.458
    assert snap.facts["net_debt"].source_type == "FMP"


@pytest.mark.parametrize(
    "kwargs", [{"sti": None}, {"sti_period": "2024-12-31:FY"}, {"sti_unit": "EUR"}]
)
def test_sin_inversiones_o_de_otro_cierre_o_divisa_no_cambia(db, kwargs):
    company = _pltr_like(db, **kwargs)
    snap = FinancialSnapshotBuilder().build(db, company)
    assert round(float(snap.facts["net_debt"].value) / 1e6, 3) == -1194.458


def test_ingesta_mapea_inversiones_a_corto_en_fmp_sec_e_ifrs():
    fmp = {metric: field for metric, field, _unit in fis.BALANCE_METRICS}
    assert fmp["short_term_investments"] == "shortTermInvestments"
    sec = {metric: concepts for metric, concepts, _unit in fis.SEC_METRIC_MAP}
    assert "MarketableSecuritiesCurrent" in sec["short_term_investments"]
    assert "ShortTermInvestments" in sec["short_term_investments"]
    metrics = [metric for metric, _c, _u in fis.SEC_METRIC_MAP]
    # Detrás de la caja: su concepto ganador decide si se emiten.
    assert metrics.index("short_term_investments") > metrics.index("cash_and_equivalents")
    esef = {metric: concepts for metric, concepts, _unit in fis.ESEF_METRIC_MAP}
    assert esef["short_term_investments"] == ["ifrs-full:ShorttermDepositsNotClassifiedAsCashEquivalents"]
    ifrs = {metric: concepts for metric, concepts, _unit in fis.SEC_IFRS_METRIC_MAP}
    assert "short_term_investments" in ifrs


def test_no_se_emiten_inversiones_si_la_caja_ya_las_incluye():
    usage = {
        "cash_and_equivalents": {
            "2025-12-31": "CashCashEquivalentsAndShortTermInvestments",
            "2025-09-30:Q3": "CashCashEquivalentsAndShortTermInvestments",
            "2024-12-31": "CashAndCashEquivalentsAtCarryingValue",
        }
    }
    assert fis._cash_includes_investments(usage, "2025-12-31") is True
    assert fis._cash_includes_investments(usage, "2025-09-30") is True
    assert fis._cash_includes_investments(usage, "2024-12-31") is False
    assert fis._cash_includes_investments({}, "2024-12-31") is False
