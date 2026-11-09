"""Gestoras detectadas por SIC 6282 aunque la industria de la ficha sea genérica (KKR: «Financial Services»)."""
from types import SimpleNamespace

from app.services import financial_ingestion_service as ingestion
from app.services import sec_extension_facts as sef


def _co(industry, sector="Financials", tags=None):
    return SimpleNamespace(industry=industry, sector=sector, factor_tags=tags)


def test_sic_de_edgar_marca_gestora():
    kkr = _co("Financial Services")
    assert not sef.is_asset_manager(kkr)
    assert sef.is_asset_manager(kkr, "6282")
    assert sef.is_asset_manager(kkr, 6282)


def test_etiqueta_sic_de_la_ficha_marca_gestora():
    assert sef.is_asset_manager(_co("Financial Services", tags=["sic:6282"]))


def test_etiqueta_de_industria_investment_advice():
    assert sef.is_asset_manager(_co("Investment advice (SIC 6282)"))


def test_otro_sic_no_es_gestora():
    assert not sef.is_asset_manager(_co("Financial Services"), "6331")
    assert not sef.is_asset_manager(_co("Insurance"), "")
    assert not sef.is_asset_manager(_co("Financial Services"), "x")


def test_wanted_metrics_pide_fre_y_de_con_sic():
    wanted = sef.wanted_metrics(_co("Financial Services"), {}, ingestion.SEC_METRIC_MAP, "2025-12-31", sic="6282")
    assert set(sef.ASSET_MANAGER_METRICS) <= set(wanted)
    assert sef.wanted_metrics(_co("Financial Services"), {}, ingestion.SEC_METRIC_MAP, "2025-12-31") == []
