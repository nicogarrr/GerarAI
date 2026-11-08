"""Backtest point-in-time del motor de TIR para el accionista (8-nov-2026).

Nico (8-nov-2026, 17:25): «Haz backtesting … con los documentos antiguos … intentar valorar y ver cómo estuvo la
valoración». Este módulo rehace, para una fecha pasada ``t``, la entrada que el motor de TIR
(:mod:`app.valuation.shareholder_irr` + :mod:`app.valuation.shareholder_irr_rules`) habría visto ese día, usando
SOLO hechos SEC presentados ANTES de ``t`` y la PRIMERA cifra publicada de cada ejercicio (no la re-expresada
después). El cálculo de escenarios y TIR es el del producto (``shareholder_irr_service.run_valuation``); aquí solo
se cambia de dónde salen los insumos (companyfacts con su fecha ``filed`` en vez de la BD actual).

Solo código determinista: ningún texto del modelo entra al backtest (el modelo «sabe» lo que pasó después).

Funciones puras: sin BD ni red. El script ``scripts/backtest_irr_pit.py`` descarga y puntúa.
"""
from __future__ import annotations

import math
import random
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import median
from typing import Any

from app.valuation import shareholder_irr as engine
from app.valuation import shareholder_irr_rules as rules

ANNUAL_FORMS = ("10-K", "10-K/A", "10-KT", "20-F", "20-F/A", "40-F", "40-F/A")
PERIODIC_FORMS = ANNUAL_FORMS + ("10-Q", "10-Q/A", "6-K")
HISTORY_YEARS = 5

#: Conceptos por métrica, en orden de prioridad. Los de flujo y acciones son los de ``SEC_METRIC_MAP`` (la
#: ingesta del producto); la deuda sigue la composición clásica (total o largo + corto) porque el agregado
#: de la ingesta mezcla reglas que dependen del filing completo.
CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue": ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
                "RevenueFromContractWithCustomerIncludingAssessedTax", "RegulatedAndUnregulatedOperatingRevenue",
                "SalesRevenueGoodsNet", "Revenue", "SalesRevenueServicesNet", "RealEstateRevenueNet",
                "RevenuesNetOfInterestExpense"),
    "operating_income": ("OperatingIncomeLoss", "ProfitLossFromOperatingActivities"),
    # respaldo del EBITDA por componentes (app.valuation.ebitda_components), mismos conceptos que la ingesta
    "income_before_tax": ("ProfitLossBeforeTax",),
    "interest_expense": ("InterestExpense", "FinanceCosts"),
    "income_tax_expense": ("IncomeTaxExpenseBenefit", "IncomeTaxExpenseContinuingOperations"),
    "net_income_total": ("ProfitLoss",),
    "finance_income_cost": ("FinanceIncomeCost",),
    "net_income_minority": ("NetIncomeLossAttributableToNoncontrollingInterest",
                            "ProfitLossAttributableToNoncontrollingInterests"),
    "net_income": ("NetIncomeLoss", "ProfitLoss", "ProfitLossAttributableToOwnersOfParent"),
    "depreciation_amortization": ("DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet",
                                  "DepreciationAndAmortization", "DepreciationAmortizationAndImpairmentLossReversalOfImpairmentLossRecognisedInProfitOrLoss",
                                  "DepreciationAndAmortisationExpense", "AdjustmentsForDepreciationAndAmortisationExpense"),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",
                            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
                            "CashFlowsFromUsedInOperatingActivities"),
    "capital_expenditure": ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
                            "PaymentsToAcquireOilAndGasPropertyAndEquipment",
                            "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"),
    "dividends_paid": ("PaymentsOfDividends", "PaymentsOfDividendsCommonStock",
                       "DividendsPaidClassifiedAsFinancingActivities"),
    "common_stock_repurchased": ("PaymentsForRepurchaseOfCommonStock", "PaymentsToAcquireOrRedeemEntitysShares"),
    "acquisitions": ("PaymentsToAcquireBusinessesNetOfCashAcquired", "PaymentsToAcquireBusinessesGross",
                     "CashFlowsUsedInObtainingControlOfSubsidiariesOrOtherBusinessesClassifiedAsInvestingActivities"),
    "stock_based_compensation": ("ShareBasedCompensation",),
    "eps_diluted": ("EarningsPerShareDiluted", "DilutedEarningsLossPerShare"),
    "shares_diluted": ("WeightedAverageNumberOfDilutedSharesOutstanding",
                       "WeightedAverageNumberOfSharesOutstandingDiluted", "AdjustedWeightedAverageShares"),
    # balance (instantáneos)
    "cash": ("CashAndCashEquivalentsAtCarryingValue",
             "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "CashAndCashEquivalents"),
    "short_term_investments": ("ShortTermInvestments", "MarketableSecuritiesCurrent",
                               "AvailableForSaleSecuritiesDebtSecuritiesCurrent"),
    "debt_total": ("LongTermDebt", "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities",
                   "DebtLongtermAndShorttermCombinedAmount", "Borrowings"),
    "debt_noncurrent": ("LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations",
                        "NoncurrentPortionOfNoncurrentBorrowings", "LongtermBorrowings"),
    "debt_current": ("LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent", "DebtCurrent",
                     "CurrentPortionOfLongtermBorrowings", "CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings"),
    "short_borrowings": ("ShortTermBorrowings", "CommercialPaper", "ShorttermBorrowings"),
    "minority_interest": ("MinorityInterest", "NoncontrollingInterests"),
    "lease_liabilities": ("LeaseLiabilities",),
    "lease_liabilities_current": ("CurrentLeaseLiabilities",),
    "lease_liabilities_noncurrent": ("NoncurrentLeaseLiabilities",),
    # portada del 10-K/10-Q (dei): acciones en circulación a la fecha de la portada
    "shares_cover": ("EntityCommonStockSharesOutstanding",),
}
#: Métrica del backtest → métrica de la ingesta del producto: sus conceptos van PRIMERO y en su orden.
_PRODUCT_METRIC = {"revenue": "revenue", "operating_income": "operating_income", "net_income": "net_income",
                   "income_before_tax": "income_before_tax", "interest_expense": "interest_expense",
                   "income_tax_expense": "income_tax_expense", "net_income_total": "net_income_total",
                   "finance_income_cost": "finance_income_cost", "net_income_minority": "net_income_minority",
                   "depreciation_amortization": "depreciation_amortization",
                   "operating_cash_flow": "operating_cash_flow", "capital_expenditure": "capital_expenditure",
                   "dividends_paid": "dividends_paid", "common_stock_repurchased": "common_stock_repurchased",
                   "acquisitions": "acquisitions", "stock_based_compensation": "stock_based_compensation",
                   "shares_diluted": "shares_diluted", "eps_diluted": "eps_diluted",
                   "cash": "cash_and_equivalents", "short_term_investments": "short_term_investments",
                   "minority_interest": "minority_interest"}
# pérdidas: el emisor etiqueta acciones y BPA «básico y diluido» en un único concepto
CONCEPTS["shares_diluted"] += ("WeightedAverageNumberOfShareOutstandingBasicAndDiluted",)
CONCEPTS["eps_diluted"] += ("EarningsPerShareBasicAndDiluted",)


def _merge_product_concepts() -> None:
    from app.services.financial_ingestion_service import SEC_IFRS_METRIC_MAP, SEC_METRIC_MAP

    prod = {m: list(c) for m, c, _ in SEC_METRIC_MAP}
    ifrs = {m: list(c) for m, c, _ in SEC_IFRS_METRIC_MAP}  # 20-F/40-F con ifrs-full (BN, CNQ, TSM…)
    for ours, theirs in _PRODUCT_METRIC.items():
        CONCEPTS[ours] = tuple(dict.fromkeys([*prod.get(theirs, []), *ifrs.get(theirs, []), *CONCEPTS[ours]]))
    # IFRS: el beneficio atribuible a la dominante va antes que el consolidado (ProfitLoss incluye minoritarios;
    # en US GAAP NetIncomeLoss ya es el atribuible y sigue primero)
    ni = [c for c in CONCEPTS["net_income"] if c != "ProfitLossAttributableToOwnersOfParent"]
    ni.insert(1, "ProfitLossAttributableToOwnersOfParent")
    CONCEPTS["net_income"] = tuple(ni)


_merge_product_concepts()
INSTANT = {"cash", "short_term_investments", "debt_total", "debt_noncurrent", "debt_current",
           "short_borrowings", "minority_interest", "lease_liabilities", "lease_liabilities_current",
           "lease_liabilities_noncurrent", "shares_cover"}
COVER_RATIO_BOUNDS = (0.5, 2.0)
UNITS = ("USD", "CAD", "EUR", "GBP", "TWD", "shares", "USD/shares", "CAD/shares", "TWD/shares", "EUR/shares")


class LookAheadError(AssertionError):
    """Un hecho presentado en o después de la fecha de valoración ha llegado a la entrada."""


@dataclass(frozen=True)
class Fact:
    metric: str
    concept: str
    priority: int
    start: date | None
    end: date
    value: float
    filed: date
    form: str
    unit: str


def _d(s: str | None) -> date | None:
    return date.fromisoformat(s[:10]) if s else None


def facts_from_companyfacts(payload: Mapping[str, Any]) -> list[Fact]:
    """Hechos de un JSON companyfacts de la SEC (us-gaap, ifrs-full, dei), solo de formularios periódicos."""
    out: list[Fact] = []
    nss = payload.get("facts", {})
    for metric, concepts in CONCEPTS.items():
        for pri, concept in enumerate(concepts):
            for ns in ("us-gaap", "ifrs-full", "dei"):
                node = nss.get(ns, {}).get(concept)
                if not node:
                    continue
                for unit, vals in node.get("units", {}).items():
                    if unit not in UNITS:
                        continue
                    for v in vals:
                        if v.get("form") not in PERIODIC_FORMS or v.get("val") is None:
                            continue
                        end, filed = _d(v.get("end")), _d(v.get("filed"))
                        if end is None or filed is None:
                            continue
                        out.append(Fact(metric, concept, pri, _d(v.get("start")), end, float(v["val"]),
                                        filed, v["form"], unit))
    return out


def as_of(facts: Iterable[Fact], t: date) -> list[Fact]:
    """Solo lo presentado estrictamente antes de ``t`` (un 10-K presentado el día ``t`` no cuenta)."""
    seen = [f for f in facts if f.filed < t]
    assert_point_in_time(seen, t)
    return seen


def assert_point_in_time(facts: Iterable[Fact], t: date) -> None:
    late = [f for f in facts if f.filed >= t]
    if late:
        f = late[0]
        raise LookAheadError(f"{len(late)} hechos presentados en o después de {t}: p. ej. {f.concept} {f.end} "
                             f"presentado {f.filed}")


def _first_published(rows: Sequence[Fact]) -> Fact:
    return min(rows, key=lambda f: (f.filed, f.priority))


def annual(facts: Sequence[Fact], metric: str) -> dict[int, float]:
    """{año de cierre: valor en millones} con la primera cifra publicada del concepto de mayor prioridad
    disponible ese ejercicio. Solo periodos de 340–380 días de formularios anuales."""
    by_end: dict[date, list[Fact]] = {}
    for f in facts:
        if f.metric != metric or f.start is None or f.form not in ANNUAL_FORMS:
            continue
        if not 340 <= (f.end - f.start).days <= 380:
            continue
        by_end.setdefault(f.end, []).append(f)
    out: dict[int, float] = {}
    ends = sorted(by_end)
    for i, end in enumerate(ends):
        if i + 1 < len(ends) and (ends[i + 1] - end).days < 300:
            continue  # cambio de cierre: se queda el último de dos cierres cercanos
        rows = by_end[end]
        best = min(f.priority for f in rows)
        f = _first_published([r for r in rows if r.priority == best])
        out[end.year] = f.value / 1e6
    return dict(sorted(out.items()))


def annual_end(facts: Sequence[Fact], metric: str, year: int) -> date | None:
    ends = [f.end for f in facts if f.metric == metric and f.start is not None and f.end.year == year
            and 340 <= (f.end - f.start).days <= 380]
    return max(ends) if ends else None


def instant(facts: Sequence[Fact], metric: str, ref: date | None = None, tol_days: int = 100
            ) -> tuple[float | None, date | None]:
    """Último cierre de balance presentado (primera cifra publicada a esa fecha), en millones. Con ``ref``,
    solo cuenta si cae a menos de ``tol_days`` del cierre de referencia."""
    rows = [f for f in facts if f.metric == metric and f.start is None]
    if not rows:
        return None, None
    end = max(f.end for f in rows)
    if ref is not None and abs((end - ref).days) > tol_days:
        return None, None
    at = [f for f in rows if f.end == end]
    best = min(f.priority for f in at)
    return _first_published([f for f in at if f.priority == best]).value / 1e6, end


def split_factor(splits: Sequence[tuple[date, float]], after: date, upto: date) -> float:
    """Producto de los splits con fecha en (after, upto]."""
    k = 1.0
    for d, r in splits:
        if after < d <= upto and r > 0:
            k *= r
    return k


def price_on(series: Sequence[tuple[date, float]], t: date) -> tuple[float | None, date | None]:
    """Último cierre en o antes de ``t`` (sin mirar después)."""
    best = None
    for d, v in series:
        if d <= t and v is not None and math.isfinite(v):
            best = (v, d)
        elif d > t:
            break
    return best if best else (None, None)


def total_return(adj: Sequence[tuple[date, float]], t: date, years: int) -> float | None:
    """Rentabilidad anual total (dividendos incluidos vía cierre ajustado) de ``t`` a ``t + years``."""
    p0, d0 = price_on(adj, t)
    try:
        end = date(t.year + years, t.month, t.day)
    except ValueError:  # 29 de febrero
        end = date(t.year + years, t.month, 28)
    if p0 is None or not adj or adj[-1][0] < end - timedelta(days=7):
        return None
    p1, d1 = price_on(adj, end)
    if p1 is None or d1 is None or d1 < end - timedelta(days=7) or p0 <= 0:
        return None
    return (p1 / p0) ** (1 / years) - 1


@dataclass
class Inputs:
    start: engine.StartingPoint
    history: rules.History
    method: dict[str, Any]
    fy_end: date
    shares_split_factor: float = 1.0
    warnings: list[str] = field(default_factory=list)


def build_inputs(facts: Sequence[Fact], *, t: date, price: float, splits: Sequence[tuple[date, float]],
                 financial: bool, currency: str = "USD") -> Inputs:
    """Mismo punto de partida que ``shareholder_irr_service.starting_point`` pero con hechos anteriores a ``t``.

    ``price`` es el cierre que cotizaba en ``t`` (no ajustado por splits posteriores)."""
    from app.services.shareholder_irr_service import choose_method

    assert_point_in_time(facts, t)
    rev = annual(facts, "revenue")
    years = sorted(rev)[-HISTORY_YEARS:]
    if not years:
        raise ValueError("sin ingresos anuales")
    last = years[-1]
    series = {m: annual(facts, m) for m in ("operating_income", "depreciation_amortization", "net_income",
                                             "income_before_tax", "interest_expense", "income_tax_expense",
                                             "net_income_total", "finance_income_cost", "net_income_minority",
                                             "operating_cash_flow", "capital_expenditure", "dividends_paid",
                                             "common_stock_repurchased", "acquisitions",
                                             "stock_based_compensation", "shares_diluted", "eps_diluted")}

    def s(m: str) -> list[float | None]:
        return [series[m].get(y) for y in years]

    from app.valuation import ebitda_components as ec

    oi, da = s("operating_income"), s("depreciation_amortization")
    pbt = [ec.pretax_income(income_before_tax=p, profit_loss=pl, income_tax_expense=tx)
           for p, pl, tx in zip(s("income_before_tax"), s("net_income_total"), s("income_tax_expense"), strict=True)]
    fin, nfr = s("interest_expense"), s("finance_income_cost")
    # misma función que la app (shareholder_irr_service.starting_point)
    ebitda = [ec.ebitda_from_components(operating_income=o, depreciation_amortization=d, income_before_tax=p,
                                        interest_expense=f, net_finance_result=nf)[0]
              for o, d, p, f, nf in zip(oi, da, pbt, fin, nfr, strict=True)]
    revenue = [rev.get(y) for y in years]
    net_income = s("net_income")
    method = choose_method(revenue=revenue[-1], ebitda_years=ebitda, net_income=net_income[-1],
                           financial=financial, segment_ebitda=False)
    basis = "pe" if method["chosen"] == "tir_per" else "ev_ebitda"
    shares = series["shares_diluted"].get(last)
    warnings: list[str] = []
    if shares is None:  # como el producto: beneficio / BPA diluido del mismo ejercicio (derivado)
        eps = series["eps_diluted"].get(last)
        if eps and net_income[-1]:
            shares = net_income[-1] / (eps * 1e6)
            warnings.append("acciones diluidas derivadas como beneficio / BPA diluido")
        if not shares or shares <= 0:
            raise ValueError("sin acciones diluidas del último ejercicio")
    fy_end = annual_end(facts, "revenue", last) or date(last, 12, 31)
    k = split_factor(splits, fy_end, t)
    shares *= k
    # control con la portada presentada antes de t: un emisor que etiqueta acciones «en miles» sin escala
    # (p. ej. 9.609 en vez de 9.609.000) daría una capitalización 1.000 veces menor
    cover, cover_end = instant(facts, "shares_cover")
    if cover and cover_end:
        cover *= split_factor(splits, cover_end, t)
        lo_r, hi_r = COVER_RATIO_BOUNDS
        if not lo_r <= cover / shares <= hi_r:
            warnings.append(f"acciones diluidas {shares:.3f} M incoherentes con la portada {cover:.3f} M "
                            f"({cover_end}): se usa la portada")
            shares = cover
    cash, bal_end = instant(facts, "cash")
    sti, _ = instant(facts, "short_term_investments", bal_end)
    tot, _ = instant(facts, "debt_total", bal_end)
    nc, _ = instant(facts, "debt_noncurrent", bal_end)
    cu, _ = instant(facts, "debt_current", bal_end)
    stb, _ = instant(facts, "short_borrowings", bal_end)
    mi, _ = instant(facts, "minority_interest", bal_end)
    leases = None
    if currency != "USD":  # como el producto: arrendamientos en deuda solo con EBITDA IFRS 16
        leases, _ = instant(facts, "lease_liabilities", bal_end)
        if leases is None:
            lc, _ = instant(facts, "lease_liabilities_current", bal_end)
            ln, _ = instant(facts, "lease_liabilities_noncurrent", bal_end)
            leases = (lc or 0.0) + (ln or 0.0) if (lc is not None or ln is not None) else None
    debt = max(tot or 0.0, (nc or 0.0) + (cu or 0.0)) + (stb or 0.0)
    if all(x is None for x in (tot, nc, cu)):
        warnings.append("deuda sin dato: se toma 0")
    if cash is None:
        # Sin caja la deuda neta sería deuda − 0: valor inventado. La observación se descarta con su motivo
        # (el llamador lo cuenta, como «sin ingresos anuales»).
        raise ValueError("caja sin dato en el último balance")
    sp = engine.StartingPoint(
        price=float(price), shares_diluted=shares, revenue=revenue[-1] or 0.0, ebitda=ebitda[-1],
        net_income=net_income[-1], cash=cash + (sti if sti is not None else 0.0), debt=debt, leases=leases or 0.0,
        minorities=(mi or 0.0) if basis != "pe" else 0.0, currency=currency, basis=basis,
    )
    ocf, capex_s, acq = s("operating_cash_flow"), s("capital_expenditure"), s("acquisitions")
    if basis == "pe":  # misma regla que la app (app.valuation.attributable); aquí solo con la parte del beneficio
        from app.valuation.attributable import attributable_shares, scale_flows

        nn = [None] * len(years)
        shares_attr = attributable_shares(net_income, s("net_income_minority"), nn, nn)
        if any(x is not None and x[0] < 1.0 for x in shares_attr):
            ocf, capex_s, acq = (scale_flows(v, shares_attr) for v in (ocf, capex_s, acq))
            warnings.append("minoritarios: flujos consolidados a la parte del accionista")
    hist = rules.History(
        years=years, revenue=revenue, earnings=net_income if basis == "pe" else ebitda,
        operating_cash_flow=ocf, capex=capex_s,
        dividends=s("dividends_paid"), buybacks=s("common_stock_repurchased"), acquisitions=acq,
        sbc=series["stock_based_compensation"].get(last),
    )
    return Inputs(sp, hist, method, fy_end, k, warnings)


def value(inp: Inputs, *, peer_multiples: Sequence[float] = ()) -> dict[str, Any]:
    """TIR a 5 y 10 años por escenario con el cálculo del producto (sin guía: no hay guía point-in-time)."""
    from app.services.shareholder_irr_service import run_valuation

    if inp.method["chosen"] == "sotp":
        raise ValueError("el motor no da TIR (método suma de partes: sin EBITDA ni beneficio positivo)")
    out = run_valuation(inp.start, inp.history, peer_multiples=peer_multiples, guidance_growth=None)
    res: dict[str, Any] = {"basis": inp.start.basis, "multiple": inp.start.multiple}
    for k in rules.SCENARIOS:
        res[k] = out["scenarios"][k]["horizons"]["5"]["irr"]
        res[k + "_10"] = out["scenarios"][k]["horizons"]["10"]["irr"]
    res["weighted"] = (out["weighted"].get("5") or {}).get("irr") if isinstance(out["weighted"].get("5"), dict) \
        else out["weighted"].get("5")
    return res


# ---------- métricas ----------

def _ranks(x: Sequence[float]) -> list[float]:
    order = sorted(range(len(x)), key=lambda i: x[i])
    r = [0.0] * len(x)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and x[order[j + 1]] == x[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def rank_ic(pred: Sequence[float], real: Sequence[float]) -> float | None:
    """Correlación de Spearman."""
    if len(pred) < 3:
        return None
    a, b = _ranks(list(pred)), _ranks(list(real))
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True))
    den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
    return num / den if den else None


def newey_west_t(series: Sequence[float], lags: int) -> float:
    """t de la media con varianza HAC (Bartlett) de Newey-West."""
    n = len(series)
    m = sum(series) / n
    e = [x - m for x in series]
    g0 = sum(x * x for x in e) / n
    var = g0
    for lag in range(1, min(lags, n - 1) + 1):
        g = sum(e[i] * e[i - lag] for i in range(lag, n)) / n
        var += 2 * (1 - lag / (lags + 1)) * g
    if var <= 0:
        return 0.0 if abs(m) < 1e-12 else math.copysign(math.inf, m)
    return m / math.sqrt(var / n)


def block_bootstrap_ci(series: Sequence[float], *, block: int, n: int = 2000, seed: int = 20261108,
                       q: tuple[float, float] = (0.025, 0.975)) -> tuple[float, float]:
    """Intervalo de la media por bootstrap de bloques móviles (respeta el solapamiento de horizontes)."""
    rnd = random.Random(seed)
    x = list(series)
    L = max(1, min(block, len(x)))
    starts = list(range(len(x) - L + 1))
    means = []
    for _ in range(n):
        s: list[float] = []
        while len(s) < len(x):
            i = rnd.choice(starts)
            s.extend(x[i:i + L])
        means.append(sum(s[:len(x)]) / len(x))
    means.sort()
    return means[int(q[0] * (n - 1))], means[int(q[1] * (n - 1))]


def med(x: Iterable[float]) -> float | None:
    v = [a for a in x if a is not None]
    return median(v) if v else None
