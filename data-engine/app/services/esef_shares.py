"""Acciones medias para emisores ESEF, derivadas del propio filing (IAS 33).

Medido 2026-10-29 contra los 105 emisores ES reviewed (ultimo filing con
xBRL-JSON en filings.xbrl.org, base scope): 0/105 etiquetan
WeightedAverageNumberOf*Shares; 102/105 declaran
ifrs-full:ProfitLossAttributableToOwnersOfParent, 63/105 BPA diluido anual
en EUR y 73/105 BPA basico. IAS 33: BPA = beneficio atribuido (ajustado) /
numero medio ponderado de acciones, asi que n = beneficio / BPA es la media
ponderada del ejercicio.

DOS VIAS, nunca mezcladas (revision del piloto 2026-10-29):

- ``shares_diluted`` SOLO desde ifrs-full:DilutedEarningsLossPerShare. El
  numerador del BPA diluido puede llevar ajustes (convertibles,
  preferentes) que el beneficio atribuido no recoge: cuando el filing
  declara ademas BPA basico y difiere del diluido mas alla del redondeo,
  la derivacion es aproximada y queda SEnALADA
  (``numerator_adjustment_risk`` en metadata, confidence 0.6).
- ``shares_basic_derived`` desde ifrs-full:BasicEarningsLossPerShare cuando
  no hay BPA diluido. beneficio/BPA basico da acciones BASICAS, no
  diluidas: es una metrica distinta, solo informativa y siempre marcada
  como derivada/aproximada. El DCF NO la acepta: la equivalencia con
  acciones diluidas solo se podria acreditar con un BPA diluido igual, y
  entonces la via diluida ya existe.

Guardas comunes (cada una observada en la medicion): solo beneficio
ATRIBUIDO a la dominante (el total con minoritarios inflaria las acciones
de holdings); BPA en la misma divisa que el beneficio (un emisor declara el
BPA en AED: fuera); BPA != 0; signos coherentes; cota de redondeo del BPA
<= 2 % segun sus ``decimals`` (con 2 decimales y BPA 0,11 la cota ya es
4,5 %); sin ``decimals`` no hay cota calculable y se rechaza.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

MAX_REL_ERROR = Decimal("0.02")

# Conceptos usados (verificados presentes en la medicion citada).
ATTRIBUTABLE_PROFIT_CONCEPT = "ifrs-full:ProfitLossAttributableToOwnersOfParent"
DILUTED_EPS_CONCEPT = "ifrs-full:DilutedEarningsLossPerShare"
BASIC_EPS_CONCEPT = "ifrs-full:BasicEarningsLossPerShare"
EPS_UNIT = "iso4217:EUR/xbrli:shares"
PROFIT_UNIT = "iso4217:EUR"

DILUTED_METRIC = "shares_diluted"
BASIC_METRIC = "shares_basic_derived"

DERIVATION_FORMULA = (
    "shares = ifrs-full:ProfitLossAttributableToOwnersOfParent / BPA (IAS 33); "
    "shares_diluted solo con BPA diluido, shares_basic_derived solo con BPA "
    "basico; cota de error = medio ulp del BPA segun sus decimals / |BPA|"
)


@dataclass(frozen=True, slots=True)
class ShareDerivation:
    period: str               # cierre inclusivo ISO (p.ej. "2025-12-31")
    shares: Decimal           # acciones medias ponderadas, redondeadas a unidad
    profit: Decimal
    eps: Decimal
    eps_decimals: int
    rel_error_bound: Decimal
    lane: str                 # "diluted" | "basic"
    # True cuando el filing declara BPA basico distinto del diluido mas alla
    # del redondeo: el numerador del BPA diluido puede llevar ajustes de
    # convertibles/preferentes que el beneficio atribuido no recoge.
    numerator_adjustment_risk: bool = False


@dataclass(frozen=True, slots=True)
class ShareSkip:
    period: str
    lane: str
    reason: str


def _dec(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return out if out.is_finite() else None


def _eps_decimals(entry: dict) -> int | None:
    raw = entry.get("decimals")
    if raw is None or str(raw).upper() in {"INF", "INFINITY"}:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _derive_period(
    period: str, profit_entry: dict, eps_entry: dict, lane: str,
    *, max_rel_error: Decimal,
) -> ShareDerivation | ShareSkip:
    profit = _dec(profit_entry.get("val"))
    eps = _dec(eps_entry.get("val"))
    if profit is None:
        return ShareSkip(period, lane, "beneficio_atribuido_no_numerico")
    if eps is None:
        return ShareSkip(period, lane, "bpa_no_numerico")
    if eps == 0:
        return ShareSkip(period, lane, "bpa_cero")
    if profit * eps <= 0:
        return ShareSkip(period, lane, "signo_incoherente_beneficio_bpa")
    decimals = _eps_decimals(eps_entry)
    if decimals is None:
        return ShareSkip(period, lane, "bpa_sin_decimals")
    bound = (Decimal(10) ** -decimals / 2) / abs(eps)
    if bound > max_rel_error:
        return ShareSkip(period, lane, f"redondeo_bpa_{bound:.2%}_supera_{max_rel_error:.0%}")
    shares = (profit / eps).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if shares <= 0:
        return ShareSkip(period, lane, "acciones_no_positivas")
    return ShareDerivation(
        period=period, shares=shares, profit=profit, eps=eps,
        eps_decimals=decimals, rel_error_bound=bound, lane=lane,
    )


def _beyond_rounding(a: Decimal, a_dec: int | None, b: Decimal, b_dec: int | None) -> bool:
    """True si dos BPA difieren mas que la suma de sus cotas de redondeo."""
    half_ulp = Decimal(0)
    for value, dec in ((a, a_dec), (b, b_dec)):
        half_ulp += Decimal(10) ** -(dec if dec is not None else 0) / 2
    return abs(a - b) > half_ulp


def derive_shares(
    profit_by_period: dict[str, dict],
    diluted_eps_by_period: dict[str, dict],
    basic_eps_by_period: dict[str, dict],
    *,
    max_rel_error: Decimal = MAX_REL_ERROR,
) -> tuple[list[ShareDerivation], list[ShareDerivation], list[ShareSkip]]:
    """Deriva acciones medias por periodo desde periodos ya fusionados.

    Entradas: salidas de ``_merge_esef_periods`` (periodo -> entrada con
    ``val`` y ``decimals``); el caller ya filtro base scope, duracion anual
    y unidad EUR. Devuelve (derivadas_diluidas, derivadas_basicas, skips).
    Un periodo con BPA diluido NUNCA usa el basico; el basico solo cubre
    periodos sin diluido. Periodos sin solape beneficio/BPA no se reportan
    aqui: la cobertura por metrica ya la declara el mapa de ingesta.
    """
    diluted: list[ShareDerivation] = []
    basic: list[ShareDerivation] = []
    skipped: list[ShareSkip] = []
    for period in sorted(set(profit_by_period) & set(diluted_eps_by_period)):
        result = _derive_period(
            period, profit_by_period[period], diluted_eps_by_period[period],
            "diluted", max_rel_error=max_rel_error,
        )
        if isinstance(result, ShareSkip):
            skipped.append(result)
            continue
        basic_entry = basic_eps_by_period.get(period)
        if basic_entry is not None:
            basic_eps = _dec(basic_entry.get("val"))
            if basic_eps is not None and _beyond_rounding(
                result.eps, result.eps_decimals, basic_eps, _eps_decimals(basic_entry)
            ):
                result = replace(result, numerator_adjustment_risk=True)
        diluted.append(result)
    for period in sorted(
        (set(profit_by_period) & set(basic_eps_by_period)) - set(diluted_eps_by_period)
    ):
        result = _derive_period(
            period, profit_by_period[period], basic_eps_by_period[period],
            "basic", max_rel_error=max_rel_error,
        )
        if isinstance(result, ShareSkip):
            skipped.append(result)
        else:
            basic.append(result)
    return diluted, basic, skipped
