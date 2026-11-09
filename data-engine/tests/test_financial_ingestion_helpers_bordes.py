"""Bordes de financial_ingestion_service.py (lote A1): helpers puros.

Todos los tests llaman a helpers sincronos del modulo con datos sinteticos:
sin DB, sin red, sin reloj, sin estado global. Es la misma via directa ya
aceptada para helpers puros en test_sec_helpers_bordes y
test_sec_xbrl_instance_bordes; aqui la via publica seria refresh_from_* con
BD y red dobladas para llegar al mismo guard. Aserciones por igualdad.

Sin lineas declaradas inalcanzables en este lote.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services import financial_ingestion_service as fis

# --- _sec_reporting_currency (113->111) ---


def test_sec_reporting_currency_ignora_unidades_compuestas():
    """113->111: una clave de unidad compuesta ("USD/shares") no es divisa ISO
    y no cuenta; gana la ISO con mas observaciones."""
    us_gaap = {
        "Assets": {
            "units": {
                "USD/shares": [{"end": "2025-12-31"}],
                "USD": [{"end": "2025-12-31"}],
            }
        }
    }
    assert fis._sec_reporting_currency(us_gaap) == "USD"


# --- _ifrs_annual_values (476->475) ---


def test_ifrs_annual_values_solo_hechos_fy_completos():
    """476->475: filas sin fp=FY se saltan; las FY completas entran."""
    ifrs_facts = {
        "Revenue": {
            "units": {
                "EUR": [
                    {"fp": "Q1", "start": "2025-01-01", "end": "2025-03-31", "val": 1},
                    {"fp": "FY", "start": "2025-01-01", "end": "2025-12-31", "val": 2.5},
                ]
            }
        }
    }
    assert fis._ifrs_annual_values(ifrs_facts, "Revenue") == {
        ("2025-01-01", "2025-12-31"): 2.5
    }


# --- _name_tokens (587) y _name_identity_ok (609) ---


def test_name_tokens_sin_nombre_devuelve_vacio():
    """587: sin nombre no hay tokens."""
    assert fis._name_tokens(None) == set()
    assert fis._name_tokens("") == set()


def test_name_identity_sin_tokens_en_un_lado_no_hay_prueba():
    """609: sin tokens significativos en cualquiera de los lados, mismatch."""
    assert fis._name_identity_ok("SA", "Kerry Group plc") is False
    assert fis._name_identity_ok("Kerry Group plc", None) is False


# --- _collapse_aliases (686->683) ---


def test_collapse_aliases_gana_el_filed_mas_reciente():
    """686->683: una entrada menos reciente para el mismo periodo NO sustituye."""
    reciente = {"end": "2025-12-31", "filed": "2026-03-01", "val": 1}
    antigua = {"end": "2025-12-31", "filed": "2026-01-01", "val": 2}
    by_concept = {
        "ConceptoA": {"2025-12-31": reciente},
        "ConceptoB": {"2025-12-31": antigua},
    }
    assert fis._collapse_aliases(by_concept) == {"2025-12-31": reciente}


# --- _latest_debt_signal_end (849, 852-853) ---


def test_latest_debt_signal_end_salta_basura():
    """849: entradas no dict se saltan. 852-853: end no parseable se salta."""
    us_gaap = {
        "LongTermDebt": {
            "units": {
                "USD": ["no-es-dict", {"end": "no-es-fecha"}, {"end": "2026-02-01"}]
            }
        }
    }
    assert fis._latest_debt_signal_end(us_gaap) == date(2026, 2, 1)


# --- widest_in_same_filing (891) ---


def test_widest_in_same_filing_sin_accn_compara_por_filed():
    """891: sin accn en alguno, la misma presentacion se decide por filed."""
    ganador = {"end": "2025-12-31", "filed": "2026-01-15", "val": 100}
    mismo_filing = {"end": "2025-12-31", "filed": "2026-01-15", "val": 200}
    otro_filing = {"end": "2025-12-31", "filed": "2026-02-01", "val": 300}
    by_concept = {
        "ConceptoA": {"2025-12-31": ganador},
        "ConceptoB": {"2025-12-31": mismo_filing},
        "ConceptoC": {"2025-12-31": otro_filing},
    }
    by_end = {"2025-12-31": ganador}
    # 200 supera 100*(1+0,02) y es el mismo filing: gana. 300 es otro filing: no.
    assert fis.widest_in_same_filing(by_concept, by_end) == {
        "2025-12-31": mismo_filing
    }


# --- _negate_entry (1058) ---


def test_negate_entry_sin_valor_numerico_devuelve_la_entrada():
    """1058: val no decimal -> la entrada vuelve intacta."""
    entrada = {"end": "2025-12-31", "val": "no-numero"}
    assert fis._negate_entry(entrada) == entrada


# --- _quarters_from_ytd (1181) ---


def test_quarters_from_ytd_descarta_valores_nulos():
    """1181: un acumulado con val None no entra en la derivacion."""
    ytd = {"2025-03-31": {"val": None, "start": "2025-01-01", "end": "2025-03-31"}}
    assert fis._quarters_from_ytd({}, ytd) == {}


# --- _collect_by_concept (1292-1293, 1303, 1306->1254) ---


def test_collect_by_concept_span_con_fecha_rota_se_salta():
    """1292-1293: start no parseable en un hecho de flujo -> se descarta."""
    us_gaap = {
        "Revenues": {
            "units": {
                "USD": [
                    {
                        "form": "10-K",
                        "fp": "FY",
                        "start": "no-es-fecha",
                        "end": "2025-12-31",
                        "val": 1,
                    }
                ]
            }
        }
    }
    assert fis._collect_by_concept(
        us_gaap, ["Revenues"], "USD",
        forms={"10-K"}, periods={"FY"}, min_span=300, max_span=380,
    ) == {}


def test_collect_by_concept_end_vacio_y_ganador_por_filed():
    """1303: end vacio se descarta. 1306->1254: a igual periodo no sustituye
    una entrada con filed mas antiguo."""
    reciente = {
        "form": "10-K", "fp": "FY", "end": "2025-12-31",
        "filed": "2026-03-01", "val": 1,
    }
    antigua = {
        "form": "10-K", "fp": "FY", "end": "2025-12-31",
        "filed": "2026-01-01", "val": 2,
    }
    sin_end = {"form": "10-K", "fp": "FY", "end": "", "val": 3}
    us_gaap = {
        "Revenues": {"units": {"USD": [reciente, antigua, sin_end]}}
    }
    resultado = fis._collect_by_concept(
        us_gaap, ["Revenues"], "USD",
        forms={"10-K"}, periods={"FY"}, min_span=None, max_span=None,
    )
    assert resultado == {"Revenues": {"2025-12-31": {**reciente, "_concept": "Revenues"}}}


# --- _esef_period (1327-1328, 1334) ---


def test_esef_period_fechas_rotas_y_sin_periodo():
    """1327-1328: span no calculable -> None. 1334: sin end/start ni instant."""
    assert fis._esef_period({"start": "no-es-fecha", "end": "2025-12-31"}) is None
    assert fis._esef_period({"val": 42}) is None


# --- esef_tagged_diluted_shares (1347->1345) ---


def test_esef_tagged_diluted_shares_solo_valores_positivos():
    """1347->1345: val None o no positivo no entra en el resultado."""
    concepto = fis.ESEF_DILUTED_SHARES_CONCEPT
    facts_data = {
        concepto: {
            "xbrli:shares": [
                {"start": "2025-01-01", "end": "2025-12-31", "val": 100},
                {"start": "2024-01-01", "end": "2024-12-31", "val": 0},
                {"start": "2023-01-01", "end": "2023-12-31", "val": "no-numero"},
            ]
        }
    }
    assert fis.esef_tagged_diluted_shares(facts_data) == {
        "2025-12-31": Decimal("100")
    }


# --- _norm_date (1514-1515) ---


def test_norm_date_epoch_fuera_de_rango_devuelve_none():
    """1514-1515: epoch que desborda datetime.fromtimestamp -> None."""
    assert fis._norm_date("999999999999") is None


# --- _rows (1589-1591) ---


def test_rows_dict_se_envuelve_y_otros_tipos_se_descartan():
    """1589-1590: un dict suelto se envuelve en lista. 1591: otro tipo -> []."""
    assert fis._rows({"a": 1}) == [{"a": 1}]
    assert fis._rows("texto") == []


# --- _annual_fiscal_year (1631-1632) ---


def test_annual_fiscal_year_mes_modal_invalido_se_trata_como_none():
    """1631-1632: modal_fy_month no entero -> None -> cierre de enero <= 7 es
    del ejercicio anterior."""
    assert fis._annual_fiscal_year("2026-01-02", "abc") == 2025


# --- _fiscal_annual_pairs (1736-1737) ---


def test_fiscal_annual_pairs_salta_fechas_rotas():
    """1736-1737: un hecho FY 10-K con start no parseable se descarta; el
    valido entra con su mes normalizado."""
    us_gaap = {
        "Assets": {"units": {"USD": [{"end": "2025-12-31"}]}},
        "PaymentsForRepurchaseOfCommonStock": {
            "units": {
                "USD": [
                    {
                        "fp": "FY", "form": "10-K",
                        "start": "no-es-fecha", "end": "2025-12-31",
                    },
                    {
                        "fp": "FY", "form": "10-K",
                        "start": "2025-01-01", "end": "2025-12-31",
                    },
                ]
            }
        },
    }
    assert fis._fiscal_annual_pairs(us_gaap) == [("12", "2025-12-31")]
