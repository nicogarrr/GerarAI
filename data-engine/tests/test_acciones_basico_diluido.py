"""Empresas con pérdidas: etiquetan acciones y BPA «básico y diluido» en un único concepto (p. ej. ASTS, RXRX)."""
from __future__ import annotations

from app.services import financial_ingestion_service as fis


def test_acciones_y_bpa_basico_y_diluido_mapeados():
    sec = {m: c for m, c, _ in fis.SEC_METRIC_MAP}
    assert sec["shares_diluted"][0] == "WeightedAverageNumberOfDilutedSharesOutstanding"
    assert "WeightedAverageNumberOfShareOutstandingBasicAndDiluted" in sec["shares_diluted"]
    assert sec["eps_diluted"][0] == "EarningsPerShareDiluted"
    assert "EarningsPerShareBasicAndDiluted" in sec["eps_diluted"]
    assert fis.SEC_INGESTION_RULES_VERSION >= 8
