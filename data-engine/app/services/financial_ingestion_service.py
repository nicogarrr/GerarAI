from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import delete, or_, select, tuple_
from sqlalchemy.orm import Session

from app.core.errors import redact_secrets
from app.core.source_urls import linkable_source_url
from app.models import Company, Document, FinancialFact, FinancialStatement, MarketPrice
from app.services.connectors import esef as esef_connector
from app.services.connectors import fred as fred_connector
from app.services.connectors import sec_edgar as sec_edgar_connector
from app.services.connectors.fmp import FMPClient
from app.services.connectors.sec import ANNUAL_REPORT_FORMS, SECClient
from app.services.fact_chunk_service import sync_company_fact_chunks
from app.services.fact_deletion import (
    delete_financial_facts,
    drop_shadowed_facts,
    tenant_condition,
)
from app.services.number_parsing import parse_machine_decimal as _decimal
from app.services.price_units import price_in_currency
from app.services.ttm_fundamentals import (
    NON_ADDITIVE_FLOWS,
    PeriodValue,
    derive_quarters_from_ytd,
)

MetricSpec = tuple[str, str, str]

# Concepts that are DISJOINT PARTS of one total, not alternative tags for it.
# Treating them as aliases meant whichever happened to be filed last won, so an
# issuer with 5.000 of finite-lived and 8.000 of indefinite-lived intangibles
# stored only one of the two and the metric silently changed meaning between
# years. These are summed per period instead.
SEC_INTANGIBLE_COMPONENTS = [
    "FiniteLivedIntangibleAssetsNet",
    "IndefiniteLivedIntangibleAssetsExcludingGoodwill",
]
# Metrics whose concepts are disjoint parts to be summed, not alternative tags.
SUMMED_COMPONENT_METRICS: frozenset[str] = frozenset({"intangible_assets"})
CAPITAL_FLOW_METRICS = frozenset({
    "common_stock_repurchased", "common_stock_issued", "shares_repurchased", "stock_based_compensation",
})
CAPITAL_PROVENANCE_METRICS = CAPITAL_FLOW_METRICS | {"shares_outstanding"}

# Formularios cuya portada declara acciones en circulacion (dei).
SHARES_OUTSTANDING_FORMS = frozenset({"10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "40-F"})

# Which provider wins when the same (metric, fiscal year) exists more than once.
# A regulator filing the number itself beats a vendor's restatement of it, and
# a vendor beats a manually typed value, which beats an unattributed row.
# Without this, `created_at` decided ownership and the DCF could be anchored on
# whichever provider happened to be ingested last.
SOURCE_PRIORITY: dict[str, int] = {
    "SEC": 0,
    "ESEF": 0,
    "CNMV": 0,
    "FMP": 10,
    "FMP_profile": 20,
    # Yahoo no oficial: por debajo de cualquier fuente oficial o FMP.
    "YAHOO_FUNDAMENTALS": 40,
}



def _iso_currency(raw: Any) -> str | None:
    """Codigo ISO de 3 letras en mayusculas, o None si no lo es."""
    text = str(raw or "").strip().upper()
    return text if len(text) == 3 and text.isalpha() else None


def _with_reporting_currency(unit: str, currency: str | None) -> str:
    """Sustituye la divisa de una unidad monetaria por la de reporte.

    Las tablas de metricas dicen ``USD``/``USD/share`` como plantilla de
    "importe monetario", no como hecho: BABA reporta en CNY, Toyota en JPY.
    ``shares``, ``decimal`` y demas unidades no monetarias no cambian. Sin
    divisa declarada se conserva la plantilla (comportamiento anterior).
    """
    if currency is None:
        return unit
    if unit == "USD":
        return currency
    if unit == "USD/share":
        return f"{currency}/share"
    return unit


def _sec_reporting_currency(us_gaap: dict[str, Any]) -> str | None:
    """Divisa de reporte de un filer SEC segun sus propios hechos us-gaap.

    Un 10-K reporta en USD, pero un 20-F en US GAAP puede reportar en CNY
    (BABA), TWD... y entonces companyfacts trae ``units: {"CNY": [...]}``.
    Leer solo la clave ``USD`` dejaba a esos emisores sin hechos (o, peor,
    con la traduccion de conveniencia del ultimo ano). Se cuenta, en los
    conceptos de referencia, cuantas observaciones hay por divisa ISO y gana
    la que mas tiene. Empate o ausencia de evidencia -> desconocida.
    """
    counts: Counter[str] = Counter()
    for concept in _SEC_CURRENCY_PROBE_CONCEPTS:
        units = (us_gaap.get(concept) or {}).get("units") or {}
        for key, entries in units.items():
            code = _iso_currency(key) if "/" not in str(key) else None
            if code is not None and isinstance(entries, list):
                counts[code] += len(entries)
    if not counts:
        return None
    best = max(counts.values())
    leaders = sorted(code for code, n in counts.items() if n == best)
    return leaders[0] if len(leaders) == 1 else None


def _sec_unit_keys(unit: str, currency: str | None) -> tuple[str, str] | None:
    """(unidad a guardar, clave de ``units`` en companyfacts) para la divisa."""
    if currency is None and unit in {"USD", "USD/share"}:
        return None
    stored = _with_reporting_currency(unit, currency)
    if stored.endswith("/share"):
        return stored, stored.replace("/share", "/shares")
    return stored, stored


_SEC_CURRENCY_PROBE_CONCEPTS = (
    "Assets",
    "Liabilities",
    "StockholdersEquity",
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "NetIncomeLoss",
    "NetCashProvidedByUsedInOperatingActivities",
    "CashAndCashEquivalentsAtCarryingValue",
)

INCOME_METRICS: list[MetricSpec] = [
    ("revenue", "revenue", "USD"),
    ("gross_profit", "grossProfit", "USD"),
    ("operating_income", "operatingIncome", "USD"),
    ("income_before_tax", "incomeBeforeTax", "USD"),
    ("income_tax_expense", "incomeTaxExpense", "USD"),
    ("interest_expense", "interestExpense", "USD"),
    ("net_income", "netIncome", "USD"),
    ("ebitda", "ebitda", "USD"),
    ("eps_diluted", "epsdiluted", "USD/share"),
    ("shares_diluted", "weightedAverageShsOutDil", "shares"),
]

BALANCE_METRICS: list[MetricSpec] = [
    ("cash_and_equivalents", "cashAndCashEquivalents", "USD"),
    ("total_debt", "totalDebt", "USD"),
    ("net_debt", "netDebt", "USD"),
    ("total_assets", "totalAssets", "USD"),
    ("total_liabilities", "totalLiabilities", "USD"),
    ("total_equity", "totalStockholdersEquity", "USD"),
    ("goodwill", "goodwill", "USD"),
    ("intangible_assets", "intangibleAssets", "USD"),
    ("operating_lease_liabilities", "operatingLeaseLiabilities", "USD"),
]

CASH_FLOW_METRICS: list[MetricSpec] = [
    ("operating_cash_flow", "operatingCashFlow", "USD"),
    ("capital_expenditure", "capitalExpenditure", "USD"),
    # Signo de flujo de caja: negativo = el circulante absorbió caja.
    ("change_in_working_capital", "changeInWorkingCapital", "USD"),
    ("free_cash_flow", "freeCashFlow", "USD"),
    ("common_stock_repurchased", "commonStockRepurchased", "USD"),
    ("dividends_paid", "dividendsPaid", "USD"),
]

RATIO_METRICS: list[MetricSpec] = [
    ("gross_margin", "grossProfitMargin", "decimal"),
    ("operating_margin", "operatingProfitMargin", "decimal"),
    ("net_margin", "netProfitMargin", "decimal"),
    ("debt_to_equity", "debtEquityRatio", "decimal"),
    ("effective_tax_rate", "effectiveTaxRate", "decimal"),
]

# --- total_debt: definicion explicita (suma de componentes, un tag por componente) ---
# total_debt = deuda financiera con coste: prestamos y bonos + pagares + lineas de
# credito dispuestas + arrendamientos financieros + convertibles. NUNCA se suma
# mas de un tag por componente (alias), y los tags que ya incluyen a otros se
# usan en lugar de ellos, no ademas:
#   1. DebtLongtermAndShorttermCombinedAmount: total declarado por el emisor.
#      Gana solo; no se le suma nada.
#   2. Si no hay total declarado, deuda a plazo (un tag, por prioridad):
#        LongTermDebt (incluye vencimientos corrientes por definicion US-GAAP)
#        > LongTermDebtNoncurrent (+ LongTermDebtCurrent si consta el mismo cierre)
#        > LongTermDebtAndCapitalLeaseObligations (+ su Current): YA incluye los
#          arrendamientos financieros, asi que no se les suma FinanceLease*.
#      Con deuda a plazo presente se anaden SOLO las partidas que no estan
#      dentro de ella: prestamos corrientes (ShortTermBorrowings > CommercialPaper > LinesOfCreditCurrent)
#      y arrendamientos financieros (si el tag de plazo no los incluye).
#   3. Sin deuda a plazo, se suman los componentes sueltos, uno por componente:
#      convertibles, pagares, linea de credito (LT y corriente), vencimiento corriente,
#      prestamos corrientes y arrendamientos financieros. DebtInstrumentCarryingAmount
#      solo si no hay ninguna otra partida de deuda (es un hecho por instrumento).
#      Un arrendamiento financiero SOLO no cuenta como deuda: sin otra partida, no hay total_debt.
# Fail closed: sin ninguna partida en el cierre no hay total_debt (nunca 0 inventado).
TOTAL_DEBT_AGGREGATE = "DebtLongtermAndShorttermCombinedAmount"
TOTAL_DEBT_TERM_CHOICES: tuple[tuple[str, tuple[str, ...], bool], ...] = (
    ("LongTermDebt", (), False),
    ("LongTermDebtNoncurrent", ("LongTermDebtCurrent",), False),
    ("LongTermDebtAndCapitalLeaseObligations", ("LongTermDebtAndCapitalLeaseObligationsCurrent",), True),
)
TOTAL_DEBT_SHORT_CHOICES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ShortTermBorrowings", ()),
    ("CommercialPaper", ()),
    ("LinesOfCreditCurrent", ()),
)
TOTAL_DEBT_LEASE_CHOICES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("FinanceLeaseLiability", ()),
    ("FinanceLeaseLiabilityNoncurrent", ("FinanceLeaseLiabilityCurrent",)),
)
# Componentes sueltos (solo sin deuda a plazo): cada grupo aporta UN tag.
TOTAL_DEBT_LOOSE_GROUPS: tuple[tuple[tuple[str, tuple[str, ...]], ...], ...] = (
    (("ConvertibleDebt", ()), ("ConvertibleNotesPayable", ()),
     ("ConvertibleDebtNoncurrent", ("ConvertibleDebtCurrent",)),
     ("ConvertibleNotesPayableNoncurrent", ("ConvertibleNotesPayableCurrent",))),
    (("NotesPayable", ()), ("LongTermNotesPayable", ()),
     ("NotesPayableNoncurrent", ("NotesPayableCurrent",))),
    (("LongTermLineOfCredit", ()),),
    (("LongTermDebtCurrent", ()),),
    TOTAL_DEBT_SHORT_CHOICES,
    TOTAL_DEBT_LEASE_CHOICES,
)
TOTAL_DEBT_LAST_RESORT = "DebtInstrumentCarryingAmount"
TOTAL_DEBT_CONCEPTS: tuple[str, ...] = tuple(dict.fromkeys(
    [TOTAL_DEBT_AGGREGATE]
    + [t for t, _, _ in TOTAL_DEBT_TERM_CHOICES]
    + [t for _, extra, _ in TOTAL_DEBT_TERM_CHOICES for t in extra]
    + [t for g in (TOTAL_DEBT_SHORT_CHOICES, TOTAL_DEBT_LEASE_CHOICES, *TOTAL_DEBT_LOOSE_GROUPS)
       for t, extra in g for t in (t, *extra)]
    + [TOTAL_DEBT_LAST_RESORT]
))

SEC_METRIC_MAP: list[tuple[str, list[str], str]] = [
    ("revenue",           ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax", "RegulatedAndUnregulatedOperatingRevenue"],  "USD"),
    ("gross_profit",      ["GrossProfit"],                                                                          "USD"),
    ("operating_income",  ["OperatingIncomeLoss"],                                                                  "USD"),
    ("income_before_tax", ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest", "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments", "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomesticAndForeign"], "USD"),
    ("income_tax_expense", ["IncomeTaxExpenseBenefit"],                                                             "USD"),
    ("interest_expense",   ["InterestExpenseNonoperating", "InterestExpenseNonOperating", "InterestExpense", "InterestExpenseDebt", "InterestExpenseLongTermDebt", "InterestAndDebtExpense"],                                      "USD"),
    ("net_income",        ["NetIncomeLoss", "ProfitLoss"],                                                          "USD"),
    ("eps_diluted",       ["EarningsPerShareDiluted"],                                                              "USD/share"),
    # PROMEDIO ponderado de acciones (un denominador de duracion). El saldo
    # puntual CommonStockSharesOutstanding es otra magnitud (un instantaneo) y
    # vive en su propia metrica: mezclarlos hacia que el saldo ganara el
    # colapso de aliases por `filed` mas reciente y se publicara como divisor
    # del DCF (fix FIX5-8).
    ("shares_diluted",    ["WeightedAverageNumberOfDilutedSharesOutstanding"],                                      "shares"),
    ("shares_outstanding", ["CommonStockSharesOutstanding"],                                                         "shares"),
    # Fallback (WWW, 25/9): el tag combinado incluye caja
    # restringida -> deuda neta fresca pero algo optimista. Va el ULTIMO: por
    # periodo gana el `filed` mas reciente, y los periodos donde se uso quedan
    # anotados en document.metadata_["cash_includes_restricted_periods"].
    ("cash_and_equivalents", ["CashAndCashEquivalentsAtCarryingValue",
                              "CashCashEquivalentsAndShortTermInvestments",
                              "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"], "USD"),
    # Orden por alcance, NO por antiguedad: el tag combinado (largo + corto) es
    # el que representa "deuda total", y se coloco antes detras de
    # LongTermDebt, asi que la deuda neta salia sin la parte corriente. El
    # ganador lo decide el `filed` mas reciente del MISMO periodo, de modo que el
    # orden solo desempata cuando el emisor nunca presenta el tag combinado.
    ("total_debt",        list(TOTAL_DEBT_CONCEPTS), "USD"),
    # Annual health-screen inputs: keep current balances and noncurrent debt distinct.
    ("current_assets", ["AssetsCurrent"], "USD"),
    ("current_liabilities", ["LiabilitiesCurrent"], "USD"),
    ("long_term_debt", ["LongTermDebtNoncurrent"], "USD"),
    ("retained_earnings", ["RetainedEarningsAccumulatedDeficit"], "USD"),
    ("total_assets",      ["Assets"],                                                                               "USD"),
    ("total_liabilities", ["Liabilities"],                                                                          "USD"),
    # StockholdersEquity = patrimonio atribuible a la matriz; la variante
    # "IncludingPortionAttributableToNoncontrollingInterest" consolida los
    # intereses minoritarios. Son MAGNITUDES DISTINTAS: mezclarlas hacia que el
    # balance cuadre por la diferencia de NCI. Se usa la de la matriz.
    ("total_equity",      ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"], "USD"),
    ("goodwill",          ["Goodwill"],                                                                              "USD"),
    # Componentes del NOI de un REIT (net operating income = ingresos por
    # arrendamiento - gastos operativos de los inmuebles - impuestos sobre
    # inmuebles). El NOI no es un concepto us-gaap: se DERIVA en el modelo
    # fundamental a partir de estos tres hechos reportados (Camden FY2024:
    # 1.543,8 - 365,7 - 193,1 = 985,0 M$).
    ("lease_income",      ["OperatingLeaseLeaseIncome", "OperatingLeasesIncomeStatementLeaseRevenue"],            "USD"),
    ("property_operating_expense", ["DirectCostsOfLeasedAndRentedPropertyOrEquipment"],                            "USD"),
    ("real_estate_tax_expense", ["RealEstateTaxExpense"],                                                           "USD"),
    # Puente EV -> equity del DCF: patrimonio de minoritarios (NCI) y valor de
    # las preferentes. Saldos de balance (instantes).
    ("minority_interest", ["MinorityInterest"],                                                                     "USD"),
    ("preferred_stock",   ["PreferredStockValue", "PreferredStockValueOutstanding"],                               "USD"),
    ("intangible_assets", SEC_INTANGIBLE_COMPONENTS,                                                                "USD"),
    ("operating_lease_liabilities", ["OperatingLeaseLiability", "OperatingLeaseLiabilityNoncurrent"],                "USD"),
    ("operating_cash_flow", ["NetCashProvidedByUsedInOperatingActivities"],                                         "USD"),
    ("capital_expenditure", ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],          "USD"),
    # Leases financieros nuevos del periodo (adiciones de RoU): complemento del capex en
    # efectivo para flujos de inversión tipo hyperscalers (distinción cash capex vs leases).
    ("finance_lease_additions", ["RightOfUseAssetObtainedInExchangeForFinanceLeaseLiability"], "USD"),
    ("depreciation_amortization", ["DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet",
                                   "Depreciation", "DepreciationAndAmortization"],                                                                  "USD"),
    # Signo CONTRARIO al del flujo de caja (+ = el circulante sube y consume
    # caja): _merge_for_metric lo niega para guardar el signo de FMP
    # changeInWorkingCapital (ver SEC_CASH_FLOW_SIGN_FLIPPED_METRICS).
    ("change_in_working_capital", ["IncreaseDecreaseInOperatingCapital"], "USD"),
    ("common_stock_repurchased", ["PaymentsForRepurchaseOfCommonStock", "StockRepurchasedDuringPeriodValue"], "USD"),
    ("common_stock_issued", ["ProceedsFromIssuanceOfCommonStock", "StockIssuedDuringPeriodValueNewIssues"], "USD"),
    ("shares_repurchased", ["StockRepurchasedDuringPeriodShares"], "shares"),
    ("stock_based_compensation", ["ShareBasedCompensation"], "USD"),
    ("dividends_paid",    ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"],                                "USD"),
    # Drivers obligatorios de los marcos de tesis que SI estan en us-gaap y no
    # se leian (la tesis los daba por ausentes con el dato en el 10-K):
    # - aseguradoras: primas devengadas netas (Chubb FY2025: 53.014 M$);
    # - espacio/defensa: cartera contratada = obligaciones de desempeno
    #   pendientes (ASC 606), que es la cifra que Rocket Lab publica como
    #   «backlog» (FY2025: 1.847,3 M$). Es un saldo (instantaneo).
    ("earned_premiums",   ["PremiumsEarnedNet"],                                                                    "USD"),
    ("backlog",           ["RevenueRemainingPerformanceObligation"],                                                "USD"),
]


# IFRS (ESEF) -> metricas internas. Mismo contrato que SEC con una diferencia
# que importa: aqui los snapshots no llevan fecha de presentacion, asi que no
# hay nada honesto con lo que ordenar dos tags y gana el primero declarado. Los
# tags que NO son alias sino partes disjuntas de un total (capex desagregado)
# se suman, y un total yaAgglomerado nunca se suma con sus propias partes; ver
# ESEF_PART_CONCEPTS y ESEF_SUPERSET_CONCEPTS. Solo conceptos verificados en
# los snapshots reales de los 6 emisores reviewed (24-25/9); ampliado 25/9 con
# componentes de deuda verificados en 105 emisores (27+ con
# CurrentFinancialLiabilities). Hueco honesto: shares_diluted (ninguno de los 6
# reviewed trae WeightedAverageNumberOfShares en base scope). EBITDA no es tag
# IFRS estandar: se deriva como operating_income + D&A en _derive_esef_metrics
# (no aplica a bancos sin beneficio operativo, p.ej. SAN).
# Emisores extranjeros que presentan a la SEC en IFRS (40-F canadienses como
# Brookfield BN, 20-F en IFRS): companyfacts trae SOLO la taxonomia
# ``ifrs-full`` y la lectura us-gaap los dejaba con 0 hechos y la tesis
# «sin datos suficientes» (27/10/2026). Misma estructura que SEC_METRIC_MAP
# y mismas reglas de admision (ancla de filing, 300-380 dias, fp=FY); solo
# cambian los conceptos. Se usa unicamente si el filer no trae us-gaap.
# Semantica alineada con us-gaap: beneficio y patrimonio ATRIBUIBLES a la
# dominante (NetIncomeLoss/StockholdersEquity), nunca el total con
# minoritarios (ProfitLoss/Equity), que en un holding como BN es ~2,5x.
SEC_IFRS_METRIC_MAP: list[tuple[str, list[str], str]] = [
    ("revenue",           ["Revenue", "RevenueFromContractsWithCustomers"],                            "USD"),
    ("gross_profit",      ["GrossProfit"],                                                             "USD"),
    ("operating_income",  ["ProfitLossFromOperatingActivities"],                                       "USD"),
    ("income_before_tax", ["ProfitLossBeforeTax"],                                                     "USD"),
    ("income_tax_expense", ["IncomeTaxExpenseContinuingOperations"],                                   "USD"),
    ("interest_expense",  ["InterestExpense", "FinanceCosts"],                                         "USD"),
    ("net_income",        ["ProfitLossAttributableToOwnersOfParent"],                                  "USD"),
    ("eps_diluted",       ["DilutedEarningsLossPerShare"],                                             "USD/share"),
    # IAS 33: AdjustedWeightedAverageShares = media ponderada DILUIDA.
    ("shares_diluted",    ["AdjustedWeightedAverageShares"],                                           "shares"),
    ("total_assets",      ["Assets"],                                                                  "USD"),
    ("total_liabilities", ["Liabilities"],                                                             "USD"),
    ("total_equity",      ["EquityAttributableToOwnersOfParent"],                                      "USD"),
    ("cash_and_equivalents", ["CashAndCashEquivalents"],                                               "USD"),
    ("operating_cash_flow", ["CashFlowsFromUsedInOperatingActivities"],                                "USD"),
    ("capital_expenditure", ["PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"],    "USD"),
    ("depreciation_amortization", ["DepreciationAndAmortisationExpense"],                              "USD"),
    ("dividends_paid",    ["DividendsPaidClassifiedAsFinancingActivities", "DividendsPaid"],          "USD"),
]


ESEF_METRIC_MAP: list[tuple[str, list[str], str]] = [
    ("revenue",           ["ifrs-full:Revenue", "ifrs-full:RevenueFromInterest"],                        "iso4217:EUR"),
    ("net_income",        ["ifrs-full:ProfitLoss"],                                                      "iso4217:EUR"),
    ("operating_income",  ["ifrs-full:ProfitLossFromOperatingActivities"],                               "iso4217:EUR"),
    ("gross_profit",      ["ifrs-full:GrossProfit"],                                                     "iso4217:EUR"),
    ("income_before_tax", ["ifrs-full:ProfitLossBeforeTax"],                                             "iso4217:EUR"),
    ("income_tax_expense", ["ifrs-full:IncomeTaxExpenseContinuingOperations"],                           "iso4217:EUR"),
    ("interest_expense",  ["ifrs-full:InterestExpense", "ifrs-full:FinanceCosts"],                       "iso4217:EUR"),
    ("depreciation_amortization", ["ifrs-full:DepreciationAndAmortisationExpense",
                                   "ifrs-full:AdjustmentsForDepreciationAndAmortisationExpense"],        "iso4217:EUR"),
    ("eps_diluted",       ["ifrs-full:DilutedEarningsLossPerShare", "ifrs-full:BasicEarningsLossPerShare"], "iso4217:EUR/xbrli:shares"),
    ("total_assets",      ["ifrs-full:Assets"],                                                          "iso4217:EUR"),
    ("total_liabilities", ["ifrs-full:Liabilities"],                                                     "iso4217:EUR"),
    ("total_equity",      ["ifrs-full:EquityAttributableToOwnersOfParent", "ifrs-full:Equity"],          "iso4217:EUR"),
    ("cash_and_equivalents", ["ifrs-full:CashAndCashEquivalents"],                                       "iso4217:EUR"),
    # Componentes de deuda financiera (no alias: partes disjuntas del pasivo
    # financiero). total_debt se DERIVE como suma declarada en _derive_esef_metrics.
    ("financial_liabilities_current", ["ifrs-full:CurrentFinancialLiabilities"],                          "iso4217:EUR"),
    ("financial_liabilities_noncurrent", ["ifrs-full:NoncurrentFinancialLiabilities"],                    "iso4217:EUR"),
    ("lease_liabilities_current", ["ifrs-full:CurrentLeaseLiabilities"],                                  "iso4217:EUR"),
    ("lease_liabilities_noncurrent", ["ifrs-full:NoncurrentLeaseLiabilities"],                            "iso4217:EUR"),
    ("operating_cash_flow", ["ifrs-full:CashFlowsFromUsedInOperatingActivities"],                        "iso4217:EUR"),
    ("capital_expenditure", ["ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
                             "ifrs-full:PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities",
                             # Concepto combinado estandar IFRS (PP&E + intangibles + otras no
                             # corrientes): lo usan emisores que no desagregan el capex, p.ej. REP.
                             "ifrs-full:PurchaseOfPropertyPlantAndEquipmentIntangibleAssetsOtherThanGoodwillInvestmentPropertyAndOtherNoncurrentAssets"],
                                                                                                        "iso4217:EUR"),
    ("dividends_paid",    ["ifrs-full:DividendsPaidClassifiedAsFinancingActivities"],                    "iso4217:EUR"),
]



_NAME_STOPWORDS = frozenset({
    "INC", "SA", "S.A", "NV", "N.V", "PLC", "COMPANY", "GROUP", "THE", "DE",
    "LA", "EL", "Y", "S", "A", "HOLDING", "HOLDINGS", "CORP", "CORPORATION",
    "LTD", "LIMITED", "PUBLIC", "SOCIEDAD", "ANONIMA", "AKTIENGESELLSCHAFT",
    "AG", "SE", "SPA", "S.P.A", "OYS", "AB", "ASA", "BV", "B.V", "(OTC)",
})


def _name_tokens(name: str | None) -> set[str]:
    """Tokens significativos de un nombre legal: mayusculas, SIN ACENTOS (la
    Company puede decir «Telefónica» y el filing «TELEFONICA SA»: sin plegar
    diacriticos la guardia bloquearia una identidad legitima), sin signos ni
    formas societarias (SA/NV/PLC/Inc...)."""
    import unicodedata

    if not name:
        return set()
    raw = "".join(
        c for c in unicodedata.normalize("NFKD", str(name).upper())
        if not unicodedata.combining(c)
    )
    for ch in ".,()/&-":
        raw = raw.replace(ch, " ")
    return {w for w in raw.split() if len(w) > 2 and w not in _NAME_STOPWORDS}


def _name_identity_ok(company_name: str | None, candidate_name: str | None) -> bool:
    """Prueba de identidad por nombre entre la Company y un nombre del emisor.

    Pasa si comparten >=2 tokens significativos, o si TODOS los tokens de la
    Company estan contenidos en el candidato (nombre corto legitimo:
    «Telefónica» dentro de «TELEFONICA SA», «Kerry Group plc» dentro de
    «KERRY GROUP PLC»). Un solo token compartido con tokens sueltos a ambos
    lados NO basta: «Kerry Logistics Network» comparte «KERRY» con
    «KERRY GROUP PLC» y es otra empresa (objecion del auditor, 2026-10-19).
    Sin tokens en alguno de los dos lados no hay prueba: mismatch."""
    a, b = _name_tokens(company_name), _name_tokens(candidate_name)
    if not a or not b:
        return False
    return len(a & b) >= 2 or a <= b

# ESEF: concepts that are disjoint PARTS of one total. A filer that discloses
# capex disaggregated reports PP&E and intangibles separately, and taking the
# first alias that reports leaves half the capex out: FCF that is too high and a
# DCF that is too generous. These are added up per period.
ESEF_PART_CONCEPTS: dict[str, list[str]] = {
    "capital_expenditure": [
        "ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
        "ifrs-full:PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities",
    ],
}
# ESEF: concepts that ALREADY include the parts above. Summing a total with its
# own components is the double count this table prevents: a filer that tags the
# combined concept (REP) is taken at its word, and only filers that disclose
# the parts get them added up.
ESEF_SUPERSET_CONCEPTS: dict[str, list[str]] = {
    "capital_expenditure": [
        "ifrs-full:PurchaseOfPropertyPlantAndEquipmentIntangibleAssetsOtherThanGoodwill"
        "InvestmentPropertyAndOtherNoncurrentAssets",
    ],
}

# Metricas que la via FMP combina entre si (FCF = OCF + capex, margen = FCF /
# revenue, net debt = deuda - caja). Se indexan por (metrica, fiscal_year) en
# una sola lectura: cada par se resuelve dentro de SU ano, nunca tomando el
# "ultimo" de cada metrica por separado.
DERIVED_PAIR_METRICS: tuple[str, ...] = (
    "revenue",
    "operating_cash_flow",
    "capital_expenditure",
    "free_cash_flow",
    "fcf_margin",
    "total_debt",
    "cash_and_equivalents",
    "net_debt",
    "revenue_growth",
)


def is_summed_component(metric: str) -> bool:
    """True when a metric's concepts are disjoint PARTS of one total."""
    return metric in SUMMED_COMPONENT_METRICS


def _collapse_aliases(
    by_concept: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    """One winner per period across concepts that are ALIASES of each other.

    Many filers migrate from one tag to another and freeze the old one in the
    past, so the same period arrives under two concepts. That is one fact
    reported twice, and the most recent ``filed`` is its current presentation
    (a recast included). These concepts are alternatives, never added up.
    """
    by_end: dict[str, dict[str, Any]] = {}
    for entries in by_concept.values():
        for entry in entries.values():
            end = str(entry.get("end") or "")
            current = by_end.get(end)
            if current is None or str(entry.get("filed") or "") > str(
                current.get("filed") or ""
            ):
                by_end[end] = entry
    return by_end


def _sum_disjoint_components(
    by_concept: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    """Add up per-period values of concepts that are parts of the same total.

    Takes the concepts APART on purpose. The previous shape was a flat
    ``{end: entry}`` map, which had already collapsed the parts of a period
    into a single winner before this function ever saw them, so a total like
    intangible assets stored whichever component was filed last and quietly
    dropped the other: the metric changed meaning between years and no amount
    of summing downstream could recover it.

    The merged row keeps the most recent ``filed`` for provenance and records
    every contributing concept in ``_components``, so the total stays auditable
    back to its parts instead of becoming an opaque number.
    """
    totals: dict[str, dict[str, Any]] = {}
    for concept, entries in by_concept.items():
        for end, entry in entries.items():
            value = _decimal(entry.get("val"))
            if value is None:
                continue
            bucket = totals.setdefault(
                end,
                {
                    "val": Decimal("0"),
                    "filed": "",
                    "end": end,
                    "_components": {},
                    "_latest": entry,
                },
            )
            bucket["val"] = bucket["val"] + value
            bucket["_components"][concept] = str(value)
            filed = str(entry.get("filed") or "")
            if filed > str(bucket["filed"]):
                bucket["filed"] = filed
                # The label of the merged row (`fp`, `accn`, `form`) comes from
                # the newest filing of the period, not from whichever part was
                # summed first.
                bucket["_latest"] = entry
    for key, bucket in list(totals.items()):
        latest = bucket.pop("_latest")
        merged = {**latest, **bucket}
        if len(merged["_components"]) == 1:
            merged["_concept"] = next(iter(merged["_components"]))
        else:
            merged["_concept"] = "+".join(sorted(merged["_components"]))
        merged["val"] = float(merged["val"])
        totals[key] = merged
    return totals


# Metrics whose concepts are NOT interchangeable aliases: each tag covers a
# different scope (combined short+long debt vs long-term only). For these the
# declared order is the scope priority, and `filed` only breaks ties inside one
# concept (a recast), never across concepts.
SCOPE_PRIORITY_METRICS = {"total_debt"}

# Tags us-gaap de deuda financiera (lado PASIVO) usados como evidencia para la
# derivada "net_debt = -caja" (EXEL, 19/10/2026): solo si NINGUNO tiene valor
# en los ultimos 5 ejercicios la ausencia de total_debt es probatoria ("sin
# deuda financiera reportada"). Si alguno tiene valor reciente (mapeado o no,
# p.ej. ShortTermBorrowings o convertibles fuera del alcance de total_debt),
# la ausencia es un posible hueco de mapeo y la deuda neta queda N/D (regla
# del auditor). Lista cerrada y deliberadamente SIN los tags de deuda como
# ACTIVO (DebtSecurities*, AvailableForSaleDebtSecurities*,
# PaymentsToAcquire*Debt, ProceedsFromSaleOf*Debt): son inversiones, no
# pasivo, y falsearian a emisores como EXEL que si los reportan. Verificado
# contra el companyfacts real de EXEL: su ultimo tag de pasivo es
# FinanceLeaseLiability* (2019-09-27) y su ultimo flujo de deuda
# RepaymentsOfLongTermDebt (2020-01-03), ambos fuera de la ventana.
DEBT_SIGNAL_CONCEPTS: frozenset[str] = frozenset({
    # alcance actual de total_debt (si estan recientes, total_debt existe y
    # esta via no se usa; se incluyen por fail-closed)
    "DebtLongtermAndShorttermCombinedAmount", "LongTermDebt",
    "LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations",
    # saldos NO mapeados
    "LongTermDebtCurrent", "ShortTermBorrowings",
    "ConvertibleDebt", "ConvertibleDebtCurrent", "ConvertibleDebtNoncurrent",
    "ConvertibleNotesPayable", "ConvertibleNotesPayableCurrent",
    "ConvertibleNotesPayableNoncurrent",
    "NotesPayable", "NotesPayableCurrent", "NotesPayableNoncurrent",
    "LongTermNotesPayable", "LineOfCreditFacilityAmountOutstanding",
    "FinanceLeaseLiability", "FinanceLeaseLiabilityCurrent",
    "FinanceLeaseLiabilityNoncurrent",
    "CommercialPaper", "SecuredDebt", "UnsecuredDebt",
    "DebtInstrumentCarryingAmount", "BankOverdrafts",
    # flujos del periodo: no son saldo a la fecha, pero una emision o
    # amortizacion reciente es evidencia de que HUBO deuda cerca (prudencia)
    "RepaymentsOfDebt", "RepaymentsOfLongTermDebt", "RepaymentsOfConvertibleDebt",
    "RepaymentsOfShortTermDebt", "RepaymentsOfLinesOfCredit",
    "ProceedsFromIssuanceOfDebt", "ProceedsFromIssuanceOfLongTermDebt",
    "ProceedsFromShortTermDebt", "ProceedsFromConvertibleDebt",
    "ProceedsFromLinesOfCredit", "PaymentsOfDebtIssuanceCosts",
    # ifrs-full (40-F/20-F en IFRS, p. ej. BN): prestamos y su flujo. Sin
    # ellos un filer IFRS con deuda salia con deuda neta = -caja.
    "Borrowings", "LongtermBorrowings", "ShorttermBorrowings",
    "CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings",
    "NoncurrentPortionOfNoncurrentBorrowings",
    "ProceedsFromBorrowingsClassifiedAsFinancingActivities",
    "RepaymentsOfBorrowingsClassifiedAsFinancingActivities",
})

# Ventana de evidencia (regla del auditor: "ultimos N ejercicios"): 5 anos
# anclados al ejercicio anual mas reciente de ESTA ingesta (nivel emisor, no
# por ano, para que la serie derivada sea consistente).
DEBT_SIGNAL_MAX_AGE_DAYS = 365 * 5


def _latest_debt_signal_end(us_gaap: dict[str, Any]) -> date | None:
    """Fecha (end) mas reciente con valor en cualquier tag de DEBT_SIGNAL_CONCEPTS.

    Escaneo bruto del companyfacts (sin filtro de forma/fp/unidad): cualquier
    valor reportado cuenta como evidencia de deuda financiera viva o reciente.
    """
    latest: date | None = None
    for concept in DEBT_SIGNAL_CONCEPTS:
        units = (us_gaap.get(concept) or {}).get("units") or {}
        for entries in units.values():
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                try:
                    end = date.fromisoformat(str(entry.get("end") or "")[:10])
                except ValueError:
                    continue
                if latest is None or end > latest:
                    latest = end
    return latest


def _collapse_by_scope(
    by_concept: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    """Per period, take the first concept in declared (widest-scope-first) order."""
    by_end: dict[str, dict[str, Any]] = {}
    for entries in by_concept.values():
        for end, entry in entries.items():
            by_end.setdefault(end, entry)
    return by_end


def _compose_total_debt(
    by_concept: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    """total_debt por cierre segun la definicion explicita (ver TOTAL_DEBT_*)."""
    ends: set[str] = set()
    for entries in by_concept.values():
        ends.update(entries)

    def pick(
        choices: tuple[tuple[str, tuple[str, ...]], ...], end: str
    ) -> list[tuple[str, dict[str, Any]]]:
        for tag, extras in choices:
            entry = by_concept.get(tag, {}).get(end)
            if entry is None or _decimal(entry.get("val")) is None:
                continue
            parts = [(tag, entry)]
            for extra in extras:
                other = by_concept.get(extra, {}).get(end)
                if other is not None and _decimal(other.get("val")) is not None:
                    parts.append((extra, other))
            return parts
        return []

    out: dict[str, dict[str, Any]] = {}
    for end in ends:
        parts: list[tuple[str, dict[str, Any]]] = []
        aggregate = by_concept.get(TOTAL_DEBT_AGGREGATE, {}).get(end)
        if aggregate is not None and _decimal(aggregate.get("val")) is not None:
            parts = [(TOTAL_DEBT_AGGREGATE, aggregate)]
        else:
            term: list[tuple[str, dict[str, Any]]] = []
            leases_in = False
            for tag, extras, includes_leases in TOTAL_DEBT_TERM_CHOICES:
                term = pick(((tag, extras),), end)
                if term:
                    leases_in = includes_leases
                    break
            if term:
                parts = term + pick(TOTAL_DEBT_SHORT_CHOICES, end)
                if not leases_in:
                    parts += pick(TOTAL_DEBT_LEASE_CHOICES, end)
            else:
                for group in TOTAL_DEBT_LOOSE_GROUPS:
                    parts += pick(group, end)
                # Un arrendamiento financiero solo NO es la deuda de la
                # empresa (p.ej. F: 0,9 mil M frente a la deuda real de
                # Ford Credit): sin ninguna partida de deuda financiera no
                # se publica total_debt.
                lease_tags = {t for t, _ in TOTAL_DEBT_LEASE_CHOICES} | {
                    x for _, extra in TOTAL_DEBT_LEASE_CHOICES for x in extra
                }
                if not any(tag not in lease_tags for tag, _ in parts):
                    parts = pick(((TOTAL_DEBT_LAST_RESORT, ()),), end)
        if not parts:
            continue
        total = sum((cast(Decimal, _decimal(e["val"])) for _, e in parts), Decimal("0"))
        latest = max((e for _, e in parts), key=lambda e: str(e.get("filed") or ""))
        components = {tag: str(_decimal(e["val"])) for tag, e in parts}
        out[end] = {
            **latest,
            "val": float(total),
            "_concept": "+".join(sorted(components)),
            "_components": components,
        }
    return out


# Métricas cuyo concepto us-gaap llega con el signo contrario al del estado de
# flujos de caja. IncreaseDecreaseInOperatingCapital es + cuando el circulante
# operativo SUBE (caja consumida); el hecho se guarda en el signo de FMP
# changeInWorkingCapital (− = caja consumida), que es el que usan el
# beneficio del propietario (app/services/owner_earnings.py) y el FCFE.
SEC_CASH_FLOW_SIGN_FLIPPED_METRICS: frozenset[str] = frozenset({"change_in_working_capital"})


def _merge_for_metric(
    by_concept: dict[str, dict[str, dict[str, Any]]], metric: str
) -> dict[str, dict[str, Any]]:
    """Merge concepts per period: summed when they are parts, else one winner."""
    if metric in SEC_CASH_FLOW_SIGN_FLIPPED_METRICS:
        return {
            end: _negate_entry(entry)
            for end, entry in _collapse_aliases(by_concept).items()
        }
    if is_summed_component(metric):
        return _sum_disjoint_components(by_concept)
    if metric == "total_debt":
        return _compose_total_debt(by_concept)
    if metric in SCOPE_PRIORITY_METRICS:
        return _collapse_by_scope(by_concept)
    return _collapse_aliases(by_concept)


def _negate_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Copia de la entrada con ``val`` cambiado de signo (el crudo no se toca)."""
    value = _decimal(entry.get("val"))
    if value is None:
        return entry
    return {**entry, "val": -value}


BANK_REVENUE_COMPONENTS = ("InterestIncomeExpenseNet", "NoninterestIncome")
BANK_REVENUE_CONCEPT = "InterestIncomeExpenseNet+NoninterestIncome"
# Emisores verificados de la decision de bancos (29/9) cuyo industry en el
# maestro no contiene "bank": MS = "Financial Services" (dato de prod).
BANK_REVENUE_TICKERS = {"BPOP", "MS", "WFC"}


def _compose_bank_revenue(
    us_gaap: dict[str, Any],
    *,
    forms: set[str],
    periods: set[str],
    min_span: int | None,
    max_span: int | None,
    annual_anchors: dict[str, str] | None = None,
    as_of: date | None = None,
) -> dict[str, dict[str, Any]]:
    """Revenue compuesto para bancos: intereses netos + ingresos no financieros.

    Los bancos (WFC, MS, BPOP...) no reportan un tag de revenue agregado: sus
    ingresos son la suma de ambos componentes (el "total net revenue" de sus
    10-K). Solo entra un periodo con AMBOS componentes presentes (fail
    closed: un componente ausente NO se imputa a cero - un subtotal parcial
    nunca se publica como revenue). El caller solo rellena periodos donde el
    merge de aliases no encontro nada: un tag agregado real siempre gana.
    La proveniencia viaja en `_concept` (se registra en
    xbrl_concept_by_metric_period como el resto de conceptos).
    """
    parts = _collect_by_concept(
        us_gaap,
        list(BANK_REVENUE_COMPONENTS),
        "USD",
        forms=forms,
        periods=periods,
        min_span=min_span,
        max_span=max_span,
        annual_anchors=annual_anchors,
        as_of=as_of,
    )
    interest = parts.get("InterestIncomeExpenseNet", {})
    noninterest = parts.get("NoninterestIncome", {})
    composed: dict[str, dict[str, Any]] = {}
    for end, interest_entry in interest.items():
        noninterest_entry = noninterest.get(end)
        if noninterest_entry is None:
            continue
        interest_val = _decimal(interest_entry.get("val"))
        noninterest_val = _decimal(noninterest_entry.get("val"))
        if interest_val is None or noninterest_val is None:
            continue
        composed[end] = {
            **interest_entry,
            "val": float(interest_val + noninterest_val),
            "_concept": BANK_REVENUE_CONCEPT,
        }
    return composed


# Tags de revenue por contrato que en un banco son un SUBTOTAL de comisiones
# (una parte de NoninterestIncome), nunca el total.
BANK_REVENUE_SUBTOTAL_TAGS = frozenset({
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
})


def _revenue_concepts_for(concepts: list[str], bank_like: bool) -> list[str]:
    """Candidatos a revenue de un emisor.

    En bancos los subtotales de comisiones salen ANTES de la recoleccion y
    el colapso de aliases: si se filtraran despues, un subtotal presentado
    mas tarde que un agregado real del mismo periodo ganaria el colapso por
    `filed` y el agregado se perderia. Fuera de bancos el tag de contrato
    ES el revenue total y no se toca nada.
    """
    if not bank_like:
        return concepts
    return [c for c in concepts if c not in BANK_REVENUE_SUBTOTAL_TAGS]


def _is_bank_like(company: Any) -> bool:
    """Gate verificable de la composicion de revenue bancario.

    InterestIncomeExpenseNet + NoninterestIncome ES la definicion de
    ingresos ("total net revenue") solo para bancos/financieras; en un
    industrial esos tags serian un subtotal enganoso publicado como
    revenue. Se decide con el sector/industry del maestro de companias.
    """
    industry = str(getattr(company, "industry", "") or "").strip().lower()
    if any(k in industry for k in ("bank", "thrift", "savings", "capital markets")):
        return True
    # Lista verificada: los 3 bancos de la decision cuyo maestro no dice
    # "bank" en industry (MS figura como "Financial Services" en prod).
    return (
        str(getattr(company, "ticker", "") or "").strip().upper()
        in BANK_REVENUE_TICKERS
    )


def _quarters_from_ytd(
    by_end_q: dict[str, dict[str, Any]],
    ytd_by_end: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Trimestres de 3 meses derivados de acumulados YTD de 10-Q.

    Solo devuelve cierres que NO estan ya en ``by_end_q`` (un trimestre
    presentado gana). La fila derivada hereda accn/filed/concepto del
    acumulado mas reciente (el filing que la hace conocible) y lleva
    ``_derived_from_ytd`` para persistirse como no reportada.
    """
    rows: list[PeriodValue] = []
    for entry in [*by_end_q.values(), *ytd_by_end.values()]:
        val = _decimal(entry.get("val"))
        try:
            start = date.fromisoformat(str(entry.get("start")))
            end = date.fromisoformat(str(entry.get("end")))
        except (TypeError, ValueError):
            continue
        if val is None:
            continue
        rows.append(PeriodValue(start=start, end=end, value=val))
    derived: dict[str, dict[str, Any]] = {}
    for quarter in derive_quarters_from_ytd(rows):
        end = quarter.end.isoformat()
        source = ytd_by_end.get(end)
        if quarter.reported or end in by_end_q or source is None or quarter.start is None:
            continue
        derived[end] = {
            **source,
            "val": quarter.value,
            "start": quarter.start.isoformat(),
            "_derived_from_ytd": True,
        }
    return derived


def _collect_by_concept(
    us_gaap: dict[str, Any],
    concepts: list[str],
    unit_key: str,
    *,
    forms: set[str],
    periods: set[str],
    min_span: int | None,
    max_span: int | None,
    annual_anchors: dict[str, str] | None = None,
    as_of: date | None = None,
    require_start: bool = False,
) -> dict[str, dict[str, dict[str, Any]]]:
    """Newest ``filed`` fact per concept and period, before any merging.

    Keeping the concepts apart until the caller knows what they are (aliases or
    disjoint parts) is what lets `_collapse_aliases` and
    `_sum_disjoint_components` disagree on purpose instead of by accident.

    ``as_of`` is an information cut-off, not a fiscal filter: an entry whose
    ``filed`` date is after it was not public on that date and must not enter
    (FIX5-1). Without a cut-off nothing is date-filtered and the caller says so
    in the result.

    ``require_start`` keeps only flow facts: a duration metric like
    ``shares_diluted`` (a weighted average) reported as an instant is a
    different magnitude and must not enter as one (FIX5-8).
    """
    by_concept: dict[str, dict[str, dict[str, Any]]] = {}
    for concept in concepts:
        entries = us_gaap.get(concept, {}).get("units", {}).get(unit_key, [])
        for entry in entries:
            if entry.get("form") not in forms or entry.get("fp") not in periods:
                continue
            if as_of is not None and not _published_by(entry, as_of):
                continue
            if require_start and not entry.get("start"):
                continue
            # A flow fact (one WITH `start`) has to really span the period it
            # claims: `fp="FY"` does not guarantee an annual duration, and the
            # year-to-date and TTM variants clear a duration check too. Instant
            # facts (balance sheet, no `start`) are not duration-filtered.
            # An annual fact - flow OR instant - only enters anchored to its
            # own annual filing (F353): the entry's `accn` must resolve to a
            # 10-K (o variante) in submissions AND close on the same month
            # that filing declares on its cover. A TTM row inside a 10-K
            # fails the month check even though its accn is valid; a
            # coherent TTM series cannot move the anchor because the anchor
            # is a declared cover date, not a mode over facts. Fail closed
            # for every annual row: without a linkable anchor, no annual
            # fact enters (instant facts skip the duration check below, so
            # the anchor check must live outside it).
            if annual_anchors is not None:
                accn = str(entry.get("accn") or "")
                report_date = annual_anchors.get(accn)
                if not report_date:
                    continue
                entry_month = _normalized_fiscal_month(str(entry.get("end") or ""))
                if entry_month is None or entry_month != _normalized_fiscal_month(report_date):
                    continue
            start = entry.get("start")
            if start and min_span is not None and max_span is not None:
                # A flow fact (one WITH `start`) has to really span the
                # period it claims; instant facts have no duration to check.
                try:
                    span = (
                        date.fromisoformat(str(entry["end"]))
                        - date.fromisoformat(str(start))
                    ).days
                except (KeyError, TypeError, ValueError):
                    continue
                if not min_span <= span <= max_span:
                    continue
            end = str(entry.get("end") or "")
            if not end:
                continue
            concept_entries = by_concept.setdefault(concept, {})
            current = concept_entries.get(end)
            if current is None or str(entry.get("filed") or "") > str(
                current.get("filed") or ""
            ):
                concept_entries[end] = {**entry, "_concept": concept}
    return by_concept


def _esef_period(entry: dict[str, Any]) -> str | None:
    """The period an ESEF fact belongs to, or None when it is not usable.

    A per-member breakdown is not the consolidated figure, and a flow fact
    only counts when it really spans the fiscal year it claims.
    """
    if entry.get("dims"):
        return None
    if "end" in entry and "start" in entry:
        try:
            span = (
                date.fromisoformat(str(entry["end"]))
                - date.fromisoformat(str(entry["start"]))
            ).days
        except (TypeError, ValueError):
            return None
        if not 300 <= span <= 380:
            return None
        return str(entry["end"])
    if "instant" in entry:
        return str(entry["instant"])
    return None


def _merge_esef_periods(
    facts_data: dict[str, Any], concepts: list[str], unit: str, metric: str
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """One value per period for an ESEF metric, plus an explicit coverage record.

    A filer that disaggregates a total into disjoint parts has them added up, a
    filer that tags the combined total is taken at its word, and everything
    else keeps the first concept that reports the period: ESEF snapshots carry
    no filing date, so there is nothing honest to rank two aliases with beyond
    the order the concepts are declared in.

    Two failure modes of the sum are refused rather than published:

    * the same fact twice (same tag, same context, same value) used to be added
      twice - two snapshots of one filing read as double the capex. Identical
      duplicates collapse to one fact; two DIFFERENT values for the same tag
      and period cannot be ranked without a filing date, so the period is
      ambiguous and is rejected (a disclosed total for the period still wins);
    * a part that is missing for the period used to vanish silently, and the
      subtotal was published as the complete metric. A missing part is only
      declared when its absence can be affirmed - the filer DOES report that
      concept, just not for this period; a part the filer never reports can be
      zero or not applicable, and the sum is taken as complete.

    Returns the merged periods and a coverage record with the rejected
    (ambiguous) and incomplete (partial) periods, so the caller can state what
    was NOT published instead of letting it pass for the whole magnitude.
    """
    superset = ESEF_SUPERSET_CONCEPTS.get(metric, [])
    parts = ESEF_PART_CONCEPTS.get(metric, [])
    by_period: dict[str, dict[str, Any]] = {}
    part_facts: dict[str, dict[str, set[Decimal]]] = {}
    concepts_with_data: set[str] = set()
    for concept in concepts:
        for entry in facts_data.get(concept, {}).get(unit, []):
            period = _esef_period(entry)
            if period is None:
                continue
            if concept in superset:
                by_period.setdefault(period, entry)
            elif concept in parts:
                value = _decimal(entry.get("val"))
                if value is None:
                    continue
                concepts_with_data.add(concept)
                part_facts.setdefault(period, {}).setdefault(concept, set()).add(value)
            elif period not in by_period:
                by_period[period] = entry
    coverage: dict[str, Any] = {"ambiguous": {}, "partial": {}}
    for period, by_concept in part_facts.items():
        # A disclosed total always beats the sum of its parts: it is the only
        # statement of the whole magnitude, and it may include components the
        # parts do not itemise.
        if period in by_period:
            continue
        conflicts = {
            concept: sorted(str(value) for value in values)
            for concept, values in by_concept.items()
            if len(values) > 1
        }
        if conflicts:
            coverage["ambiguous"][period] = conflicts
            continue
        missing = sorted(concepts_with_data - set(by_concept))
        if missing:
            coverage["partial"][period] = missing
            continue
        by_period[period] = {
            "val": float(sum((next(iter(values)) for values in by_concept.values()), Decimal("0"))),
            "period": period,
            "_components": {
                concept: str(next(iter(values))) for concept, values in by_concept.items()
            },
        }
    return by_period, coverage


def _norm_symbol(value: object) -> str:
    """Normaliza la clase de acciones: BRK-B, BRK.B y BRK/B son el mismo emisor."""
    return re.sub(r"[.\-/ ]", "", str(value)).upper()


def _norm_date(value: Any) -> str | None:
    """Fecha ISO de un campo `date` (FMP): acepta ISO y epoch (segundos).

    FMP entrega el cierre del periodo como cadena ISO, pero hay filas (y
    snapshots) que lo entregan como epoch en segundos. Sin normalizar, la
    etiqueta de periodo salia `1767225600:FY` y ninguna puerta la reconocia
    como fecha. Un valor no parseable devuelve None: el caller decide si lo
    conserva tal cual para que la etiqueta siga inspeccionable.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    seconds: int | None = None
    if re.fullmatch(r"\d{9,12}(\.0+)?", text):
        seconds = int(float(text))
    elif re.fullmatch(r"\d{13}(\.0+)?", text):
        seconds = int(float(text)) // 1000
    if seconds is not None:
        try:
            return datetime.fromtimestamp(seconds, tz=UTC).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return None


def _published_by(entry: dict[str, Any], as_of: date) -> bool:
    """True cuando el hecho YA era publico en `as_of` (fecha de filing).

    Fail closed: sin `filed` (o con uno ilegible) no se puede probar la
    publicacion, y un hecho sin fecha de publicacion nunca entra bajo un corte.
    """
    filed = str(entry.get("filed") or "").strip()
    if not filed:
        return False
    try:
        return date.fromisoformat(filed[:10]) <= as_of
    except ValueError:
        return False


def _publication_date(entry: dict[str, Any]) -> date | None:
    """Fecha de publicacion declarada por la fuente (`filed`), o None."""
    filed = str(entry.get("filed") or "").strip()
    if not filed:
        return None
    try:
        return date.fromisoformat(filed[:10])
    except ValueError:
        return None


def _latest_known_filed(*facts: Any) -> date | None:
    """Fecha de filing de una derivada: la mas tardia de sus entradas.

    Si alguna entrada no tiene ``filed`` no se puede probar cuando fue publica
    la derivada: NULL (el lector aplica entonces su retraso conservador).
    """
    dates = [getattr(fact, "filed", None) for fact in facts]
    if not dates or any(d is None for d in dates):
        return None
    return max(dates)


def _period(row: dict[str, Any]) -> tuple[str, int | None, str | None]:
    fiscal_year = row.get("calendarYear") or row.get("fiscalYear")
    fiscal_quarter = row.get("period")
    raw_date = row.get("date")
    # Se normaliza lo normalizable (epoch -> ISO) y lo no parseable se
    # conserva VERBATIM: una fecha imposible como `2025-99-99` debe llegar a
    # la etiqueta para que la puerta no_lookahead la señale como defecto, no
    # esfumarse en un `unknown` que ninguna puerta sabria acusar (FIX5-10).
    date_value = _norm_date(raw_date) or (str(raw_date).strip() if raw_date is not None else None)

    year_int: int | None = None
    if fiscal_year is not None:
        try:
            year_int = int(fiscal_year)
        except (TypeError, ValueError):
            year_int = None

    if date_value and fiscal_quarter:
        return f"{date_value}:{fiscal_quarter}", year_int, str(fiscal_quarter)
    if year_int and fiscal_quarter:
        return f"{year_int}:{fiscal_quarter}", year_int, str(fiscal_quarter)
    if date_value:
        return str(date_value), year_int, None
    return "unknown", year_int, str(fiscal_quarter) if fiscal_quarter else None


def _rows(payload: list | dict) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        return [payload]
    return []


async def _free_data_snapshot(ticker: str, cik: str) -> dict[str, Any]:
    """Snapshot best-effort de filings EDGAR (10-K/10-Q) + macro FRED.

    Nunca lanza excepciones: cada fuente falla por separado y sin clave FRED
    el macro simplemente queda en None.
    """
    snapshot: dict[str, Any] = {
        "status": "ok",
        "recent_filings": [],
        "macro": None,
    }
    try:
        snapshot["recent_filings"] = await sec_edgar_connector.recent_filings(
            cik, forms=("10-K", "10-Q"), limit=5
        )
    except Exception as exc:
        snapshot["recent_filings"] = []
        snapshot["filings_error"] = redact_secrets(str(exc))[:200]
    try:
        snapshot["macro"] = await fred_connector.latest_observation("cpi")
    except Exception as exc:  # pragma: no cover - red defensiva
        snapshot["macro"] = None
        snapshot["macro_error"] = redact_secrets(str(exc))[:200]
    return snapshot



def _annual_fiscal_year(end: str, modal_fy_month: str | None) -> int:
    """Ano fiscal de un cierre anual SEC. Es el ano del ``end`` salvo en los
    ejercicios de 52/53 semanas que cierran la primera semana de enero
    (EXEL: 2025-01-03 es el FY2024, 2026-01-02 el FY2025): ahi el cierre cae
    en el ano siguiente y el dato iba etiquetado un ano de mas."""
    end_date = date.fromisoformat(str(end)[:10])
    year = end_date.year
    if end_date.month == 1 and end_date.day <= 7:
        try:
            modal = int(modal_fy_month) if modal_fy_month else None
        except (TypeError, ValueError):
            modal = None
        if modal in (None, 12, 1):
            year -= 1
    return year


def _fiscal_quarter_from_end(end: str, modal_fy_month: str | None) -> str | None:
    """Trimestre fiscal derivado del cierre del periodo contra el mes modal de
    cierre de ejercicio. El `fp` de companyfacts es el periodo fiscal DE LA
    PRESENTACION, no del dato: las comparativas trimestrales dentro de un 10-Q
    heredan el fp de ese 10-Q (caso real AAPL: dividendos pagados en abril o
    julio etiquetados Q1 porque la copia mas reciente salio en el 10-Q de Q1),
    asi que no sirve para etiquetar. Meses desde el cierre modal redondeados a
    trimestres: el propio mes de cierre (y su drift de 52/53 semanas, +-1 mes)
    es Q4; +3 meses es Q1; +6, Q2; +9, Q3. None sin ancla modal."""
    if not modal_fy_month:
        return None
    try:
        month = date.fromisoformat(str(end)).month
        modal = int(modal_fy_month)
    except (TypeError, ValueError):
        return None
    quarter = round(((month - modal) % 12) / 3)
    if quarter == 0:
        quarter = 4
    return f"Q{quarter}"

def _normalized_fiscal_month(end: str) -> str | None:
    """Mes de cierre fiscal normalizado: los ejercicios de 52/53 semanas que
    cierran en la primera semana de un mes pertenecen convencionalmente al mes
    anterior (VFC cierra el sabado mas cercano al 31 de marzo: 2023-04-01,
    2024-03-30, 2025-03-29 son todos "marzo"). Sin esa normalizacion el drift
    cruzando un cambio de mes parte la moda y deja fuera ejercicios validos.
    """
    try:
        d = date.fromisoformat(str(end))
    except (TypeError, ValueError):
        return None
    month = d.month - 1 if d.day <= 7 else d.month
    return f"{month or 12:02d}"


def _current_fiscal_month_from_anchors(anchors: dict[str, str]) -> str | None:
    """Mes vigente de cierre de ejercicio segun los ~5 filings anuales mas
    recientes (sus reportDate normalizados). Solo etiqueta trimestres; la
    admision anual va por ancla de filing por hecho, nunca por esta moda."""
    if not anchors:
        return None
    recent = sorted(anchors.values(), reverse=True)[:5]
    months = [m for m in (_normalized_fiscal_month(d) for d in recent) if m]
    if not months:
        return None
    return Counter(months).most_common(1)[0][0]


def _modal_fiscal_end_month(us_gaap: dict[str, Any]) -> str | None:
    """Fallback de etiquetado trimestral cuando no hay submissions: la
    admision anual NUNCA usa esta moda (es envenenable con ruido TTM;
    F353 la sustituyo por anclas de filing). Mes modal de cierre de
    ejercicio a partir de los hechos de flujo
    anuales candidatos (300-380 dias, fp=FY, 10-K/20-F). Los acumulados TTM de
    ~365 dias que cierran en fin de trimestre (caso real AA/AAL: revenue
    2019-04-01 -> 2020-03-31 etiquetado FY) pasan el filtro de duracion, pero
    su mes de cierre es minoritario frente al del ejercicio real.

    F353: la moda se computa sobre la VENTANA RECIENTE (ultimos ~5 anos de
    cierres anuales), no sobre toda la historia. Emisores que cambian de
    calendario fiscal (casos reales 28/09/2026: BRT Sep->Dec, ZWS Mar->Dec,
    CSR Abr->Dec, JEF Dic->Nov, CMP Dic->Sep, EYPT/MYGN/LHX Jun->Dic, FOR
    Dic->Sep, VFC Dic->Mar/Abr) quedaban congelados en el ano del cambio
    porque la historia vieja ganaba la moda y el filtro rechazaba los
    ejercicios nuevos. La ventana reciente adopta el calendario actual; la
    historia solo desempata, asi la proteccion anti-TTM de F28 sigue
    vigente (los TTM no cambian de mes: el ejercicio real reciente sigue
    ganando la moda). Mes normalizado (primeros 7 dias = mes anterior) para
    absorber el drift de 52/53 semanas cruzando cambio de mes.
    Devuelve None si no hay candidatos de flujo (emisor sin historia anual).
    """
    pairs = _fiscal_annual_pairs(us_gaap)
    if not pairs:
        return None
    return _recent_fiscal_mode(pairs)


def _fiscal_annual_pairs(us_gaap: dict[str, Any]) -> list[tuple[str, str]]:
    """Pares (mes normalizado, end) de todos los hechos de flujo anuales
    candidatos (300-380 dias, fp=FY, 10-K/20-F) sobre todo SEC_METRIC_MAP."""
    pairs: list[tuple[str, str]] = []
    reporting_currency = _sec_reporting_currency(us_gaap)
    for _metric, concepts, unit in SEC_METRIC_MAP:
        unit_keys = _sec_unit_keys(unit, reporting_currency)
        if unit_keys is None:
            continue
        unit, xbrl_unit_key = unit_keys
        for concept in concepts:
            entries = us_gaap.get(concept, {}).get("units", {}).get(xbrl_unit_key, [])
            for e in entries:
                if e.get("fp") != "FY" or e.get("form") not in {"10-K", "20-F"}:
                    continue
                start = e.get("start")
                if not start:
                    continue
                try:
                    span = (date.fromisoformat(str(e["end"])) - date.fromisoformat(str(start))).days
                except (TypeError, ValueError):
                    continue
                if not 300 <= span <= 380:
                    continue
                end = str(e.get("end") or "")
                if len(end) < 7:
                    continue
                month = _normalized_fiscal_month(end)
                if month is not None:
                    pairs.append((month, end))
    return pairs


def _recent_fiscal_mode(pairs: list[tuple[str, str]]) -> str:
    """Moda sobre la ventana reciente (ultimos ~5 anos de cierres); a empate,
    el mes con el cierre mas reciente (el calendario vigente)."""
    max_year = max(int(end[:4]) for _month, end in pairs)
    counts_recent: Counter[str] = Counter()
    latest_end: dict[str, str] = {}
    for month, end in pairs:
        if end > latest_end.get(month, ""):
            latest_end[month] = end
        if int(end[:4]) >= max_year - 5:
            counts_recent[month] += 1
    pool = counts_recent or Counter(m for m, _e in pairs)
    return max(pool, key=lambda m: (pool[m], latest_end.get(m, "")))



def _latest_filed_date(us_gaap: dict[str, Any]):
    """Fecha `filed` mas reciente de los hechos companyfacts, o None."""
    latest = None
    for concept in (us_gaap or {}).values():
        for entries in ((concept or {}).get("units") or {}).values():
            for entry in entries or []:
                raw = str((entry or {}).get("filed") or "")[:10]
                try:
                    parsed = date.fromisoformat(raw)
                except ValueError:
                    continue
                if latest is None or parsed > latest:
                    latest = parsed
    return latest


class FinancialIngestionService:
    """Normalize provider data into auditable financial facts."""

    async def refresh_from_fmp(
        self,
        db: Session,
        company: Company,
        client: FMPClient | None = None,
        # FMP free tier rejects limit>=6 on /stable statements with 402;
        # 5 periods is the deepest history the free key serves.
        limit: int = 5,
    ) -> dict[str, Any]:
        fmp = client or FMPClient()
        ticker = company.ticker.upper()

        income = _rows(await fmp.income_statement(ticker, limit=limit))
        balance = _rows(await fmp.balance_sheet(ticker, limit=limit))
        cash_flow = _rows(await fmp.cash_flow(ticker, limit=limit))
        ratios = _rows(await fmp.ratios(ticker, limit=limit))
        profile = _rows(await fmp.company_profile(ticker))

        document = self._source_document(db, company)
        self._replace_fmp_data(db, company, document)

        statements = 0
        facts = 0
        rows_rechazadas_por_symbol = 0
        filling_dates: list[date] = []
        seen_keys: set[tuple[str, str]] = set()
        for statement_type, rows, specs in [
            ("income", income, INCOME_METRICS),
            ("balance_sheet", balance, BALANCE_METRICS),
            ("cash_flow", cash_flow, CASH_FLOW_METRICS),
            ("ratios", ratios, RATIO_METRICS),
        ]:
            for row in rows:
                # Cada fila declara su emisor: una fila de OTRA sociedad en el
                # payload (el endpoint no siempre filtra) no puede atribuirse a
                # este ticker - contaminaria la serie y el crecimiento derivado
                # (FIX5-3). Una fila sin `symbol` no puede contradecirse y se
                # acepta como hasta ahora.
                if _norm_symbol(row.get("symbol") or ticker) != _norm_symbol(ticker):
                    rows_rechazadas_por_symbol += 1
                    continue
                statements += self._add_statement(
                    db=db,
                    company=company,
                    document=document,
                    statement_type=statement_type,
                    row=row,
                )
                facts += self._add_facts(
                    db=db,
                    company=company,
                    document=document,
                    row=row,
                    specs=specs,
                    seen=seen_keys,
                )
                filled = _norm_date(row.get("fillingDate"))
                if filled:
                    filling_dates.append(date.fromisoformat(filled))

        drop_shadowed_facts(db, company.id, document.id, tenant_condition(db))
        facts += self._add_derived_facts(db, company, document)
        facts += self._add_profile_facts(db, company, document, profile)
        await self._add_spot_price(db, company, fmp, ticker)
        if filling_dates:
            # FIX de la publicacion: los hechos apuntan a este documento y sin
            # fecha de publicacion el guard point-in-time nunca podia disparar
            # su eje de publicacion.
            document.published_at = datetime.combine(
                max(filling_dates), datetime.min.time(), tzinfo=UTC
            )

        document.metadata_ = {
            **(document.metadata_ or {}),
            "provider": "FMP",
            "last_refreshed_at": datetime.now(UTC).isoformat(),
            "income_rows": len(income),
            "balance_rows": len(balance),
            "cash_flow_rows": len(cash_flow),
            "ratio_rows": len(ratios),
        }
        db.commit()

        return {
            "status": "ingested",
            "ticker": ticker,
            "provider": "FMP",
            "source_document_id": document.id,
            "facts_imported": facts,
            "statements_imported": statements,
            "rows_rechazadas_por_symbol": rows_rechazadas_por_symbol,
            "latest_periods": self.latest_periods(db, company),
            "valuation_input_ready": self.valuation_input_ready(db, company),
        }

    async def refresh_from_sec(
        self,
        db: Session,
        company: Company,
        as_of: date | None = None,
    ) -> dict[str, Any]:
        """Ingesta de fundamentales SEC. ``as_of`` es un corte de INFORMACION:
        solo entra lo ya publicado (``filed``) en esa fecha. Con ``as_of=None``
        no se filtra por fecha y el resultado lo declara (FIX5-1)."""
        from app.services.connectors.sec_edgar import drain_mirror_serves

        drain_mirror_serves()  # marca el inicio de ESTA corrida
        sec = SECClient()
        ticker = company.ticker.upper()

        try:
            cik = await sec.cik_for_ticker(ticker)
        except Exception as e:
            raise RuntimeError(f"SEC fetch failed: {e}") from e

        if not cik:
            raise RuntimeError(f"Sin CIK para {ticker}: este emisor no reporta a la SEC; usa la fuente de su mercado local (ESEF para emisores de la UE)")

        try:
            facts_data = await sec.company_facts(cik)
        except Exception as e:
            raise RuntimeError(f"SEC fetch failed: {e}") from e

        # La entidad del payload debe ser la que se resolvio para el ticker y la
        # que dice la ficha: `company_tickers.json` tiene entradas duplicadas
        # para el mismo ticker (tickers reutilizados tras un delisting) y un
        # manifest local desactualizado puede resolver el CIK de OTRO emisor.
        # Sin este contraste, los hechos de Apple acababan en la ficha de ABCD
        # con confidence=0.95 (FIX5-6). Fail closed: sin entidad que contrastar
        # (payload sin `cik` declarado, que la API real nunca produce) no hay
        # nada que falsificar y la ingesta sigue igual que antes.
        payload_cik = str(facts_data.get("cik") or "").strip()
        resolved_cik = str(cik).zfill(10)
        card_cik = str(getattr(company, "cik", "") or "").strip()
        if payload_cik:
            payload_cik = payload_cik.zfill(10)
            mismatches = []
            if payload_cik != resolved_cik:
                mismatches.append(f"CIK resuelto {resolved_cik}")
            if card_cik and payload_cik != card_cik.zfill(10):
                mismatches.append(f"CIK de la ficha {card_cik.zfill(10)}")
            if mismatches:
                raise RuntimeError(
                    f"CIK del payload {payload_cik} != {' y '.join(mismatches)} "
                    f"para {ticker}: entidad ambigua, no se atribuyen hechos de "
                    "otro emisor (fail closed)"
                )

        us_gaap = facts_data.get("facts", {}).get("us-gaap", {})
        # 40-F/20-F en IFRS (BN): sin us-gaap, la misma lectura va sobre
        # ifrs-full con su mapa de conceptos; el resto de reglas no cambia.
        metric_map = SEC_METRIC_MAP
        taxonomy = "us-gaap"
        if not us_gaap and facts_data.get("facts", {}).get("ifrs-full"):
            us_gaap = facts_data["facts"]["ifrs-full"]
            metric_map = SEC_IFRS_METRIC_MAP
            taxonomy = "ifrs-full"
        # Divisa de reporte del filer (10-K: USD; 20-F en US GAAP: CNY, TWD...).
        # Cada hecho monetario se guarda con ELLA como unidad.
        reporting_currency = _sec_reporting_currency(us_gaap)

        # Evidencia de calendario a nivel de filing (submissions). Fail
        # closed: sin anclas no entra NINGUN hecho anual (la cobertura
        # parcial queda visible en el resultado); los trimestres siguen su
        # flujo normal. Nunca se sustituye por una moda de hechos: esa moda
        # es envenenable con ruido TTM y una fecha de portada de 10-K no.
        try:
            annual_anchors = await sec.annual_report_anchors(cik)
        except Exception:  # noqa: BLE001 - fail closed anual, no romper trimestres
            annual_anchors = {}
        # Indice de filings del emisor para verificar el carril DEI: un hecho
        # de portada que cita un accession que el indice ya no lista no es
        # verificable y NO entra (regla de oro: OFICIAL solo si el indice lo
        # verifica). Fail closed: indice caido -> None -> no entra ningun DEI.
        try:
            index_accessions: set[str] | None = await sec.index_accessions(cik)
        except Exception:  # noqa: BLE001 - fail closed DEI, no romper lo demas
            index_accessions = None

        document = self._source_document_sec(db, company, ticker)
        # published_at = presentacion mas reciente (campo `filed` de companyfacts)
        # para que la procedencia OFICIAL tenga fecha; nunca se inventa.
        latest_filed = _latest_filed_date(us_gaap)
        if latest_filed is not None and (
            document.published_at is None
            or document.published_at.date() < latest_filed
        ):
            document.published_at = datetime(
                latest_filed.year, latest_filed.month, latest_filed.day, tzinfo=UTC
            )

        facts_imported = 0
        cash_restricted_years: set[int] = set()
        concept_usage: dict[str, dict[str, Any]] = {}
        capital_provenance = dict((document.metadata_ or {}).get("capital_fact_provenance") or {})
        # La moda SOLO etiqueta trimestres (los 10-Q no declaran su cierre de
        # ejercicio por hecho); la admision anual va por ancla de filing.
        modal_fy_month = _current_fiscal_month_from_anchors(
            annual_anchors
        ) or _modal_fiscal_end_month(us_gaap)
        bank_like = _is_bank_like(company)

        # Pre-computo anual (funciones puras sobre companyfacts), ANTES del
        # replace, para que el borrado sea selectivo por (metric, period):
        # solo se reescriben los ejercicios que este import re-autoriza
        # (un restatement machaca la cifra vieja) y se conservan los FY
        # validos que ya no son re-anclables (p.ej. calendario anterior
        # cuyos filings salieron de la ventana de submissions).
        annual_by_metric: dict[str, dict[str, dict[str, Any]]] = {}
        restated_fy_keys: list[tuple[str, str]] = []
        for metric, concepts, unit in metric_map:
            unit_keys = _sec_unit_keys(unit, reporting_currency)
            if unit_keys is None:
                continue
            unit, xbrl_unit_key = unit_keys
            metric_concepts = (
                _revenue_concepts_for(concepts, bank_like)
                if metric == "revenue"
                else concepts
            )
            by_end = _merge_for_metric(
                _collect_by_concept(
                    us_gaap,
                    metric_concepts,
                    xbrl_unit_key,
                    forms=ANNUAL_REPORT_FORMS,
                    periods={"FY"},
                    min_span=300,
                    max_span=380,
                    annual_anchors=annual_anchors,
                    as_of=as_of,
                    require_start=metric in CAPITAL_FLOW_METRICS,
                ),
                metric,
            )
            if metric == "revenue" and bank_like:
                # Bancos: rellena solo los periodos sin tag agregado.
                for end, entry in _compose_bank_revenue(
                    us_gaap,
                    forms=ANNUAL_REPORT_FORMS,
                    periods={"FY"},
                    min_span=300,
                    max_span=380,
                    annual_anchors=annual_anchors,
                    as_of=as_of,
                ).items():
                    by_end.setdefault(end, entry)
            if by_end:
                # El cap se aplica AQUI, no en la insercion: las claves del
                # replace y el reporte de cobertura reflejan EXACTAMENTE lo
                # insertado. Lo que queda fuera del cap no se borra: si ya
                # estaba verificado en DB se preserva (borrarlo sin
                # reinsertarlo perderia historia valida).
                capped = dict(
                    sorted(by_end.items(), key=lambda kv: str(kv[0]), reverse=True)[:20]
                )
                annual_by_metric[metric] = capped
                restated_fy_keys.extend((metric, f"{end}:FY") for end in capped)

        # Historia trimestral: el import solo re-inserta los 12 trimestres mas
        # recientes por metrica, y _replace_sec_data borra todos los trimestres
        # del documento. Sin esta foto, cada refresh perdia en silencio los
        # trimestres que salen de la ventana (los FY ya se preservan, F353).
        prior_quarters = self._snapshot_sec_quarters(db, company, document)
        quarter_ends_by_metric: dict[str, set[str]] = {}
        quarter_unit_by_metric: dict[str, str] = {}

        self._replace_sec_data(
            db, company, document, restated_fy_keys=restated_fy_keys
        )

        for metric, concepts, unit in metric_map:
            unit_keys = _sec_unit_keys(unit, reporting_currency)
            if unit_keys is None:
                continue
            unit, xbrl_unit_key = unit_keys
            # --- Trimestres (10-Q): mismas reglas de fusion por `end` ---
            # fp Q1-Q4 + form 10-Q; flujo = 70-110 dias (trimestre real; los
            # acumulados YTD de ~180 dias y los TTM quedan fuera); instantaneos
            # (balance, sin start) pasan. fiscal_year queda NULL a proposito:
            # los consumidores anuales seleccionan por fiscal_year (y los que
            # ordenan por el usan nullslast), asi las filas :Qn nunca se
            # confunden con el ejercicio anual. period = "<end>:Q<n>". La
            # etiqueta <n> se deriva del cierre contra el mes modal de cierre
            # de ejercicio: el fp de companyfacts es el periodo fiscal DE LA
            # PRESENTACION (las comparativas heredan el fp del 10-Q que las
            # trae), no el del dato. Fallback a fp sin ancla modal.
            metric_concepts_q = (
                _revenue_concepts_for(concepts, bank_like)
                if metric == "revenue"
                else concepts
            )
            by_end_q = _merge_for_metric(
                _collect_by_concept(
                    us_gaap,
                    metric_concepts_q,
                    xbrl_unit_key,
                    forms={"10-Q"},
                    periods={"Q1", "Q2", "Q3", "Q4"},
                    min_span=70,
                    max_span=110,
                    as_of=as_of,
                    # FIX5-8: shares_diluted es un promedio ponderado (flujo).
                    # Sin ancla trimestral, un saldo instantaneo de portada
                    # entraba como '<fecha>:Qn' y el mismo trimestre acababa
                    # con dos filas shares_diluted.
                    require_start=metric == "shares_diluted" or metric in CAPITAL_FLOW_METRICS,
                ),
                metric,
            )
            if metric == "revenue" and bank_like:
                for end, entry in _compose_bank_revenue(
                    us_gaap,
                    forms={"10-Q"},
                    periods={"Q1", "Q2", "Q3", "Q4"},
                    min_span=70,
                    max_span=110,
                    as_of=as_of,
                ).items():
                    by_end_q.setdefault(end, entry)
            if metric not in NON_ADDITIVE_FLOWS:
                # El estado de flujos de efectivo de un 10-Q suele venir SOLO
                # acumulado (3, 6 y 9 meses: AAPL, flujo operativo y capex),
                # asi que el filtro de 70-110 dias dejaba sin Q2/Q3. Se derivan
                # restando acumulados del mismo ejercicio: Q(t) = YTD(t) -
                # YTD(t-1). Un trimestre de 3 meses presentado siempre gana;
                # las filas derivadas van con is_reported=False (INFERIDO).
                ytd_by_end = _merge_for_metric(
                    _collect_by_concept(
                        us_gaap,
                        metric_concepts_q,
                        xbrl_unit_key,
                        forms={"10-Q"},
                        periods={"Q1", "Q2", "Q3", "Q4"},
                        min_span=150,
                        max_span=290,
                        as_of=as_of,
                        require_start=True,
                    ),
                    metric,
                )
                for end, entry in _quarters_from_ytd(by_end_q, ytd_by_end).items():
                    by_end_q.setdefault(end, entry)
            if by_end_q:
                q_sorted = sorted(
                    by_end_q.values(), key=lambda e: str(e["end"]), reverse=True
                )[:12]
                for entry in q_sorted:
                    val = _decimal(entry.get("val"))
                    if val is None:
                        continue
                    if metric == "capital_expenditure":
                        val = -val
                    fp = _fiscal_quarter_from_end(
                        str(entry["end"]), modal_fy_month
                    ) or str(entry["fp"])
                    derived_from_ytd = bool(entry.get("_derived_from_ytd"))
                    db.add(
                        FinancialFact(
                            company_id=company.id,
                            metric=metric,
                            value=val,
                            unit=unit,
                            period=f"{entry['end']}:{fp}",
                            fiscal_year=None,
                            fiscal_quarter=fp,
                            source_id=document.id,
                            source_type="SEC",
                            is_reported=not derived_from_ytd,
                            confidence=Decimal("0.85") if derived_from_ytd else Decimal("0.9"),
                            accession_number=entry.get("accn"),
                            filed=_publication_date(entry),
                        )
                    )
                    # Misma proveniencia por periodo que el bucle anual:
                    # clave "<end>:<fp>" para no colisionar con el FY.
                    concept_usage.setdefault(metric, {})[
                        f"{entry['end']}:{fp}"
                    ] = entry.get("_concept")
                    if metric in CAPITAL_PROVENANCE_METRICS:
                        capital_provenance.setdefault(metric, {})[f"{entry['end']}:{fp}"] = {
                            "filed": entry.get("filed"), "concept": entry.get("_concept"),
                        }
                    facts_imported += 1
                    quarter_ends_by_metric.setdefault(metric, set()).add(
                        str(entry["end"])
                    )
                    quarter_unit_by_metric[metric] = unit
            # Los alias se FUSIONAN, no "gana el primero que informe": muchos
            # filers migraron de tag (Revenues -> SalesRevenueNet ->
            # RevenueFromContractWithCustomer...) y el tag antiguo queda
            # congelado en el pasado. Fusion por periodo (`end`) conservando
            # el `filed` mas reciente: mismo periodo bajo dos tags = una sola
            # vez, con su presentacion mas reciente (recast incluido).
            # OJO: `fy` es el ANIO DEL FILING, no el del periodo. Un 10-K de
            # FY2025 trae revenue de 2025, 2024 y 2023; el ano fiscal correcto
            # es el del `end`. Ante re-presentaciones del mismo periodo manda
            # el `filed` mas reciente, pero DENTRO de cada tag: comparar tags
            # distintos entre si es lo que descartaba una de las partes de
            # `intangible_assets` en vez de sumarlas.
            by_end = annual_by_metric.get(metric) or {}
            if by_end:
                # Ya capeado en el pre-computo (~2 eras completas); la
                # cobertura real queda en fy_periods del resultado.
                annual_sorted = sorted(
                    by_end.values(), key=lambda e: str(e["end"]), reverse=True
                )
                for entry in annual_sorted:
                    val = _decimal(entry.get("val"))
                    if val is None:
                        continue
                    if metric == "capital_expenditure":
                        val = -val
                    if (
                        metric == "cash_and_equivalents"
                        and entry.get("_concept")
                        == "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"
                    ):
                        cash_restricted_years.add(_annual_fiscal_year(str(entry["end"]), modal_fy_month))
                    db.add(
                        FinancialFact(
                            company_id=company.id,
                            metric=metric,
                            value=val,
                            unit=unit,
                            period=f"{entry['end']}:FY",
                            fiscal_year=_annual_fiscal_year(str(entry["end"]), modal_fy_month),
                            fiscal_quarter="FY",
                            source_id=document.id,
                            source_type="SEC",
                            is_reported=True,
                            confidence=Decimal("0.95"),
                            accession_number=entry.get("accn"),
                            filed=_publication_date(entry),
                        )
                    )
                    # Record which XBRL concept produced the value. Several
                    # metrics accept alternative tags with different scopes, so
                    # without this the definition of a series can change between
                    # years with nothing in the database saying so. The map is
                    # written to the document below (FinancialFact has no
                    # free-form column, and this is per-run provenance).
                    concept_usage.setdefault(metric, {})[str(entry["end"])] = entry.get(
                        "_concept"
                    )
                    if metric in CAPITAL_PROVENANCE_METRICS:
                        capital_provenance.setdefault(metric, {})[f"{entry['end']}:FY"] = {
                            "filed": entry.get("filed"), "concept": entry.get("_concept"),
                        }
                    facts_imported += 1

        facts_imported += self._restore_sec_quarters(
            db,
            company,
            document,
            prior_quarters,
            quarter_ends_by_metric,
            quarter_unit_by_metric,
        )

        # --- dei:EntityCommonStockSharesOutstanding (portada 10-K/10-Q) ---
        # El saldo de acciones en circulacion lo reporta todo emisor SEC en la
        # PORTADA del filing (namespace dei), no necesariamente como hecho
        # us-gaap: sin esta pasada empresas con todo reportado (caso real UNH)
        # salian N/D en dilucion. Son instantes de portada: su `end` es la
        # fecha "as of" de la portada, NO el cierre fiscal - por eso NO pasan
        # el anclaje anual (su mes nunca es el del cierre) y se guardan con
        # fiscal_year/fiscal_quarter NULL y sufijo :DEI (re-autorizados en cada
        # refresh por la regla fiscal_quarter IS NULL de _replace_sec_data).
        # Multi-clase (META, GOOGL, BRK.B, ASTS): la SEC no consolida las
        # clases en companyfacts (van por dimension); esas clases entran por
        # el carril per-clase, no por aqui.
        dei = facts_data.get("facts", {}).get("dei", {}) or {}
        ecso_entries = (
            dei.get("EntityCommonStockSharesOutstanding", {})
            .get("units", {})
            .get("shares", [])
        )
        ecso_by_end: dict[str, dict[str, Any]] = {}
        for entry in ecso_entries:
            if entry.get("form") not in SHARES_OUTSTANDING_FORMS:
                continue
            # Verificacion contra el indice (no el anclaje anual: el `end` de
            # portada nunca casa con el cierre fiscal). Sin el accn listado en
            # submissions el hecho de portada no es verificable: no entra.
            if index_accessions is None or entry.get("accn") not in index_accessions:
                continue
            if as_of is not None and not _published_by(entry, as_of):
                continue
            end = str(entry.get("end") or "")
            if not end:
                continue
            current = ecso_by_end.get(end)
            if current is None or str(entry.get("filed") or "") > str(
                current.get("filed") or ""
            ):
                ecso_by_end[end] = entry
        for end in sorted(ecso_by_end, reverse=True):
            entry = ecso_by_end[end]
            val = _decimal(entry.get("val"))
            if val is None or val <= 0:
                continue
            period = f"{end}:DEI"
            # El concepto us-gaap ya informo este mismo saldo con el mismo
            # `end` (mismo filing): no duplicar la fila.
            existing = annual_by_metric.get("shares_outstanding", {})
            if end in existing:
                continue
            db.add(
                FinancialFact(
                    company_id=company.id,
                    metric="shares_outstanding",
                    value=val,
                    unit="shares",
                    period=period,
                    fiscal_year=None,
                    fiscal_quarter=None,
                    source_id=document.id,
                    source_type="SEC",
                    is_reported=True,
                    confidence=Decimal("0.95"),
                    accession_number=entry.get("accn"),
                    filed=_publication_date(entry),
                )
            )
            concept_usage.setdefault("shares_outstanding", {})[period] = (
                "dei:EntityCommonStockSharesOutstanding"
            )
            capital_provenance.setdefault("shares_outstanding", {})[period] = {
                "filed": entry.get("filed"),
                "concept": "dei:EntityCommonStockSharesOutstanding",
            }
            facts_imported += 1

        if concept_usage:
            existing_meta = dict(document.metadata_ or {})
            existing_meta["xbrl_concept_by_metric_period"] = concept_usage
            existing_meta["capital_fact_provenance"] = capital_provenance
            # Taxonomia leida (us-gaap o ifrs-full): procedencia del concepto.
            existing_meta["xbrl_taxonomy"] = taxonomy
            document.metadata_ = existing_meta

        drop_shadowed_facts(db, company.id, document.id, tenant_condition(db))

        if cash_restricted_years:
            document.metadata_ = {
                **(document.metadata_ or {}),
                # Nota de cobertura: estos ejercicios usan caja + caja
                # restringida (el emisor dejo de reportar caja estricta).
                # La deuda neta derivada es ligeramente optimista en ellos.
                "cash_includes_restricted_periods": sorted(cash_restricted_years),
            }
        facts_imported += self._derive_sec_metrics(
            db, company, document, debt_signal_latest_end=_latest_debt_signal_end(us_gaap)
        )

        conflicts: list[str] = []
        sec_facts = list(
            db.scalars(
                select(FinancialFact).where(
                    FinancialFact.company_id == company.id,
                    FinancialFact.source_type == "SEC",
                )
            )
        )
        # Batch: every FMP fact for the company once, matched in Python
        # instead of one query per SEC fact.
        fmp_by_key = {
            (fact.metric, fact.period): fact
            for fact in db.scalars(
                select(FinancialFact).where(
                    FinancialFact.company_id == company.id,
                    FinancialFact.source_type == "FMP",
                )
            ).all()
        }
        for sec_fact in sec_facts:
            fmp_fact = fmp_by_key.get((sec_fact.metric, sec_fact.period))
            if fmp_fact is not None:
                sec_val = float(sec_fact.value)
                fmp_val = float(fmp_fact.value)
                diff = abs(sec_val - fmp_val) / max(abs(fmp_val), 1)
                if diff > 0.05:
                    pct = round(diff * 100, 1)
                    conflicts.append(
                        f"{sec_fact.metric}:{sec_fact.period} FMP={int(fmp_val)} SEC={int(sec_val)} diff={pct}%"
                    )

        # Una muestra representativa por lote, nunca una llamada por hecho.
        # La anomalía es solo una bandera; no toca las cifras ingestadas.
        jev_anomaly = None
        if conflicts:
            # nosemgrep: gerarai-broad-except-pass -- marca opcional de Jev (best-effort); la ingesta sigue
            try:
                from app.services.jev_gates import ANOMALY_CRITERIA, mark_only
                jev_anomaly = mark_only("data_anomaly", "\n".join(conflicts[:8]),
                    "Mark possible source discrepancies for human review; do not correct values.",
                    ANOMALY_CRITERIA)
            except Exception:  # noqa: BLE001
                pass
        document.metadata_ = {
            **(document.metadata_ or {}),
            "provider": "SEC",
            "cik": cik,
            "last_refreshed_at": datetime.now(UTC).isoformat(),
            "conflicts": conflicts,
            **({"jev_anomaly": jev_anomaly} if jev_anomaly else {}),
        }
        # Hook gratuito best-effort (EDGAR 10-K/10-Q + FRED): una llamada que
        # nunca rompe el flujo principal de ingesta.
        try:
            free_data = await _free_data_snapshot(ticker, cik)
        except Exception:
            free_data = {"status": "unavailable", "recent_filings": [], "macro": None}
        document.metadata_ = {**(document.metadata_ or {}), "free_data": free_data}
        # Chunks RAG desde los hechos persistidos (ver refresh_from_esef).
        fy_periods = sorted({period for _m, period in restated_fy_keys}, reverse=True)
        # Procedencia de transporte: si algo se sirvio del mirror HF (ban de
        # IP), queda declarado con la fecha de sync del mirror.
        mirror_serves = drain_mirror_serves()
        mirror_info = None
        if mirror_serves:
            mirror_info = {
                "documents": len(mirror_serves),
                "synced_at": mirror_serves[-1].get("synced_at"),
            }
        # "mirror" se escribe SIEMPRE (null cuando esta corrida fue SEC
        # directo): una clave vieja de una corrida con fallback no puede
        # sobrevivir y atribuir al mirror una ingesta directa.
        document.metadata_ = {
            **(document.metadata_ or {}),
            "fy_periods": fy_periods,
            "mirror": mirror_info,
        }
        sync_company_fact_chunks(db, company)
        db.commit()

        return {
            "status": "ingested",
            "ticker": ticker,
            "provider": "SEC",
            "source_document_id": document.id,
            "facts_imported": facts_imported,
            "cik": cik,
            # Corte de informacion aplicado (FIX5-1). Con as_of=None el filtro
            # de fecha NO se aplico y el consumidor lo ve aqui.
            "as_of": as_of.isoformat() if as_of else None,
            "date_filter_applied": as_of is not None,
            "conflicts": conflicts,
            "free_data": free_data,
            "fy_periods": fy_periods,
            "annual_anchored_filings": len(annual_anchors),
            # Procedencia del listado de filings que ancla los FY: si vino del
            # fallback EFTS es PARCIAL (sin historico completo) y el consumidor
            # lo ve aqui. No cambia ningun valor financiero.
            "annual_anchor_source": getattr(annual_anchors, "source", "sec-submissions"),
            "annual_anchor_partial": bool(getattr(annual_anchors, "partial", False)),
            "annual_anchor_note": (
                "Anclas anuales desde EDGAR full-text search: cobertura parcial, "
                "sin historico completo de filings."
                if getattr(annual_anchors, "partial", False)
                else None
            ),
            # None cuando no hubo fallback: el consumidor ve la fuente real.
            "mirror": mirror_info,
        }

    async def refresh_from_esef(self, db: Session, company: Company) -> dict[str, Any]:
        """Fundamentales anuales IFRS desde el snapshot ESEF local (build_esef_snapshots).

        Solo hechos consolidados (entry["dims"] == []: los desgloses por miembro
        NUNCA se leen como total consolidado). Duraciones anuales (300-380 dias)
        para magnitudes de flujo; instantes para balance. Alias fusionados por
        periodo: gana el primer alias que informa el periodo, nunca se suman.

        Guardia de identidad: Company es GLOBAL y los tickers no son unicos a
        nivel mundial; un ticker reciclado o compartido (caso real 2026-10-19:
        KRKNF = Kraken Robotics CA ligado por error a Kerry Group IE) escribiria
        los hechos de UN EMISOR bajo OTRA Company. Si el nombre de la Company y
        el entity_name del snapshot no comparten ningun token significativo, se
        rechaza la escritura (company_mismatch): N/D honesto, nunca hechos
        cruzados.
        """
        ticker = company.ticker.upper()
        snapshot = esef_connector.read_esef_snapshot(ticker)
        if snapshot is None:
            raise RuntimeError(f"Sin snapshot ESEF local para {ticker}: por ahora solo hay cobertura de emisores IBEX revisados")
        # Multi-package snapshots now preserve incompatible presentations in
        # an archive instead of silently blending them. Their current facts
        # may be narrower; reject BEFORE source creation/deletion/commit.
        if snapshot.get("requires_presentation_review"):
            raise RuntimeError(
                "esef_presentation_review_required: snapshot preserves separate "
                "filing presentations; automatic history replacement is blocked"
            )
        from app.services.esef_issuer_mapping import (
            reviewed_isins_for_ticker,
            reviewed_names_for_ticker,
        )

        # Carril ISIN (prueba fuerte): la Company captura ISIN del Flex de
        # IBKR; si ambos lados lo tienen, manda el ISIN sobre el nombre.
        reviewed_isins = reviewed_isins_for_ticker(ticker)
        company_isin = (company.isin or "").strip().upper()
        if company_isin and reviewed_isins:
            if company_isin not in reviewed_isins:
                raise RuntimeError(
                    "company_mismatch: ISIN de la Company "
                    f"{company_isin} no esta entre los ISINs reviewed "
                    f"{sorted(reviewed_isins)} para {ticker} "
                    f"({snapshot.get('entity_name')!r}): no se escriben "
                    "hechos de una entidad bajo otra"
                )
        else:
            candidates = reviewed_names_for_ticker(ticker) | {
                n for n in [snapshot.get("entity_name")] if n
            }
            if not any(_name_identity_ok(company.name, n) for n in candidates):
                raise RuntimeError(
                    "company_mismatch: la Company "
                    f"{company.name!r} no acredita identidad con el emisor ESEF "
                    f"{snapshot.get('entity_name')!r} ({snapshot.get('lei')}): "
                    "no se escriben hechos de una entidad bajo otra"
                )

        from app.services.esef_fact_quarantine import reviewed_eps_conflict

        # Reviewed issuer conflicts stay in the source snapshot, but are not
        # eligible inputs for new facts or derivatives. No guessed rescaling.
        facts_data = {
            concept: {
                unit: [entry for entry in entries if not reviewed_eps_conflict(
                    str(snapshot.get("lei") or ""),
                    str(entry.get("end") or entry.get("instant") or ""),
                    concept, entry.get("val"),
                )]
                for unit, entries in units.items()
            }
            for concept, units in snapshot.get("facts", {}).items()
        }
        document = self._source_document_esef(db, company, ticker, snapshot)
        self._replace_esef_data(db, company, document)
        facts_imported = 0

        esef_coverage: dict[str, Any] = {}
        for metric, concepts, unit in ESEF_METRIC_MAP:
            by_period, coverage = _merge_esef_periods(facts_data, concepts, unit, metric)
            if coverage["ambiguous"] or coverage["partial"]:
                esef_coverage[metric] = coverage
            for period_date in sorted(by_period, reverse=True)[:10]:
                val = _decimal(by_period[period_date].get("val"))
                if val is None:
                    continue
                if metric == "capital_expenditure":
                    val = -val
                db.add(
                    FinancialFact(
                        company_id=company.id,
                        metric=metric,
                        value=val,
                        unit="EUR/share" if unit.endswith("/xbrli:shares") else "EUR",
                        period=f"{period_date}:FY",
                        fiscal_year=_annual_fiscal_year(period_date, None),
                        fiscal_quarter="FY",
                        source_id=document.id,
                        source_type="ESEF",
                        is_reported=True,
                        confidence=Decimal("0.95"),
                    )
                )
                facts_imported += 1

        # la sesion de ingestion usa autoflush=False: drop_shadowed_facts hace flush antes de derivar
        drop_shadowed_facts(db, company.id, document.id, tenant_condition(db))
        facts_imported += self._derive_esef_metrics(db, company, document)
        facts_imported += self._import_esef_shares(db, company, document, facts_data)

        document.metadata_ = {
            **(document.metadata_ or {}),
            "provider": "ESEF",
            "lei": snapshot.get("lei"),
            "entity_name": snapshot.get("entity_name"),
            "period_end": snapshot.get("period_end"),
            "fxo_id": snapshot.get("fxo_id"),
            "snapshot_fetched_at": snapshot.get("fetched_at"),
            "esef_coverage": esef_coverage,
            "last_refreshed_at": datetime.now(UTC).isoformat(),
        }
        # Chunks RAG desde los hechos persistidos (documento parseado no existe:
        # el snapshot es XBRL, no texto). Sin esto rebuild_tenant no indexa nada.
        sync_company_fact_chunks(db, company)
        db.commit()

        return {
            "status": "ingested",
            "ticker": ticker,
            "provider": "ESEF",
            "source_document_id": document.id,
            "facts_imported": facts_imported,
            "lei": snapshot.get("lei"),
            "period_end": snapshot.get("period_end"),
            "latest_periods": self.latest_periods(db, company),
            "valuation_input_ready": self.valuation_input_ready(db, company),
        }

    def latest_periods(self, db: Session, company: Company) -> dict[str, str | None]:
        periods: dict[str, str | None] = {}
        for metric in ["revenue", "free_cash_flow", "net_debt", "shares_diluted"]:
            fact = self.latest_fact(db, company, metric)
            periods[metric] = fact.period if fact else None
        return periods

    def valuation_input_ready(self, db: Session, company: Company) -> bool:
        return all(
            self.latest_fact(db, company, metric)
            for metric in ["revenue", "free_cash_flow", "shares_diluted"]
        )

    def latest_fact(self, db: Session, company: Company, metric: str) -> FinancialFact | None:
        """Latest fact for a metric, preferring the authoritative source.

        Ordering by ``created_at`` alone meant whichever provider was ingested
        last owned the metric: after a ``refresh_from_fmp`` on top of SEC, the
        DCF anchor could be the vendor's revenue while the primary filing sat
        ignored, with nothing in the trace saying so. The priority makes the
        choice deterministic and the provenance auditable.
        """
        rows = list(
            db.scalars(
                select(FinancialFact)
                .where(FinancialFact.company_id == company.id, FinancialFact.metric == metric)
                .order_by(
                    FinancialFact.fiscal_year.desc().nullslast(),
                    FinancialFact.created_at.desc(),
                    FinancialFact.id.desc(),
                )
            ).all()
        )
        if not rows:
            return None
        latest_year = rows[0].fiscal_year
        candidates = [row for row in rows if row.fiscal_year == latest_year]
        return min(
            candidates,
            key=lambda row: (SOURCE_PRIORITY.get(row.source_type or "", 50), row.id),
        )

    def _source_document(self, db: Session, company: Company) -> Document:
        title = f"FMP normalized financials - {company.ticker}"
        document = db.scalar(
            select(Document).where(
                Document.company_id == company.id,
                Document.source_type == "FMP",
                Document.title == title,
            )
        )
        if document:
            return document
        document = Document(
            company_id=company.id,
            title=title,
            source_type="FMP",
            source_url=f"https://financialmodelingprep.com/financial-summary/{company.ticker}",
            metadata_={"provider": "FMP", "normalized": True},
        )
        db.add(document)
        db.flush()
        return document

    def _replace_fmp_data(self, db: Session, company: Company, document: Document) -> None:
        tenant_id = db.info.get("tenant_id")
        fact_tenant = (
            FinancialFact.tenant_id == tenant_id
            if tenant_id is not None
            else FinancialFact.tenant_id.is_(None)
        )
        statement_tenant = (
            FinancialStatement.tenant_id == tenant_id
            if tenant_id is not None
            else FinancialStatement.tenant_id.is_(None)
        )
        delete_financial_facts(
            db,
            FinancialFact.company_id == company.id,
            FinancialFact.source_type == "FMP",
            fact_tenant,
        )
        db.execute(
            delete(FinancialStatement).where(
                FinancialStatement.company_id == company.id,
                FinancialStatement.source_id == document.id,
                statement_tenant,
            )
        )
        db.flush()

    def _derive_sec_metrics(
        self,
        db: Session,
        company: Company,
        document: Document,
        debt_signal_latest_end: date | None = None,
    ) -> int:
        """Metricas derivadas del XBRL bruto (la SEC publica componentes, no
        derivadas; FMP si las trae): FCF = OCF + capex (capex ya negativo),
        margen FCF, crecimiento de revenue y deuda neta, por ano fiscal.
        Sin ellas el snapshot de valoracion queda insufficient_data.

        Deuda neta sin concepto de deuda: si el ejercicio no tiene NINGUN
        hecho total_debt pero el balance completo consta (caja, activos y
        pasivos del mismo ano) Y el emisor no muestra ningun tag de deuda
        financiera con valor en los ultimos 5 ejercicios
        (DEBT_SIGNAL_CONCEPTS, evidencia positiva), la deuda neta se deriva
        como -caja con la etiqueta "calculada; sin deuda financiera
        reportada (ausencia de concepto, no un cero reportado)" en
        document.metadata_ y en el claim de la tesis. Con señal de deuda
        reciente o sin balance completo no se infiere nada: N/D. El LLM
        nunca aporta la cifra: toda derivada nace de hechos reportados con
        fuente."""
        by_metric: dict[str, dict[int, FinancialFact]] = {}
        for fact in db.scalars(
            select(FinancialFact).where(
                FinancialFact.company_id == company.id,
                FinancialFact.source_type == "SEC",
                FinancialFact.is_reported.is_(True),
            )
        ):
            if fact.fiscal_year is not None:
                by_metric.setdefault(fact.metric, {})[fact.fiscal_year] = fact

        def year_fact(metric: str, year: int) -> FinancialFact | None:
            return by_metric.get(metric, {}).get(year)

        derived = 0
        no_financial_debt_periods: dict[str, str] = {}
        # Evidencia positiva para "sin deuda financiera": ningun tag de deuda
        # (DEBT_SIGNAL_CONCEPTS) con valor en los ultimos 5 ejercicios, contado
        # desde el ejercicio anual mas reciente de esta ingesta (nivel emisor).
        # Con señal reciente la ausencia de total_debt puede ser un hueco de
        # mapeo (ShortTermBorrowings, convertibles, leases...) y la deuda neta
        # queda N/D, nunca -caja (regla del auditor, 19/10/2026).
        latest_annual_end: date | None = None
        for metric_facts in by_metric.values():
            for fact in metric_facts.values():
                try:
                    end = date.fromisoformat(str(fact.period).split(":")[0])
                except ValueError:
                    continue
                if latest_annual_end is None or end > latest_annual_end:
                    latest_annual_end = end
        debt_signal_recent = (
            debt_signal_latest_end is not None
            and latest_annual_end is not None
            and (latest_annual_end - debt_signal_latest_end).days
            <= DEBT_SIGNAL_MAX_AGE_DAYS
        )
        # roe y book_value_growth solo se derivan para motores que los usan
        # como INPUT PROPIO (insurer/bank, P/B-ROE). Derivarlas para toda
        # empresa las haria visibles como alias de dividend_growth en el motor
        # DDM/FCFE (ddm_fcfe.py no filtra is_reported) y cambiaria valoraciones
        # ya publicadas de pagadores de dividendos con un dato que no pedian.
        from app.valuation.engines.registry import resolve_engine_key

        derives_equity_ratios = resolve_engine_key(company) in ("insurer", "bank")
        years = sorted({y for metric_facts in by_metric.values() for y in metric_facts})
        for year in years:
            ocf = year_fact("operating_cash_flow", year)
            capex = year_fact("capital_expenditure", year)
            revenue = year_fact("revenue", year)
            debt = year_fact("total_debt", year)
            cash = year_fact("cash_and_equivalents", year)
            assets = year_fact("total_assets", year)
            liabilities = year_fact("total_liabilities", year)
            equity = year_fact("total_equity", year) if derives_equity_ratios else None
            prev_equity = year_fact("total_equity", year - 1) if derives_equity_ratios else None
            net_income = year_fact("net_income", year) if derives_equity_ratios else None

            # ROE = beneficio neto / patrimonio medio del ejercicio y
            # crecimiento del valor contable (YoY): inputs del motor de
            # aseguradoras/bancos (P/B-ROE). Derivadas de hechos reportados,
            # is_reported=False; sin las dos puntas del periodo no hay dato.
            if net_income is not None and equity is not None and prev_equity is not None:
                avg_equity = (equity.value + prev_equity.value) / 2
                if avg_equity > 0:
                    db.add(
                        FinancialFact(
                            company_id=company.id,
                            metric="roe",
                            value=net_income.value / avg_equity,
                            unit="decimal",
                            period=equity.period,
                            fiscal_year=year,
                            fiscal_quarter="FY",
                            source_id=document.id,
                            source_type="SEC",
                            is_reported=False,
                            confidence=Decimal("0.85"),
                        )
                    )
                    derived += 1
            if equity is not None and prev_equity is not None and prev_equity.value > 0:
                db.add(
                    FinancialFact(
                        company_id=company.id,
                        metric="book_value_growth",
                        value=(equity.value / prev_equity.value) - 1,
                        unit="decimal",
                        period=equity.period,
                        fiscal_year=year,
                        fiscal_quarter="FY",
                        source_id=document.id,
                        source_type="SEC",
                        is_reported=False,
                        confidence=Decimal("0.85"),
                    )
                )
                derived += 1

            fcf: FinancialFact | None = None
            if ocf is not None and capex is not None:
                fcf = FinancialFact(
                    company_id=company.id,
                    metric="free_cash_flow",
                    value=ocf.value + capex.value,
                    # Misma divisa que sus componentes (CNY en un 20-F de BABA).
                    unit=ocf.unit,
                    period=ocf.period,
                    fiscal_year=year,
                    fiscal_quarter="FY",
                    source_id=document.id,
                    source_type="SEC",
                    is_reported=False,
                    confidence=Decimal("0.85"),
                    # Derivada: conocible cuando lo fueron AMBAS entradas.
                    filed=_latest_known_filed(ocf, capex),
                )
                db.add(fcf)
                derived += 1
            if (
                fcf is not None
                and revenue is not None
                and revenue.value > 0
            ):
                db.add(
                    FinancialFact(
                        company_id=company.id,
                        metric="fcf_margin",
                        value=fcf.value / revenue.value,
                        unit="decimal",
                        period=revenue.period,
                        fiscal_year=year,
                        fiscal_quarter="FY",
                        source_id=document.id,
                        source_type="SEC",
                        is_reported=False,
                        confidence=Decimal("0.85"),
                    )
                )
                derived += 1
            previous_revenue = year_fact("revenue", year - 1)
            if (
                revenue is not None
                and previous_revenue is not None
                and previous_revenue.value > 0
            ):
                db.add(
                    FinancialFact(
                        company_id=company.id,
                        metric="revenue_growth",
                        value=(revenue.value / previous_revenue.value) - 1,
                        unit="decimal",
                        period=revenue.period,
                        fiscal_year=year,
                        fiscal_quarter="FY",
                        source_id=document.id,
                        source_type="SEC",
                        is_reported=False,
                        confidence=Decimal("0.85"),
                    )
                )
                derived += 1
            if debt is not None and cash is not None:
                db.add(
                    FinancialFact(
                        company_id=company.id,
                        metric="net_debt",
                        value=debt.value - cash.value,
                        unit=debt.unit,
                        period=debt.period,
                        fiscal_year=year,
                        fiscal_quarter="FY",
                        source_id=document.id,
                        source_type="SEC",
                        is_reported=False,
                        confidence=Decimal("0.85"),
                    )
                )
                derived += 1
            elif (
                debt is None
                and cash is not None
                and assets is not None
                and liabilities is not None
                and not debt_signal_recent
            ):
                # Emisor que ya no reporta NINGUN concepto de deuda financiera
                # en su 10-K (EXEL, 19/10/2026: pago su deuda; el ultimo tag
                # LongTermDebt* es FY2017). Con el balance completo presente
                # (activos y pasivos del mismo ejercicio), la ausencia del
                # concepto significa "sin deuda financiera" y la deuda neta
                # se deriva como -caja. NO es un cero reportado: la fila
                # lleva is_reported=False, confidence rebajada y la etiqueta
                # queda en document.metadata_["net_debt_no_financial_debt_periods"].
                # Sin balance completo no hay inferencia: N/D (no se crea fila).
                db.add(
                    FinancialFact(
                        company_id=company.id,
                        metric="net_debt",
                        value=-cash.value,
                        unit=cash.unit,
                        period=cash.period,
                        fiscal_year=year,
                        fiscal_quarter="FY",
                        source_id=document.id,
                        source_type="SEC",
                        is_reported=False,
                        confidence=Decimal("0.80"),
                    )
                )
                derived += 1
                no_financial_debt_periods[cash.period] = (
                    "calculada; sin deuda financiera reportada en el 10-K del "
                    f"periodo {cash.period} (ausencia de concepto, no un cero reportado)"
                )
        if no_financial_debt_periods:
            existing = dict(
                (document.metadata_ or {}).get("net_debt_no_financial_debt_periods") or {}
            )
            existing.update(no_financial_debt_periods)
            document.metadata_ = {
                **(document.metadata_ or {}),
                "net_debt_no_financial_debt_periods": existing,
            }
        db.flush()
        return derived

    def _import_esef_shares(
        self, db: Session, company: Company, document: Document, facts_data: dict[str, Any]
    ) -> int:
        """Acciones medias derivadas del propio filing ESEF (app.services.esef_shares).

        Sin esta derivacion NINGUN emisor ESEF tiene acciones medias (0/105
        etiquetan WeightedAverageNumberOf*Shares en base scope, medido
        2026-10-29) y el DCF queda bloqueado en el input requerido
        ``shares_diluted``. Dos vias separadas (revision del piloto):
        ``shares_diluted`` SOLO desde BPA diluido (con senal
        ``numerator_adjustment_risk`` cuando el basico difiere mas alla del
        redondeo: posibles convertibles/preferentes en el numerador), y el
        fallback con BPA basico bajo la metrica informativa
        ``shares_basic_derived``, que el DCF NO acepta porque la
        equivalencia con acciones diluidas no se puede acreditar sin un BPA
        diluido igual. Formula, cotas y descartes quedan en metadata del
        documento fuente; toda cifra es is_reported=False (derivada y
        aproximada, nunca oficial).
        """
        from app.services import esef_shares

        profit_periods, _ = _merge_esef_periods(
            facts_data, [esef_shares.ATTRIBUTABLE_PROFIT_CONCEPT],
            esef_shares.PROFIT_UNIT, "net_income_attributable",
        )
        diluted_periods, _ = _merge_esef_periods(
            facts_data, [esef_shares.DILUTED_EPS_CONCEPT],
            esef_shares.EPS_UNIT, "eps_diluted",
        )
        basic_periods, _ = _merge_esef_periods(
            facts_data, [esef_shares.BASIC_EPS_CONCEPT],
            esef_shares.EPS_UNIT, "eps_basic",
        )
        diluted, basic, skipped = esef_shares.derive_shares(
            profit_periods, diluted_periods, basic_periods
        )
        imported = 0
        for item in diluted:
            db.add(
                FinancialFact(
                    company_id=company.id,
                    metric=esef_shares.DILUTED_METRIC,
                    value=item.shares,
                    unit="shares",
                    period=f"{item.period}:FY",
                    fiscal_year=_annual_fiscal_year(item.period, None),
                    fiscal_quarter="FY",
                    source_id=document.id,
                    source_type="ESEF",
                    is_reported=False,
                    confidence=Decimal("0.6") if item.numerator_adjustment_risk else Decimal("0.7"),
                )
            )
            imported += 1
        for item in basic:
            db.add(
                FinancialFact(
                    company_id=company.id,
                    metric=esef_shares.BASIC_METRIC,
                    value=item.shares,
                    unit="shares",
                    period=f"{item.period}:FY",
                    fiscal_year=_annual_fiscal_year(item.period, None),
                    fiscal_quarter="FY",
                    source_id=document.id,
                    source_type="ESEF",
                    is_reported=False,
                    confidence=Decimal("0.6"),
                )
            )
            imported += 1
        document.metadata_ = {
            **(document.metadata_ or {}),
            "esef_shares": {
                "formula": esef_shares.DERIVATION_FORMULA,
                "diluted_metric": esef_shares.DILUTED_METRIC,
                "basic_metric": esef_shares.BASIC_METRIC,
                "dcf_accepts": esef_shares.DILUTED_METRIC,
                "approximate": True,
                "derived": [
                    {
                        "period": d.period,
                        "lane": d.lane,
                        "shares": str(d.shares),
                        "profit": str(d.profit),
                        "eps": str(d.eps),
                        "eps_decimals": d.eps_decimals,
                        "rel_error_bound": f"{d.rel_error_bound:.4%}",
                        "numerator_adjustment_risk": d.numerator_adjustment_risk,
                    }
                    for d in diluted + basic
                ],
                "skipped": [
                    {"period": s.period, "lane": s.lane, "reason": s.reason}
                    for s in skipped
                ],
            },
        }
        db.flush()
        return imported

    def _derive_esef_metrics(self, db: Session, company: Company, document: Document) -> int:
        """Metricas derivadas de los hechos ESEF, mismo contrato que
        _derive_sec_metrics: FCF = OCF + capex (capex ya negativo), margenes
        (bruto, operativo, neto, FCF), crecimiento de revenue, tipo impositivo
        efectivo y EBITDA = EBIT + D&A. total_debt = financial_liabilities_current
        + financial_liabilities_noncurrent, SOLO cuando ambos componentes
        existen ese ejercicio (son partes disjuntas del pasivo financiero, no
        alias: la suma es contablemente correcta y queda declarada aqui).
        is_reported=False: derivadas, nunca presentadas como reportadas."""
        by_metric: dict[str, dict[int, FinancialFact]] = {}
        for fact in db.scalars(
            select(FinancialFact).where(
                FinancialFact.company_id == company.id,
                FinancialFact.source_type == "ESEF",
                FinancialFact.is_reported.is_(True),
            )
        ):
            if fact.fiscal_year is not None:
                by_metric.setdefault(fact.metric, {})[fact.fiscal_year] = fact

        def year_fact(metric: str, year: int) -> FinancialFact | None:
            return by_metric.get(metric, {}).get(year)

        def add_ratio(metric: str, numerator: FinancialFact, denominator: FinancialFact) -> int:
            if denominator.value is None or denominator.value <= 0:
                return 0
            db.add(
                FinancialFact(
                    company_id=company.id,
                    metric=metric,
                    value=numerator.value / denominator.value,
                    unit="decimal",
                    period=numerator.period,
                    fiscal_year=numerator.fiscal_year,
                    fiscal_quarter="FY",
                    source_id=document.id,
                    source_type="ESEF",
                    is_reported=False,
                    confidence=Decimal("0.85"),
                )
            )
            return 1

        derived = 0
        years = sorted({y for metric_facts in by_metric.values() for y in metric_facts})
        for year in years:
            ocf = year_fact("operating_cash_flow", year)
            capex = year_fact("capital_expenditure", year)
            revenue = year_fact("revenue", year)
            net_income = year_fact("net_income", year)
            gross_profit = year_fact("gross_profit", year)
            operating_income = year_fact("operating_income", year)
            income_before_tax = year_fact("income_before_tax", year)
            income_tax_expense = year_fact("income_tax_expense", year)
            depreciation = year_fact("depreciation_amortization", year)
            fl_current = year_fact("financial_liabilities_current", year)
            fl_noncurrent = year_fact("financial_liabilities_noncurrent", year)

            if fl_current is not None and fl_noncurrent is not None:
                db.add(
                    FinancialFact(
                        company_id=company.id,
                        metric="total_debt",
                        value=fl_current.value + fl_noncurrent.value,
                        unit="EUR",
                        period=fl_current.period,
                        fiscal_year=year,
                        fiscal_quarter="FY",
                        source_id=document.id,
                        source_type="ESEF",
                        is_reported=False,
                        confidence=Decimal("0.85"),
                    )
                )
                derived += 1

            fcf: FinancialFact | None = None
            if ocf is not None and capex is not None:
                fcf = FinancialFact(
                    company_id=company.id,
                    metric="free_cash_flow",
                    value=ocf.value + capex.value,
                    unit="EUR",
                    period=ocf.period,
                    fiscal_year=year,
                    fiscal_quarter="FY",
                    source_id=document.id,
                    source_type="ESEF",
                    is_reported=False,
                    confidence=Decimal("0.85"),
                )
                db.add(fcf)
                derived += 1
            if fcf is not None and revenue is not None and revenue.value > 0:
                derived += add_ratio("fcf_margin", fcf, revenue)
            previous_revenue = year_fact("revenue", year - 1)
            if (
                revenue is not None
                and previous_revenue is not None
                and previous_revenue.value > 0
            ):
                db.add(
                    FinancialFact(
                        company_id=company.id,
                        metric="revenue_growth",
                        value=(revenue.value / previous_revenue.value) - 1,
                        unit="decimal",
                        period=revenue.period,
                        fiscal_year=year,
                        fiscal_quarter="FY",
                        source_id=document.id,
                        source_type="ESEF",
                        is_reported=False,
                        confidence=Decimal("0.85"),
                    )
                )
                derived += 1
            if revenue is not None and revenue.value > 0:
                if gross_profit is not None:
                    derived += add_ratio("gross_margin", gross_profit, revenue)
                if operating_income is not None:
                    derived += add_ratio("operating_margin", operating_income, revenue)
                if net_income is not None:
                    derived += add_ratio("net_margin", net_income, revenue)
            if (
                income_tax_expense is not None
                and income_before_tax is not None
                and income_before_tax.value > 0
            ):
                derived += add_ratio("effective_tax_rate", income_tax_expense, income_before_tax)
            if operating_income is not None and depreciation is not None:
                db.add(
                    FinancialFact(
                        company_id=company.id,
                        metric="ebitda",
                        value=operating_income.value + depreciation.value,
                        unit="EUR",
                        period=operating_income.period,
                        fiscal_year=year,
                        fiscal_quarter="FY",
                        source_id=document.id,
                        source_type="ESEF",
                        is_reported=False,
                        confidence=Decimal("0.85"),
                    )
                )
                derived += 1
        db.flush()
        return derived

    def _source_document_sec(self, db: Session, company: Company, ticker: str) -> Document:
        title = f"SEC XBRL facts - {ticker}"
        document = db.scalar(
            select(Document).where(
                Document.company_id == company.id,
                Document.source_type == "SEC",
                Document.title == title,
            )
        )
        if document:
            return document
        document = Document(
            company_id=company.id,
            title=title,
            source_type="SEC",
            source_url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&ticker={ticker}&type=10-K",
            metadata_={"provider": "SEC", "normalized": True},
        )
        db.add(document)
        db.flush()
        return document

    def _source_document_esef(
        self, db: Session, company: Company, ticker: str, snapshot: dict[str, Any]
    ) -> Document:
        title = f"ESEF XBRL facts - {ticker}"
        document = db.scalar(
            select(Document).where(
                Document.company_id == company.id,
                Document.source_type == "ESEF",
                Document.title == title,
            )
        )
        if document:
            # A normalized snapshot has no verified filing URL. Keep its LEI,
            # filing id and hash in metadata, never fabricate a clickable URL.
            if document.source_url and linkable_source_url(document.source_url) is None:
                document.source_url = None
            return document
        document = Document(
            company_id=company.id,
            title=title,
            source_type="ESEF",
            source_url=None,
            metadata_={"provider": "ESEF", "normalized": True},
        )
        db.add(document)
        db.flush()
        return document

    def _replace_esef_data(self, db: Session, company: Company, document: Document) -> None:
        """Delete only the facts THIS document wrote (see ``_replace_sec_data``)."""
        tenant_id = db.info.get("tenant_id")
        tenant_filter = (
            FinancialFact.tenant_id == tenant_id
            if tenant_id is not None
            else FinancialFact.tenant_id.is_(None)
        )
        delete_financial_facts(
            db,
            FinancialFact.company_id == company.id,
            FinancialFact.source_id == document.id,
            tenant_filter,
        )

    def _snapshot_sec_quarters(
        self, db: Session, company: Company, document: Document
    ) -> list[dict[str, Any]]:
        """Foto de los trimestres SEC ya verificados que escribio ESTE documento.

        Solo filas ancladas a un filing (``accession_number``): las derivadas
        (FCF, margenes...) no la llevan y se recalculan en cada import.
        """
        tenant_id = db.info.get("tenant_id")
        tenant_filter = (
            FinancialFact.tenant_id == tenant_id
            if tenant_id is not None
            else FinancialFact.tenant_id.is_(None)
        )
        rows = db.scalars(
            select(FinancialFact).where(
                FinancialFact.company_id == company.id,
                FinancialFact.source_id == document.id,
                tenant_filter,
                FinancialFact.fiscal_quarter.in_(("Q1", "Q2", "Q3", "Q4")),
                FinancialFact.accession_number.is_not(None),
            )
        ).all()
        return [
            {
                "metric": r.metric,
                "value": r.value,
                "unit": r.unit,
                "period": r.period,
                "fiscal_year": r.fiscal_year,
                "fiscal_quarter": r.fiscal_quarter,
                "is_reported": r.is_reported,
                "is_adjusted": r.is_adjusted,
                "confidence": r.confidence,
                "accession_number": r.accession_number,
                "filed": r.filed,
            }
            for r in rows
        ]

    def _restore_sec_quarters(
        self,
        db: Session,
        company: Company,
        document: Document,
        prior: list[dict[str, Any]],
        new_ends_by_metric: dict[str, set[str]],
        new_unit_by_metric: dict[str, str],
    ) -> int:
        """Re-inserta trimestres verificados que quedaron FUERA de la ventana.

        Solo se restauran filas mas antiguas que el trimestre mas antiguo que
        el import actual re-escribio para esa metrica: lo que cae DENTRO de la
        ventana y el import no devolvio (p.ej. SEC lo retiro o lo corrigio)
        no resucita, y una fila nunca pisa a la nueva. Si la unidad cambio
        (otra moneda de reporte) no se mezcla con la serie nueva. Se conservan
        valor, accession y fecha de filing originales.
        """
        restored = 0
        for row in prior:
            new_ends = new_ends_by_metric.get(row["metric"])
            if not new_ends:
                continue
            if new_unit_by_metric.get(row["metric"]) != row["unit"]:
                continue
            end = str(row["period"]).split(":", 1)[0]
            if end >= min(new_ends):
                continue
            db.add(
                FinancialFact(
                    company_id=company.id,
                    source_id=document.id,
                    source_type="SEC",
                    **row,
                )
            )
            restored += 1
        if restored:
            db.flush()
        return restored

    def _replace_sec_data(
        self,
        db: Session,
        company: Company,
        document: Document,
        *,
        restated_fy_keys: list[tuple[str, str]] | None = None,
    ) -> None:
        """Delete only the facts THIS document re-authors.

        The filter used to be ``source_type == "SEC"``, which is not an
        ownership boundary: ``kpi_extraction_service.approve()`` writes
        human-approved canonical facts carrying the ingested document's
        ``source_type``, and ``thesis_evidence_service`` writes evidence facts
        with its own document. A fundamentals refresh therefore deleted
        reviewer-approved values with no trace, and left the two services
        fighting over the same rows.

        The delete is selective (F353): quarterly rows are always re-authored
        by the new import, but an annual FY row is only deleted when the new
        import re-authors that exact ``(metric, period)`` - so a restated
        figure overwrites the old one, while valid FY rows the new import
        cannot re-anchor (e.g. a previous fiscal calendar whose filings fell
        out of the submissions window) are preserved with values and
        provenance intact. Facts from other documents, sources or tenants
        are never touched. Running the same import twice is idempotent:
        the same keys are deleted and re-inserted.
        """
        tenant_id = db.info.get("tenant_id")
        tenant_filter = (
            FinancialFact.tenant_id == tenant_id
            if tenant_id is not None
            else FinancialFact.tenant_id.is_(None)
        )
        conditions = [
            FinancialFact.fiscal_quarter != "FY",
            FinancialFact.fiscal_quarter.is_(None),
            # Las derivadas (FCF, margenes, crecimiento, deuda neta) se
            # recalculan en cada import a partir de las reportadas - nuevas
            # y preservadas - asi que siempre se re-autorizan; sin esta
            # condicion un segundo refresh las duplicaria.
            FinancialFact.is_reported.is_(False),
        ]
        if restated_fy_keys:
            conditions.append(
                tuple_(FinancialFact.metric, FinancialFact.period).in_(restated_fy_keys)
            )
        delete_financial_facts(
            db,
            FinancialFact.company_id == company.id,
            FinancialFact.source_id == document.id,
            tenant_filter,
            or_(*conditions),
        )
        db.flush()

    def _add_statement(
        self,
        db: Session,
        company: Company,
        document: Document,
        statement_type: str,
        row: dict[str, Any],
    ) -> int:
        period, fiscal_year, fiscal_quarter = _period(row)
        db.add(
            FinancialStatement(
                company_id=company.id,
                statement_type=statement_type,
                period=period,
                fiscal_year=fiscal_year,
                fiscal_quarter=fiscal_quarter,
                source_id=document.id,
                facts=row,
            )
        )
        return 1

    def _drop_stale_derived(
        self, db: Session, company: Company, metric: str, period: str
    ) -> None:
        """Colapsa la capa de servicio en (metrica, periodo).

        `FinancialFact` no tiene UNIQUE en (company_id, metric, period) (la
        restriccion vive en `entities.py` + migraciones, fuera de este fix), asi
        que la base no puede defenderse sola: sin este borrado, una derivada
        vieja de OTRO proveedor (o de una corrida anterior) convive con la fila
        nueva y el mismo periodo acaba con dos `fcf_margin` de valores
        distintos (FIX5-4/FIX5-7). Se borra lo derivado (is_reported=False) de
        la clave: la fila reportada que acaba de entrar la sustituye.
        """
        tenant_id = db.info.get("tenant_id")
        tenant_filter = (
            FinancialFact.tenant_id == tenant_id
            if tenant_id is not None
            else FinancialFact.tenant_id.is_(None)
        )
        # delete_financial_facts: un DELETE crudo revienta con FK NO ACTION en
        # Postgres si el hecho ya esta referenciado (ver fact_deletion.py).
        delete_financial_facts(
            db,
            FinancialFact.company_id == company.id,
            FinancialFact.metric == metric,
            FinancialFact.period == period,
            FinancialFact.is_reported.is_(False),
            tenant_filter,
        )

    def _add_facts(
        self,
        db: Session,
        company: Company,
        document: Document,
        row: dict[str, Any],
        specs: list[MetricSpec],
        seen: set[tuple[str, str]] | None = None,
    ) -> int:
        period, fiscal_year, fiscal_quarter = _period(row)
        # FMP declara la divisa de cada estado en ``reportedCurrency`` (BABA:
        # CNY, Toyota: JPY). Antes todo se guardaba como USD y la valoracion
        # comparaba un DCF en yuanes con un precio en dolares (~7x).
        reported_currency = _iso_currency(row.get("reportedCurrency"))
        count = 0
        for metric, fmp_key, template_unit in specs:
            value = _decimal(row.get(fmp_key))
            if value is None:
                continue
            unit = _with_reporting_currency(template_unit, reported_currency)
            # Deduplicacion explicita por (metrica, periodo): dos filas del
            # payload que declaran la misma magnitud para el mismo periodo son
            # UN hecho (o un duplicado sucio del proveedor), nunca dos filas
            # (FIX5-4). Sin UNIQUE en la tabla, el colapso es responsabilidad
            # del servicio.
            if seen is not None:
                key = (metric, period)
                if key in seen:
                    continue
                seen.add(key)
            self._drop_stale_derived(db, company, metric, period)
            db.add(
                FinancialFact(
                    company_id=company.id,
                    metric=metric,
                    value=value,
                    unit=unit,
                    period=period,
                    fiscal_year=fiscal_year,
                    fiscal_quarter=fiscal_quarter,
                    source_id=document.id,
                    source_type="FMP",
                    is_reported=True,
                    confidence=Decimal("0.90"),
                )
            )
            count += 1
        return count

    def _add_derived_facts(self, db: Session, company: Company, document: Document) -> int:
        """Derivadas FMP ancladas a un unico ejercicio por par de componentes.

        Resolver cada metrica con ``latest_fact`` y despues combinarlas mezclaba
        ejercicios: OCF de FY2024 con capex de FY2025, o deuda de un ano contra
        caja del siguiente. Una deuda neta asi fabricada entra en el puente de
        equity del DCF (EV - net_debt) como valor que no consta en ningun
        Balance, y el margen sale de un FCF de un ano dividido por revenue de
        otro. Aqui cada par se resuelve dentro de su mismo ``fiscal_year`` (el
        criterio de _derive_sec_metrics) y, si a ese ano le falta uno de sus
        dos componentes, no se persiste nada: la ausencia es el estado honesto
        y el motor DCF ya la trata como ``missing`` en vez de estimar.
        """

        def ownership(fact: FinancialFact) -> tuple[int, int]:
            """Misma prioridad que latest_fact: la fuente mas autoritativa gana
            el (metrica, ano) y, a igualdad de fuente, la fila ya persistida."""
            return (SOURCE_PRIORITY.get(fact.source_type or "", 50), fact.id)

        by_metric: dict[str, dict[int, FinancialFact]] = {}
        for fact in db.scalars(
            select(FinancialFact).where(
                FinancialFact.company_id == company.id,
                FinancialFact.metric.in_(DERIVED_PAIR_METRICS),
                FinancialFact.source_type == "FMP",
                FinancialFact.fiscal_quarter == "FY",
            )
        ):
            if fact.fiscal_year is None:
                continue
            current = by_metric.setdefault(fact.metric, {}).get(fact.fiscal_year)
            if current is None or ownership(fact) < ownership(current):
                by_metric[fact.metric][fact.fiscal_year] = fact

        def year_fact(metric: str, year: int) -> FinancialFact | None:
            return by_metric.get(metric, {}).get(year)

        def already_derived(metric: str, year: int) -> bool:
            return year_fact(metric, year) is not None

        count = 0
        years = sorted({year for metric_facts in by_metric.values() for year in metric_facts})
        for year in years:
            revenue = year_fact("revenue", year)
            fcf = year_fact("free_cash_flow", year)
            if fcf is None:
                ocf = year_fact("operating_cash_flow", year)
                capex = year_fact("capital_expenditure", year)
                if ocf is not None and capex is not None and ocf.unit == capex.unit:
                    fcf = self._add_derived_fact(
                        db,
                        company,
                        document,
                        "free_cash_flow",
                        ocf.value + capex.value,
                        ocf.unit,
                        ocf.period,
                        year,
                        ocf.fiscal_quarter,
                    )
                    count += 1
            if (
                fcf is not None
                and revenue is not None
                and revenue.value > 0
                # Un margen con FCF y revenue en divisas distintas no es un dato.
                and fcf.unit == revenue.unit
                and not already_derived("fcf_margin", year)
            ):
                count += 1
                self._add_derived_fact(
                    db,
                    company,
                    document,
                    "fcf_margin",
                    fcf.value / revenue.value,
                    "decimal",
                    revenue.period,
                    year,
                    revenue.fiscal_quarter,
                )
            # El crecimiento se ancla al ano anterior EXACTO: comparar con el
            # ultimo revenue ingested (puede ser el de hace dos ejercicios) y
            # etiquetarlo FY<este> seria enunciar un dato que no existe.
            previous_revenue = year_fact("revenue", year - 1)
            if (
                revenue is not None
                and previous_revenue is not None
                and previous_revenue.value > 0
                and not already_derived("revenue_growth", year)
            ):
                count += 1
                self._add_derived_fact(
                    db,
                    company,
                    document,
                    "revenue_growth",
                    revenue.value / previous_revenue.value - Decimal("1"),
                    "decimal",
                    revenue.period,
                    year,
                    revenue.fiscal_quarter,
                )
            debt = year_fact("total_debt", year)
            cash = year_fact("cash_and_equivalents", year)
            if (
                debt is not None
                and cash is not None
                and debt.unit == cash.unit
                and not already_derived("net_debt", year)
            ):
                count += 1
                self._add_derived_fact(
                    db,
                    company,
                    document,
                    "net_debt",
                    debt.value - cash.value,
                    debt.unit,
                    debt.period,
                    year,
                    debt.fiscal_quarter,
                )
        db.flush()
        return count

    def _add_derived_fact(
        self,
        db: Session,
        company: Company,
        document: Document,
        metric: str,
        value: Decimal,
        unit: str,
        period: str,
        fiscal_year: int | None,
        fiscal_quarter: str | None,
    ) -> FinancialFact:
        """Anade la derivada y la DEVUELVE: el caller encadena derivadas (FCF ->
        margen) y necesita la fila sin releerla de la base."""
        fact = FinancialFact(
            company_id=company.id,
            metric=metric,
            value=value,
            unit=unit,
            period=period,
            fiscal_year=fiscal_year,
            fiscal_quarter=fiscal_quarter,
            source_id=document.id,
            source_type="FMP",
            is_reported=False,
            is_adjusted=True,
            confidence=Decimal("0.85"),
        )
        db.add(fact)
        return fact

    async def _add_spot_price(
        self,
        db: Session,
        company: Company,
        fmp: FMPClient,
        ticker: str,
    ) -> None:
        # Barra diaria desde /quote: fecha y volumen REALES de la cotizacion.
        # Antes se tomaba profile[0].price fechado con el dia de la ingesta:
        # un refresh financiero en fin de semana fabricaba una barra del
        # sabado/domingo con el ultimo cierre conocido. Sin timestamp del
        # proveedor no hay fecha honesta, asi que no se escribe nada.
        try:
            payload = await fmp.quote(ticker)
        except Exception:  # noqa: BLE001 - best-effort: la quote no bloquea la ingesta financiera
            return
        item = payload[0] if isinstance(payload, list) and payload else None
        if not isinstance(item, dict):
            return
        price = _decimal(item.get("price"))
        if price is None or price <= 0:
            return
        # Fallar cerrado ante payload malformado: un timestamp o volumen
        # invalidos no deben tumbar el refresh financiero tras importar facts.
        try:
            timestamp = int(item.get("timestamp") or 0)
            quote_date = datetime.fromtimestamp(timestamp, tz=UTC).date() if timestamp > 0 else None
        except (TypeError, ValueError, OverflowError, OSError):
            quote_date = None
        if quote_date is None or quote_date > datetime.now(UTC).date():
            return
        try:
            volume = int(item["volume"]) if item.get("volume") is not None else None
        except (TypeError, ValueError):
            volume = None
        existing = db.scalar(
            select(MarketPrice).where(MarketPrice.company_id == company.id, MarketPrice.date == quote_date)
        )
        if existing:
            if existing.quote_currency != (item.get("currency") or None):
                price = (
                    price_in_currency(price, quote_currency=item.get("currency"),
                                      target_currency=existing.quote_currency, company=company)
                    if existing.quote_currency and item.get("currency") else None
                )
                if price is None:
                    return
            # La fila existente es una barra real: se actualiza solo el close
            # y se preservan OHLC y el adjusted autentico de esa fecha.
            existing.close = price
            if volume is not None:
                existing.volume = volume
            existing.source = "FMP"
            return
        # Una quote spot no es una barra ajustada: adj_close queda NULL en vez
        # de copiar close, que afirmaria un ajuste nunca realizado y
        # corromperia total-return/beta/Sharpe sobre splits o dividendos.
        db.add(
            MarketPrice(
                company_id=company.id,
                date=quote_date,
                open=price,
                high=price,
                low=price,
                close=price,
                adj_close=None,
                volume=volume,
                source="FMP",
                quote_currency=item.get("currency") or None,
            )
        )

    def _add_profile_facts(
        self,
        db: Session,
        company: Company,
        document: Document,
        profile: list[dict[str, Any]],
    ) -> int:
        if not profile:
            return 0
        row = profile[0]
        period = datetime.now(UTC).date().isoformat()
        # mktCap va en la divisa de COTIZACION del perfil, no en USD. Si esa
        # divisa es una subunidad (GBp, ZAc, ILA) no se sabe si FMP la expresa
        # en peniques o en libras: no se guarda (ausencia honesta).
        raw_quote_currency = str(row.get("currency") or "").strip()
        quote_currency = (
            None
            if raw_quote_currency in {"GBp", "GBX", "ZAc", "ZAC", "ILA", "ILa"}
            else _iso_currency(raw_quote_currency) or "USD"
        )
        count = 0
        for metric, field, unit in [
            ("beta", "beta", "decimal"),
            ("market_cap", "mktCap", quote_currency),
        ]:
            if unit is None:
                continue
            value = _decimal(row.get(field))
            if value is None:
                continue
            db.add(
                FinancialFact(
                    company_id=company.id,
                    metric=metric,
                    value=value,
                    unit=unit,
                    period=period,
                    source_id=document.id,
                    source_type="FMP_profile",
                    is_reported=True,
                    is_adjusted=False,
                    confidence=Decimal("0.75"),
                )
            )
            count += 1
        return count
