"""Nico, 8-nov-2026 (AITerminal): superinversores con 13F que faltaban en /inversores.
CIK y nombre oficial copiados del COVERPAGE de los SEC Form 13F Data Sets
(01jun2026-31aug2026), uno a uno."""

from app.services.investors import INVESTORS, get_investor
from app.services.manager_holding_ingestion_service import REVIEWED_MANAGERS

NEW = {
    "dalio": ("0001350694", "Bridgewater Associates, LP"),
    "icahn": ("0000921669", "ICAHN CARL C"),
    "soros": ("0001029160", "SOROS FUND MANAGEMENT LLC"),
    "laffont": ("0001135730", "COATUE MANAGEMENT LLC"),
    "halvorsen": ("0001103804", "VIKING GLOBAL INVESTORS LP"),
}


def test_superinversores_nuevos_con_cik_revisado():
    for slug, (cik, official) in NEW.items():
        investor = get_investor(slug)
        assert investor is not None and investor.cik == cik, slug
        assert REVIEWED_MANAGERS[cik] == official, slug
    assert len(INVESTORS) == 37
