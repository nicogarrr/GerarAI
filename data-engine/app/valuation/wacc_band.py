"""WACC del DCF estándar por banda de capitalización bursátil (en USD).

Owner (Nico, 4-nov-2026, 11:40 Madrid): «Mete todo lo que mejores resultados
tenga». Los dos backtests point-in-time sin lookahead (82 empresas de EE. UU.,
3.314 valoraciones trimestrales 2015–2026; elegido con 2015–20 y validado con
2021–26) muestran que descontar con una banda por tamaño ordena mejor que el
WACC por CAPM/beta en los dos periodos (IC a 24 m −0,051/−0,061 → +0,076/+0,072;
work/gerarai-backtest1 y work/gerarai-backtest2, REPORT.md). Afinar los cortes
o los niveles fue sobreajuste (243 combinaciones, correlación entre periodos
−0,78), así que la banda va EXACTA y sin suelo ni ajuste macro:

- capitalización >= 200.000 M$: 8,5 %;
- 50.000 – 200.000 M$: 9,5 %;
- 10.000 – 50.000 M$: 10,5 %;
- < 10.000 M$: 11,5 %.

Cada corte pertenece a la banda de arriba (exactamente 200.000 M$ = 8,5 %).
La capitalización es precio × acciones diluidas del DCF, en la divisa de
reporte (el servicio ya tradujo el precio), convertida a USD con el tipo de
cambio point-in-time de la fecha del precio. Sin precio, sin acciones, sin
divisa de reporte o sin tipo de cambio NO se adivina: el motor sigue con el
WACC de siempre (CAPM trazable / inferido / por defecto) y la traza dice por
qué. El CAPM se sigue calculando y viaja en la traza solo como información.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.valuation.currency import reporting_currencies, resolve_fx

WACC_POLICY_MARKET_CAP_BAND = "market_cap_band"
WACC_POLICY_FALLBACK = "fallback_previous_rate"
WACC_SOURCE_MARKET_CAP_BAND = "market_cap_band"

MILLION = 1_000_000.0
# (capitalización mínima en millones de USD, WACC). De mayor a menor; el
# primer umbral que se alcanza manda. NO afinar: ver el docstring del módulo.
WACC_MARKET_CAP_BANDS_USD_M: tuple[tuple[float, float], ...] = (
    (200_000.0, 0.085),
    (50_000.0, 0.095),
    (10_000.0, 0.105),
    (0.0, 0.115),
)


def band_wacc_for_market_cap(market_cap_usd: float) -> tuple[float, str]:
    """(WACC, etiqueta de la banda) para una capitalización en USD (> 0)."""
    cap_m = market_cap_usd / MILLION
    bands = WACC_MARKET_CAP_BANDS_USD_M
    for index, (floor_m, rate) in enumerate(bands):
        if cap_m >= floor_m:
            ceiling = bands[index - 1][0] if index > 0 else None
            if ceiling is None:
                label = f">= {floor_m:,.0f} M$"
            elif floor_m <= 0:
                label = f"< {ceiling:,.0f} M$"
            else:
                label = f"{floor_m:,.0f} – {ceiling:,.0f} M$"
            return rate, label
    # Inalcanzable con un último umbral 0 y capitalización positiva.
    return bands[-1][1], f"< {bands[-2][0]:,.0f} M$"


@dataclass
class BandWacc:
    """Resultado de la banda: ``wacc`` None = no aplicable (ver ``reason``)."""

    wacc: float | None
    band: str | None = None
    market_cap_usd: float | None = None
    market_cap_reporting: float | None = None
    reporting_currency: str | None = None
    fx: dict[str, Any] | None = None
    reason: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def trace(self) -> dict[str, Any]:
        return {
            "policy": WACC_POLICY_MARKET_CAP_BAND if self.wacc is not None else WACC_POLICY_FALLBACK,
            "wacc": self.wacc,
            "band": self.band,
            "market_cap_usd": self.market_cap_usd,
            "market_cap_reporting_currency": self.market_cap_reporting,
            "reporting_currency": self.reporting_currency,
            "fx": self.fx,
            "fallback_reason": self.reason,
            "bands_usd_m": [list(item) for item in WACC_MARKET_CAP_BANDS_USD_M],
        }


def resolve_band_wacc(
    db: Any,
    *,
    price: float | None,
    shares: float | None,
    fact_units: list[str | None],
    on: date,
) -> BandWacc:
    """WACC por banda de capitalización, o la razón de no poder aplicarla.

    ``price`` va en la divisa de reporte y en la base de acciones del DCF
    (ordinarias); ``fact_units`` son las unidades de los hechos del snapshot.
    """
    if price is None or not price > 0:
        return BandWacc(None, reason="sin precio: no hay capitalización para elegir la banda")
    if shares is None or not shares > 0:
        return BandWacc(None, reason="sin acciones diluidas: no hay capitalización")
    currencies = reporting_currencies(fact_units)
    if len(currencies) != 1:
        return BandWacc(
            None,
            reason=(
                "divisa de reporte desconocida o mezclada: no se convierte la "
                "capitalización a USD"
            ),
        )
    currency = next(iter(currencies))
    market_cap = float(price) * float(shares)
    if currency == "USD":
        rate, fx_trace = 1.0, None
    else:
        quote = resolve_fx(db, currency, "USD", on) if db is not None else None
        if quote is None:
            return BandWacc(
                None,
                market_cap_reporting=market_cap,
                reporting_currency=currency,
                reason=(
                    f"sin tipo de cambio {currency}/USD a {on.isoformat()}: no se "
                    "adivina la capitalización en USD"
                ),
            )
        rate, fx_trace = quote.rate, quote.as_trace()
    market_cap_usd = market_cap * rate
    wacc, band = band_wacc_for_market_cap(market_cap_usd)
    return BandWacc(
        wacc,
        band=band,
        market_cap_usd=market_cap_usd,
        market_cap_reporting=market_cap,
        reporting_currency=currency,
        fx=fx_trace,
    )
