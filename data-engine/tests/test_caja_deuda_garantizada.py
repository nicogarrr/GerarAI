"""total_debt con deuda garantizada / no garantizada como componentes sueltos (regla 16 de ingesta SEC)."""
from app.services.financial_ingestion_service import (
    SEC_INGESTION_RULES_VERSION,
    SEC_METRIC_MAP,
    _collect_by_concept,
    _merge_for_metric,
)

END = "2026-09-30"


def _debt(**tags):
    fact = {"end": END, "filed": "2026-11-05", "form": "10-Q", "fp": "Q3", "accn": "0001326110-26-000099"}
    us_gaap = {k: {"units": {"USD": [{**fact, "val": v}]}} for k, v in tags.items()}
    concepts = next(c for m, c, _ in SEC_METRIC_MAP if m == "total_debt")
    merged = _merge_for_metric(
        _collect_by_concept(us_gaap, concepts, "USD", forms={"10-Q"}, periods={"Q3"}, min_span=None, max_span=None),
        "total_debt",
    )
    return merged.get(END)


def test_solo_deuda_garantizada_da_total():
    # IBRX 10-Q 3T 2026: SecuredLongTermDebt 426,338 M$ y arrendamiento financiero 3,705 M$; antes total N/D.
    row = _debt(SecuredLongTermDebt=426_338_000, FinanceLeaseLiabilityNoncurrent=2_652_000,
                FinanceLeaseLiabilityCurrent=1_053_000)
    assert row is not None
    assert row["val"] == 426_338_000 + 2_652_000 + 1_053_000
    assert "SecuredLongTermDebt" in row["_components"]


def test_garantizada_y_no_garantizada_se_suman_una_vez():
    row = _debt(SecuredLongTermDebt=300, UnsecuredLongTermDebt=200, SecuredDebt=300)
    assert row["val"] == 500
    assert set(row["_components"]) == {"SecuredLongTermDebt", "UnsecuredLongTermDebt"}


def test_con_garantizada_no_se_suma_otra_vez_el_vencimiento_corriente():
    row = _debt(SecuredLongTermDebt=400, LongTermDebtCurrent=50)
    assert row["val"] == 400


def test_deuda_a_plazo_manda_sobre_el_desglose():
    row = _debt(LongTermDebt=700, SecuredLongTermDebt=400)
    assert row["val"] == 700


def test_version_de_reglas():
    assert SEC_INGESTION_RULES_VERSION >= 16
