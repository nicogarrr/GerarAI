"""Contratos de normalizacion de edgartools_facts: decimales, meses fiscales
normalizados, filtros de companyfacts, fusion por periodo (alias/suma/alcance)
y etiquetas trimestrales.

La regla de oro probada aqui: alias gana el ``filed`` mas reciente, las partes
disjuntas se suman fail-closed, el revenue de banco exige ambas partes, y el
mes fiscal se normaliza (dias 1-7 = mes anterior, drift 52/53 semanas).
"""

from decimal import Decimal
from types import SimpleNamespace

from app.services.connectors.edgartools_facts import (
    _collapse_aliases,
    _collapse_by_scope,
    _compose_bank_revenue_entries,
    _decimal,
    _iso,
    _modal_month,
    _normalized_month,
    _span_days,
    _sum_disjoint,
    anchors_from_submissions,
    entries_from_companyfacts,
    entries_from_edgartools_facts,
    merge_entries,
    quarter_label,
)

# -- helpers puros ----------------------------------------------------------


def test_decimal_none_vacio_e_invalido():
    assert _decimal(None) is None
    assert _decimal("") is None
    assert _decimal("no numerico") is None
    assert _decimal("12.5") == Decimal("12.5")
    assert _decimal(7) == Decimal("7")


def test_iso_none_vacio_y_valor():
    assert _iso(None) is None
    assert _iso("   ") is None
    assert _iso(" 2025-12-31 ") == "2025-12-31"


def test_normalized_month_dias_1_a_7_son_mes_anterior():
    assert _normalized_month("2025-01-05") == "12"   # drift 52/53 sem: enero temprano = diciembre
    assert _normalized_month("2025-01-31") == "01"
    assert _normalized_month("2025-06-03") == "05"
    assert _normalized_month("no-fecha") is None


def test_span_days_faltantes_e_invalidos():
    assert _span_days(None, "2025-12-31") is None
    assert _span_days("2025-01-01", None) is None
    assert _span_days("malo", "2025-12-31") is None
    assert _span_days("2025-01-01", "2025-12-31") == 364


# -- entries_from_companyfacts ----------------------------------------------


def _cf(entries):
    return {"Revenues": {"units": {"USD": entries}}}


def test_companyfacts_filtra_form_fp_y_no_dict():
    us_gaap = _cf([
        {"form": "10-K", "fp": "FY", "start": "2024-01-01", "end": "2024-12-31", "val": 1, "filed": "2025-01-01"},
        {"form": "8-K", "fp": "FY", "start": "2024-01-01", "end": "2024-12-31", "val": 2, "filed": "2025-01-02"},
        {"form": "10-K", "fp": "Q1", "start": "2024-01-01", "end": "2024-03-31", "val": 3, "filed": "2025-01-01"},
        "no dict",
    ])
    out = entries_from_companyfacts(us_gaap, ["Revenues"], "USD", forms={"10-K"}, periods={"FY"}, min_span=300, max_span=380)
    assert list(out["Revenues"].values())[0]["val"] == 1  # 8-K y Q1 descartados


def test_companyfacts_filtro_de_duracion_para_flujos():
    us_gaap = _cf([
        {"form": "10-K", "fp": "FY", "start": "2024-01-01", "end": "2024-12-31", "val": 1, "filed": "2025-01-01"},
        {"form": "10-K", "fp": "FY", "start": "2024-01-01", "end": "2024-02-29", "val": 9, "filed": "2025-01-01"},
    ])
    out = entries_from_companyfacts(us_gaap, ["Revenues"], "USD", forms={"10-K"}, periods={"FY"}, min_span=300, max_span=380)
    assert len(out["Revenues"]) == 1 and list(out["Revenues"].values())[0]["val"] == 1  # 59 dias fuera de rango


def test_companyfacts_sin_end_se_descarta_y_filed_mas_reciente_gana():
    us_gaap = _cf([
        {"form": "10-K", "fp": "FY", "end": "2024-12-31", "val": 1, "filed": "2025-01-01"},
        {"form": "10-K", "fp": "FY", "end": "2024-12-31", "val": 2, "filed": "2025-02-01"},
        {"form": "10-K", "fp": "FY", "val": 3, "filed": "2025-01-01"},
    ])
    out = entries_from_companyfacts(us_gaap, ["Revenues"], "USD", forms={"10-K"}, periods={"FY"}, min_span=None, max_span=None)
    assert out["Revenues"]["2024-12-31"]["val"] == 2  # recast posterior gana
    assert len(out["Revenues"]) == 1                  # sin end no entra


def test_companyfacts_ancla_anual_falla_cerrado():
    entries = [
        {"form": "10-K", "fp": "FY", "end": "2024-12-31", "val": 1, "filed": "2025-01-01", "accn": "A1"},
        {"form": "10-K", "fp": "FY", "end": "2024-12-31", "val": 2, "filed": "2025-01-01", "accn": "A2"},
        {"form": "10-K", "fp": "FY", "end": "2024-06-30", "val": 3, "filed": "2025-01-01", "accn": "A3"},
    ]
    us_gaap = _cf(entries)
    # A2 sin ancla declarada -> fuera; A3 ancla a diciembre pero su hecho es junio -> fuera
    out = entries_from_companyfacts(
        us_gaap, ["Revenues"], "USD", forms={"10-K"}, periods={"FY"},
        min_span=None, max_span=None, annual_anchors={"A1": "2024-12-31", "A3": "2024-12-31"},
    )
    assert list(out["Revenues"].values())[0]["val"] == 1
    # {} = cero hechos anuales: nada entra (ni el concepto se materializa)
    out2 = entries_from_companyfacts(
        us_gaap, ["Revenues"], "USD", forms={"10-K"}, periods={"FY"},
        min_span=None, max_span=None, annual_anchors={},
    )
    assert out2 == {}


# -- entries_from_edgartools_facts ------------------------------------------


def test_edgartools_facts_dict_y_objeto():
    facts = [
        {"concept": "Revenues", "period_end": "2024-12-31", "value": 10, "filing_date": "2025-01-01", "form_type": "10-K", "fiscal_period": "FY", "accession": "A1", "unit": "USD"},
        SimpleNamespace(concept="NetIncomeLoss", period_end="2024-12-31", numeric_value=5, filing_date="2025-01-01", form_type="10-K", fiscal_period="FY", accession=None, unit=None),
        {"concept": "FooNoMapeado", "period_end": "2024-12-31", "value": 1},          # no canonico: fuera
        {"concept": "Assets", "period_end": None, "value": 1},                          # sin end: fuera
        {"concept": "Assets", "period_end": "2024-12-31", "value": None},               # sin valor: fuera
        {"concept": "Liabilities", "period_end": "2024-12-31", "value": 1},             # no pedido: fuera
    ]
    out = entries_from_edgartools_facts(facts, ["Revenues", "NetIncomeLoss", "Assets"])
    assert set(out) == {"Revenues", "NetIncomeLoss"}
    rev = out["Revenues"]["2024-12-31"]
    assert rev["val"] == 10 and rev["form"] == "10-K" and rev["_unit"] == "USD"
    ni = out["NetIncomeLoss"]["2024-12-31"]
    assert ni["val"] == 5 and "_unit" not in ni and "accn" not in ni


def test_edgartools_facts_get_all_facts_y_dedup_por_filed():
    facts_obj = SimpleNamespace(get_all_facts=lambda: [
        {"concept": "Revenues", "period_end": "2024-12-31", "value": 1, "filing_date": "2025-01-01"},
        {"concept": "Revenues", "period_end": "2024-12-31", "value": 2, "filing_date": "2025-02-01"},
    ])
    out = entries_from_edgartools_facts(facts_obj, ["Revenues"])
    assert out["Revenues"]["2024-12-31"]["val"] == 2


# -- fusion por periodo ------------------------------------------------------


def test_collapse_aliases_gana_filed_mas_reciente_entre_conceptos():
    by_concept = {
        "Revenues": {"2024-12-31": {"end": "2024-12-31", "val": 1, "filed": "2025-01-01"}},
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"2024-12-31": {"end": "2024-12-31", "val": 2, "filed": "2025-02-01"}},
    }
    assert _collapse_aliases(by_concept)["2024-12-31"]["val"] == 2


def test_collapse_by_scope_gana_el_concepto_declarado_primero():
    by_concept = {
        "DebtLongtermAndShorttermCombinedAmount": {"2024-12-31": {"end": "2024-12-31", "val": 1, "filed": "2025-01-01"}},
        "LongTermDebt": {"2024-12-31": {"end": "2024-12-31", "val": 2, "filed": "2025-02-01"}},
    }
    # alcance: gana el primero declarado; filed solo desempata recasts (ya dedup por concepto)
    assert _collapse_by_scope(by_concept)["2024-12-31"]["val"] == 1


def test_sum_disjoint_suma_componentes_y_falla_cerrado_en_valores():
    by_concept = {
        "FiniteLivedIntangibleAssetsNet": {"2024-12-31": {"end": "2024-12-31", "val": "30", "filed": "2025-01-01"}},
        "IndefiniteLivedIntangibleAssetsExcludingGoodwill": {"2024-12-31": {"end": "2024-12-31", "val": "70", "filed": "2025-02-01"}},
    }
    merged = _sum_disjoint(by_concept)["2024-12-31"]
    assert merged["val"] == 100.0
    assert merged["filed"] == "2025-02-01"
    assert merged["_concept"] == "FiniteLivedIntangibleAssetsNet+IndefiniteLivedIntangibleAssetsExcludingGoodwill"
    # un solo componente: el concepto queda sin combinar
    single = _sum_disjoint({"FiniteLivedIntangibleAssetsNet": {"2024-12-31": {"end": "2024-12-31", "val": "30", "filed": "2025-01-01"}}})
    assert single["2024-12-31"]["_concept"] == "FiniteLivedIntangibleAssetsNet"
    # valor no decimal: ese hecho no suma (fail-closed por componente)
    bad = _sum_disjoint({
        "FiniteLivedIntangibleAssetsNet": {"2024-12-31": {"end": "2024-12-31", "val": "NaN-x", "filed": "2025-01-01"}},
        "IndefiniteLivedIntangibleAssetsExcludingGoodwill": {"2024-12-31": {"end": "2024-12-31", "val": "70", "filed": "2025-01-01"}},
    })
    assert bad["2024-12-31"]["val"] == 70.0


def test_merge_entries_despacha_por_tipo_de_metrica():
    by_concept = {
        "FiniteLivedIntangibleAssetsNet": {"2024-12-31": {"end": "2024-12-31", "val": "30", "filed": "2025-01-01"}},
        "IndefiniteLivedIntangibleAssetsExcludingGoodwill": {"2024-12-31": {"end": "2024-12-31", "val": "70", "filed": "2025-01-01"}},
    }
    assert merge_entries(by_concept, "intangible_assets")["2024-12-31"]["val"] == 100.0  # suma
    debt = {
        "DebtLongtermAndShorttermCombinedAmount": {"2024-12-31": {"end": "2024-12-31", "val": 1, "filed": "2025-01-01"}},
        "LongTermDebt": {"2024-12-31": {"end": "2024-12-31", "val": 2, "filed": "2025-02-01"}},
    }
    assert merge_entries(debt, "total_debt")["2024-12-31"]["val"] == 1  # alcance
    alias = {
        "Revenues": {"2024-12-31": {"end": "2024-12-31", "val": 1, "filed": "2025-01-01"}},
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"2024-12-31": {"end": "2024-12-31", "val": 2, "filed": "2025-02-01"}},
    }
    assert merge_entries(alias, "revenue")["2024-12-31"]["val"] == 2  # alias: filed mas reciente


def test_compose_bank_revenue_exige_ambas_partes():
    collected = {
        "InterestIncomeExpenseNet": {"2024-12-31": {"end": "2024-12-31", "val": "10", "filed": "2025-01-01"}},
        "NoninterestIncome": {"2024-12-31": {"end": "2024-12-31", "val": "5", "filed": "2025-01-01"}},
    }
    composed = _compose_bank_revenue_entries(collected)
    assert composed["2024-12-31"]["val"] == 15.0
    assert composed["2024-12-31"]["_concept"] == "InterestIncomeExpenseNet+NoninterestIncome"
    # sin una parte no hay revenue (fail-closed)
    solo_interes = _compose_bank_revenue_entries({"InterestIncomeExpenseNet": collected["InterestIncomeExpenseNet"]})
    assert solo_interes == {}


# -- anchors y etiquetas ------------------------------------------------------


def test_anchors_from_submissions_filtra_form_y_fecha():
    submissions = {"filings": {"recent": {
        "accessionNumber": ["A1", "A2", "A3"],
        "form": ["10-K", "8-K", "10-K"],
        "reportDate": ["2024-12-31", "2024-06-30", ""],
    }}}
    anchors = anchors_from_submissions(submissions)
    assert anchors == {"A1": "2024-12-31"}  # 8-K fuera; sin reportDate fuera
    custom = anchors_from_submissions(submissions, annual_forms={"8-K"})
    assert custom == {"A2": "2024-06-30"}


def test_modal_month_moda_y_vacio():
    assert _modal_month([]) is None
    ends = ["2024-12-31", "2023-12-31", "2022-06-30"]
    assert _modal_month(ends) == "12"


def test_quarter_label_distancia_al_cierre_y_fallbacks():
    assert quarter_label("2024-12-31", "12", "FY") == "Q4"
    assert quarter_label("2025-03-31", "12", "Q1") == "Q1"
    assert quarter_label("2025-06-30", "12", "Qx") == "Q2"
    assert quarter_label("2025-09-30", "12", "Qx") == "Q3"
    # delta 1-2 meses: fin imposible en trimestres sanos -> fp declarado
    assert quarter_label("2025-01-31", "12", "Q1") == "Q1"
    # sin mes modal: fp declarado
    assert quarter_label("2025-03-31", None, "Q1") == "Q1"
