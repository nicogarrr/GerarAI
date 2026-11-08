"""ESEF: lo que el emisor etiqueta manda: beneficio atribuible a la dominante y acciones diluidas medias.

Antes: el mapa ESEF tomaba ifrs-full:ProfitLoss (total). Eurofins 2024: 405,5 M en vez de 367,6 M, y las
acciones salían derivadas (beneficio / BPA diluido, «sin dato directo» y sin documento citado) aunque el
filing etiqueta AdjustedWeightedAverageShares = 194,5 M.
"""
from __future__ import annotations

from app.services import financial_ingestion_service as F


def _fact(v: float) -> dict:
    return {"val": v, "start": "2024-01-01", "end": "2024-12-31", "decimals": -5}


def _net_income(facts: dict) -> float:
    concepts = {m: c for m, c, _u in F.ESEF_METRIC_MAP}["net_income"]
    merged, _cov = F._merge_esef_periods(facts, concepts, "iso4217:EUR", "net_income")
    return float(next(iter(merged.values()))["val"])


def test_atribuible_manda_sobre_el_total():
    facts = {"ifrs-full:ProfitLoss": {"iso4217:EUR": [_fact(405.5e6)]},
             "ifrs-full:ProfitLossAttributableToOwnersOfParent": {"iso4217:EUR": [_fact(367.6e6)]}}
    assert _net_income(facts) == 367.6e6


def test_sin_desglose_se_usa_el_total():
    assert _net_income({"ifrs-full:ProfitLoss": {"iso4217:EUR": [_fact(100e6)]}}) == 100e6


def test_reglas_esef_versionadas():
    assert F.ESEF_INGESTION_RULES_VERSION >= 3


def test_acciones_diluidas_etiquetadas_se_toman_tal_cual():
    facts = {"ifrs-full:AdjustedWeightedAverageShares": {"xbrli:shares": [_fact(194.5e6)]}}
    assert {k: float(v) for k, v in F.esef_tagged_diluted_shares(facts).items()} == {"2024-12-31": 194.5e6}
    assert F.esef_tagged_diluted_shares({}) == {}
