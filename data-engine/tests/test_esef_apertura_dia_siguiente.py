"""ESEF: un saldo de apertura puesto el día siguiente al cierre es el cierre anterior.

AENA (FY2023, xBRL-JSON de filings.xbrl.org) etiqueta la caja de apertura en
«2023-01-02T00:00:00», que el conector convierte (bien) al instante 2023-01-01.
Se guardaba como «2023-01-01:FY» al lado del «2022-12-31:FY»: un balance
duplicado con otra fecha (en prod, 16 empresas reingestadas el 29/10) que no
empareja con la deuda ni con la caja del cierre. Ahora se publica con la fecha
del cierre, y si el emisor ya da ese cierre, manda el cierre.
"""

from app.services.connectors.esef import normalize_xbrl_json
from app.services.financial_ingestion_service import _merge_esef_periods

CASH = "ifrs-full:CashAndCashEquivalents"
REV = "ifrs-full:Revenue"


def _doc(facts):
    out = {}
    for i, (concept, period, value) in enumerate(facts):
        out[f"f{i}"] = {
            "value": value,
            "decimals": -3,
            "dimensions": {
                "concept": concept,
                "entity": "scheme:959800R7QMXKF0NFMT29",
                "period": period,
                "unit": "iso4217:EUR",
            },
        }
    return normalize_xbrl_json({"facts": out})


def test_apertura_del_dia_siguiente_se_publica_como_cierre_anterior():
    facts = _doc([
        (REV, "2023-01-01T00:00:00/2024-01-01T00:00:00", "5000"),
        (REV, "2022-01-01T00:00:00/2023-01-01T00:00:00", "4600"),
        (CASH, "2024-01-01T00:00:00", "2363"),       # cierre 2023-12-31
        (CASH, "2023-01-02T00:00:00", "1573"),       # apertura 2023-01-01
    ])
    by_period, _ = _merge_esef_periods(facts, [CASH], "iso4217:EUR", "cash_and_equivalents")
    assert sorted(by_period) == ["2022-12-31", "2023-12-31"]
    assert by_period["2022-12-31"]["val"] == "1573"


def test_si_el_emisor_da_el_cierre_manda_el_cierre():
    facts = _doc([
        (REV, "2022-01-01T00:00:00/2023-01-01T00:00:00", "4600"),
        (CASH, "2023-01-02T00:00:00", "1500"),       # apertura (reexpresada)
        (CASH, "2023-01-01T00:00:00", "1573"),       # cierre 2022-12-31
    ])
    by_period, coverage = _merge_esef_periods(facts, [CASH], "iso4217:EUR", "cash_and_equivalents")
    assert sorted(by_period) == ["2022-12-31"]
    assert by_period["2022-12-31"]["val"] == "1573"
    assert coverage["ambiguous"] == {}


def test_un_instante_que_no_sigue_a_un_cierre_no_se_toca():
    facts = _doc([
        (REV, "2022-01-01T00:00:00/2023-01-01T00:00:00", "4600"),
        (CASH, "2023-07-01T00:00:00", "900"),        # 30/06, cierre semestral
    ])
    by_period, _ = _merge_esef_periods(facts, [CASH], "iso4217:EUR", "cash_and_equivalents")
    assert sorted(by_period) == ["2023-06-30"]


def test_las_duraciones_no_cambian():
    facts = _doc([
        (REV, "2023-01-01T00:00:00/2024-01-01T00:00:00", "5000"),
        (REV, "2022-01-01T00:00:00/2023-01-01T00:00:00", "4600"),
    ])
    by_period, _ = _merge_esef_periods(facts, [REV], "iso4217:EUR", "revenue")
    assert {k: v["val"] for k, v in by_period.items()} == {"2023-12-31": "5000", "2022-12-31": "4600"}
