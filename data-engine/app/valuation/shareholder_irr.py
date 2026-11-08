"""Motor determinista de TIR para el accionista (tesis de nivel comité, 8-nov-2026).

Nico (8-nov-2026, 14:13): «Que hagamos tesis así» (Numantia, Eurofins y Brookfield). El método de esas
tesis es la TIR que obtiene quien compra hoy la acción, a 5 y 10 años, bajo tres escenarios, y de dónde
sale esa TIR. Aquí TODO lo calcula el código; el modelo solo elige entre opciones dadas.

Función pura: no lee BD ni red. Entra un :class:`StartingPoint` (precio, acciones diluidas, deuda neta,
híbridos, arrendamientos, EBITDA o beneficio de partida, cada uno con su fuente) y unos :class:`Drivers`
por escenario; sale la proyección año a año, la TIR a 5 y 10 años y su descomposición EXACTA:

    TIR = crecimiento orgánico + margen + M&A + cambio de múltiplo + desapalancamiento + recompras + dividendo

Regla de la descomposición (fija, documentada en :func:`decompose`): el valor por acción pasa de P0 a PN
por pasos encadenados (orgánico → margen → M&A → múltiplo → deuda → acciones). La TCAC del precio se
reparte entre pasos en proporción a ln(V_i / V_{i-1}) (en proporción a la diferencia si algún paso deja el
patrimonio en ≤ 0) y el dividendo es la TIR menos esa TCAC. Por construcción la suma da la TIR total.

Dos bases (``basis``):
* ``ev_ebitda``: empresa operativa. EV = múltiplo × EBITDA; patrimonio = EV − deuda neta − híbridos − minoritarios.
* ``pe``: holding/financiera (la deuda es de las filiales, el EBITDA consolidado no es del accionista):
  precio = P/B° × beneficio por acción; no hay paso de deuda.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from typing import Any

ENGINE_VERSION = "shareholder-irr-v1"
HORIZONS = (5, 10)
COMPONENTS = ("organico", "margen", "mna", "multiplo", "deuda", "recompras", "dividendo")
COMPONENT_LABELS = {
    "organico": "Crecimiento orgánico",
    "margen": "Mejora de margen",
    "mna": "Adquisiciones (M&A)",
    "multiplo": "Cambio de múltiplo",
    "deuda": "Desapalancamiento",
    "recompras": "Recompras",
    "dividendo": "Dividendo",
}


@dataclass(frozen=True)
class StartingPoint:
    """Punto de partida normalizado. Importes en millones de ``currency``; acciones en millones."""

    price: float
    shares_diluted: float
    revenue: float
    ebitda: float | None  # base ev_ebitda
    net_income: float | None = None  # base pe
    cash: float = 0.0
    debt: float = 0.0
    leases: float = 0.0  # arrendamientos en deuda (solo si el EBITDA es posterior a IFRS 16)
    hybrids: float = 0.0  # capital híbrido tratado como deuda económica
    minorities: float = 0.0
    currency: str = "USD"
    basis: str = "ev_ebitda"  # ev_ebitda | pe
    sources: Mapping[str, str] = field(default_factory=dict)

    @property
    def market_cap(self) -> float:
        return self.price * self.shares_diluted

    @property
    def net_debt(self) -> float:
        return self.debt + self.leases - self.cash

    @property
    def claims(self) -> float:
        """Todo lo que va por delante del accionista ordinario además de la deuda neta."""
        return self.hybrids + self.minorities

    @property
    def enterprise_value(self) -> float:
        return self.market_cap + self.net_debt + self.claims

    @property
    def multiple(self) -> float | None:
        """Múltiplo de partida: EV/EBITDA (ev_ebitda) o PER (pe)."""
        if self.basis == "pe":
            return self.market_cap / self.net_income if self.net_income and self.net_income > 0 else None
        return self.enterprise_value / self.ebitda if self.ebitda and self.ebitda > 0 else None

    @property
    def margin(self) -> float | None:
        base = self.net_income if self.basis == "pe" else self.ebitda
        return base / self.revenue if base is not None and self.revenue > 0 else None


@dataclass(frozen=True)
class Drivers:
    """Palancas de un escenario (tasas anuales en tanto por uno)."""

    organic_growth: float  # años 1–5
    organic_growth_late: float  # años 6–10
    mna_spend_pct_revenue: float = 0.0  # gasto anual en adquisiciones / ingresos del año anterior
    mna_multiple: float | None = None  # EV/EBITDA pagado por lo comprado (None → el múltiplo de partida)
    margin_target: float | None = None  # margen (EBITDA o neto) al que se llega en el año 5 (None → constante)
    cash_conversion: float = 0.5  # flujo libre para el accionista / EBITDA (o / beneficio en pe)
    dividend_payout: float = 0.0  # parte del flujo libre (tras M&A) que va a dividendo
    buyback_payout: float = 0.0  # parte que va a recompras; el resto, a deuda
    sbc_dilution: float = 0.0  # emisión bruta anual de acciones (remuneración en acciones)
    exit_multiple: float = 10.0


@dataclass(frozen=True)
class YearRow:
    year: int
    revenue: float
    margin: float
    earnings: float  # EBITDA (ev_ebitda) o beneficio neto (pe)
    free_cash_flow: float
    mna_spend: float
    dividends: float
    buybacks: float
    net_debt: float
    shares: float
    buyback_price: float
    dividend_per_share: float


@dataclass(frozen=True)
class HorizonResult:
    years: int
    exit_price: float
    irr: float | None
    price_cagr: float | None
    components: dict[str, float]
    dividends_per_share: float
    exit_multiple: float
    exit_earnings: float
    exit_net_debt: float
    exit_shares: float
    method: str  # log | linear


def _interp(a: float, b: float, t: int, n: int) -> float:
    return a + (b - a) * min(t, n) / n


def _equity(sp: StartingPoint, multiple: float, earnings: float, net_debt: float) -> float:
    if sp.basis == "pe":
        return multiple * earnings
    return multiple * earnings - net_debt - sp.claims


def project(sp: StartingPoint, d: Drivers, years: int = 10) -> list[YearRow]:
    """Proyección anual. Las recompras se ejecutan al precio implícito del año (múltiplo interpolado
    linealmente entre el de partida y el de salida), así que recomprar barato rinde más que caro."""
    m0 = sp.multiple
    if m0 is None:
        raise ValueError("sin múltiplo de partida (EBITDA o beneficio ≤ 0)")
    margin0 = sp.margin or 0.0
    target = margin0 if d.margin_target is None else d.margin_target
    mna_mult = d.mna_multiple or m0
    rev, net_debt, shares = sp.revenue, (0.0 if sp.basis == "pe" else sp.net_debt), sp.shares_diluted
    rows: list[YearRow] = []
    for t in range(1, years + 1):
        g = d.organic_growth if t <= 5 else d.organic_growth_late
        margin = _interp(margin0, target, t, 5)
        mna_spend = max(d.mna_spend_pct_revenue, 0.0) * rev
        acquired = (mna_spend / mna_mult / margin) if (mna_spend > 0 and margin > 0) else 0.0
        rev = rev * (1 + g) + acquired
        earnings = rev * margin
        fcf = d.cash_conversion * earnings
        distributable = fcf - mna_spend
        dividends = max(distributable, 0.0) * d.dividend_payout
        buybacks = max(distributable, 0.0) * d.buyback_payout
        if sp.basis != "pe":
            net_debt = net_debt - (distributable - dividends - buybacks)
        multiple_t = _interp(m0, d.exit_multiple, t, years)
        shares_pre = shares * (1 + d.sbc_dilution)
        price_t = _equity(sp, multiple_t, earnings, net_debt) / shares_pre if shares_pre > 0 else 0.0
        bought = buybacks / price_t if price_t > 0 else 0.0
        shares = max(shares_pre - bought, shares_pre * 0.5)  # nunca se recompra más de media empresa en un año
        rows.append(YearRow(t, rev, margin, earnings, fcf, mna_spend, dividends, buybacks, net_debt, shares,
                            price_t, dividends / shares if shares > 0 else 0.0))
    return rows


def irr(cashflows: Sequence[float]) -> float | None:
    """TIR anual por bisección (determinista). cashflows[0] es la compra (negativa)."""
    def npv(r: float) -> float:
        return sum(cf / (1 + r) ** i for i, cf in enumerate(cashflows))

    lo, hi = -0.99, 3.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if f_lo * f_mid <= 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def _no_growth(d: Drivers) -> Drivers:
    return replace(d, organic_growth=0.0, organic_growth_late=0.0)


def decompose(sp: StartingPoint, d: Drivers, rows: Sequence[YearRow], n: int, total_irr: float | None
              ) -> tuple[dict[str, float], str, float | None]:
    """Reparto exacto de la TIR entre las palancas (ver docstring del módulo)."""
    last = rows[n - 1]
    m0 = sp.multiple or 0.0
    margin0 = sp.margin or 0.0
    rev0 = sp.revenue
    org = math.prod((1 + (d.organic_growth if t <= 5 else d.organic_growth_late)) for t in range(1, n + 1))
    e_org = rev0 * org * margin0
    e_margin = rev0 * org * last.margin
    e_n = last.earnings
    nd0 = 0.0 if sp.basis == "pe" else sp.net_debt
    s0 = sp.shares_diluted
    chain = [
        _equity(sp, m0, (sp.net_income if sp.basis == "pe" else sp.ebitda) or 0.0, nd0) / s0,
        _equity(sp, m0, e_org, nd0) / s0,
        _equity(sp, m0, e_margin, nd0) / s0,
        _equity(sp, m0, e_n, nd0) / s0,
        _equity(sp, d.exit_multiple, e_n, nd0) / s0,
        _equity(sp, d.exit_multiple, e_n, last.net_debt) / s0,
        _equity(sp, d.exit_multiple, e_n, last.net_debt) / last.shares,
    ]
    keys = ("organico", "margen", "mna", "multiplo", "deuda", "recompras")
    p0, pn = chain[0], chain[-1]
    comps: dict[str, float] = dict.fromkeys(COMPONENTS, 0.0)
    if total_irr is None or p0 <= 0:
        return comps, "none", None
    price_cagr = (pn / p0) ** (1 / n) - 1 if pn > 0 else -1.0
    if all(v > 0 for v in chain) and abs(math.log(pn / p0)) > 1e-12:
        total_log = math.log(pn / p0)
        for i, k in enumerate(keys):
            comps[k] = price_cagr * math.log(chain[i + 1] / chain[i]) / total_log
        method = "log"
    elif abs(pn - p0) > 1e-12:
        for i, k in enumerate(keys):
            comps[k] = price_cagr * (chain[i + 1] - chain[i]) / (pn - p0)
        method = "linear"
    else:
        method = "flat"
    comps["dividendo"] = total_irr - price_cagr
    return comps, method, price_cagr


def evaluate(sp: StartingPoint, d: Drivers, horizons: Sequence[int] = HORIZONS) -> dict[int, HorizonResult]:
    out: dict[int, HorizonResult] = {}
    for n in horizons:
        rows = project(sp, d, n)
        last = rows[-1]
        exit_price = max(_equity(sp, d.exit_multiple, last.earnings, last.net_debt) / last.shares, 0.0)
        flows = [-sp.price] + [r.dividend_per_share for r in rows]
        flows[-1] += exit_price
        total = irr(flows)
        comps, method, cagr = decompose(sp, d, rows, n, total)
        out[n] = HorizonResult(n, exit_price, total, cagr, comps, sum(r.dividend_per_share for r in rows),
                               d.exit_multiple, last.earnings, last.net_debt, last.shares, method)
    return out


def sensitivity(sp: StartingPoint, d: Drivers, growths: Sequence[float], multiples: Sequence[float],
                years: int = 5) -> list[list[float | None]]:
    """TIR a ``years`` para cada (crecimiento orgánico constante, múltiplo de salida); resto del escenario igual."""
    table: list[list[float | None]] = []
    for g in growths:
        row = []
        for m in multiples:
            dd = replace(d, organic_growth=g, organic_growth_late=g, exit_multiple=m)
            row.append(evaluate(sp, dd, (years,))[years].irr)
        table.append(row)
    return table


def weighted(results: Mapping[str, Mapping[int, HorizonResult]], probabilities: Mapping[str, float], n: int
             ) -> float | None:
    """TIR ponderada por probabilidad (media ponderada de las TIR, como en las tesis de referencia)."""
    total = 0.0
    for key, p in probabilities.items():
        value = results[key][n].irr
        if value is None:
            return None
        total += p * value
    return total


def value_at_rate(sp: StartingPoint, d: Drivers, rate: float, years: int = 10) -> float | None:
    """Valor por acción hoy si se exige ``rate`` (coste del capital): dividendos y precio de salida del
    escenario descontados a esa tasa. Es el precio al que la TIR del escenario sería exactamente ``rate``."""
    if rate <= -1:
        return None
    rows = project(sp, d, years)
    last = rows[-1]
    exit_price = max(_equity(sp, d.exit_multiple, last.earnings, last.net_debt) / last.shares, 0.0)
    pv = sum(r.dividend_per_share / (1 + rate) ** r.year for r in rows)
    return pv + exit_price / (1 + rate) ** years


def as_dict(obj: Any) -> Any:
    return asdict(obj)


__all__ = [
    "COMPONENTS",
    "COMPONENT_LABELS",
    "ENGINE_VERSION",
    "Drivers",
    "HorizonResult",
    "StartingPoint",
    "YearRow",
    "decompose",
    "evaluate",
    "irr",
    "project",
    "sensitivity",
    "value_at_rate",
    "weighted",
]
