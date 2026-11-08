"""Servicio de la TIR para el accionista: elección del método con razones dadas por el código y mapeo
de adquisiciones (las compras de negocios eran invisibles para el motor)."""
from __future__ import annotations

from app.services import financial_ingestion_service as fis
from app.services.shareholder_irr_service import choose_method


def test_metodo_operativa_con_ebitda():
    m = choose_method(revenue=7000.0, ebitda_years=[1200.0, 1300.0, 1400.0], net_income=400.0, financial=False,
                      segment_ebitda=False)
    assert m["chosen"] == "tir_ev_ebitda"
    assert "solo publica ingresos por segmento" in m["discarded"]["sotp"]
    assert "dcf" in m["discarded"] and "tir_per" in m["discarded"]


def test_metodo_financiera_va_por_per():
    m = choose_method(revenue=75000.0, ebitda_years=[None, None, None], net_income=1300.0, financial=True,
                      segment_ebitda=False)
    assert m["chosen"] == "tir_per"
    assert "filiales" in m["discarded"]["tir_ev_ebitda"]


def test_metodo_sin_ebitda_ni_ingresos():
    assert choose_method(revenue=None, ebitda_years=[], net_income=None, financial=False,
                         segment_ebitda=False)["chosen"] == "sotp"
    assert choose_method(revenue=900.0, ebitda_years=[-10.0, 5.0], net_income=20.0, financial=False,
                         segment_ebitda=False)["chosen"] == "tir_per"


def _maps():
    for value in vars(fis).values():
        if isinstance(value, list) and value and isinstance(value[0], tuple) and len(value[0]) == 3:
            yield value


def test_adquisiciones_mapeadas_en_sec_y_ifrs():
    concepts = {c for m in _maps() for metric, cs, _ in m if metric == "acquisitions" for c in cs}
    assert "PaymentsToAcquireBusinessesNetOfCashAcquired" in concepts
    assert "ifrs-full:CashFlowsUsedInObtainingControlOfSubsidiariesOrOtherBusinessesClassifiedAsInvestingActivities" in concepts
    buybacks = {c for m in _maps() for metric, cs, _ in m if metric == "common_stock_repurchased" for c in cs}
    assert "ifrs-full:PaymentsToAcquireOrRedeemEntitysShares" in buybacks  # recompras IFRS (Eurofins, BN)


def test_subir_version_de_reglas_para_reingerir_las_adquisiciones():
    # Sin subirla, una empresa cuyo payload SEC/ESEF no cambia nunca recogería el concepto nuevo
    # (atajo «unchanged»): POOL y META quedaban sin adquisiciones en la prueba local.
    assert fis.SEC_INGESTION_RULES_VERSION >= 3
    assert fis.ESEF_INGESTION_RULES_VERSION >= 2
