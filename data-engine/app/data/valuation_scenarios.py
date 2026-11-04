"""Escenarios de valoración declarados en datos, por emisor.

Los lee el motor de escenarios (``app/valuation/engines/scenario_engine.py``)
para las empresas cuyo modelo declarado es de la familia de escenarios,
capacidad o cartera de pedidos (p. ej. «scenario_auto_energy_fsd»). Es un
fichero de DATOS, como ``company_master.py`` o la tabla de ratios ADR: ningún
código decide nada por ticker. Sin entrada (o sin fuente) no hay valor por
escenarios: no existe juego por defecto (Nico, 4-nov-2026: «Que tengan
escenarios reales, no hardcodeo»). El motor vuelve al que correría sin él y la
traza dice «escenarios pendientes: sin escenarios con fuente».

Formato de cada entrada (clave = ticker en mayúsculas)::

    "TICKER": {
        "source": "de dónde salen las cifras (informe, fecha, URL)",
        "scenarios": [
            # DCF con las mismas piezas que el DCF estándar (plan, puente,
            # WACC y g terminal resueltos); sustituye crecimiento y/o margen.
            {"name": "core", "probability": 0.6, "method": "dcf",
             "revenue_growth": 0.08, "fcf_margin": 0.09},
            # Múltiplo sobre una métrica futura: FCF de los años 1..year +
            # múltiplo x métrica del año ``year`` (``revenue`` o ``fcf``),
            # descontados al WACC del DCF base.
            {"name": "robotaxi", "probability": 0.1, "method": "forward_multiple",
             "metric": "revenue", "multiple": 6.0, "year": 5,
             "revenue_growth": 0.30, "fcf_margin": 0.15},
        ],
    }

Reglas que valida el motor (si falla una, respaldo al motor actual con el
motivo en ``trace.engine_fallback``): ``source`` no vacío, probabilidades en (0, 1] que suman 1
(±0,01), nombres únicos, método ``dcf`` o ``forward_multiple``, múltiplo > 0,
año entre 1 y 10, y ningún escenario toca el WACC ni la g terminal.

Las referencias generales de crecimiento ([-15 %, 45 %]) y margen FCF (50 %)
NO son rechazo (decisión de Nico, 4-nov-2026): un supuesto con fuente fuera de
referencia corre y queda avisado en la traza y en la ficha. Lo que no tiene
fuente no se declara.

TSLA (decisión de Nico, 4-nov-2026, 19:09: «sin topes, el valor real», con la
salvedad de que cada cifra tenga fuente): estructura bear/base/bull y pesos de
ARK Invest, «ARK's Expected Share Price For Tesla In 2031» (19-oct-2026):
bear = percentil 25 de su Monte Carlo, bull = percentil 75, base = media.
Crecimientos = CAGR de ventas de SU tabla (2025A 95 BUSD -> 2031E 1.202 /
1.449 / 1.622 BUSD): (1202/95)^(1/6)-1 = 0,526500; (1449/95)^(1/6)-1 =
0,574795; (1622/95)^(1/6)-1 = 0,604678. ARK no publica margen FCF: los
escenarios heredan el margen base de TSLA (regla del motor), no uno derivado.
El motor valora con su WACC, su plan y una trayectoria única de crecimiento:
NO reproduce los objetivos de ARK (3.300/4.400/5.000 USD, modelo por
segmentos con robotaxi/Optimus y descuento propio).
"""

from __future__ import annotations

from typing import Any

VALUATION_SCENARIOS: dict[str, dict[str, Any]] = {
    "TSLA": {
        "source": (
            "ARK Invest, «ARK's Expected Share Price For Tesla In 2031», 19-oct-2026, "
            "https://www.ark-invest.com/articles/valuation-models/arks-expected-share-price-for-tesla-2031 "
            "(pesos: percentiles 25/50/75 de su Monte Carlo; crecimientos: CAGR de las ventas "
            "de su tabla 2025A->2031E; margen FCF: no publicado por ARK, se hereda el base de TSLA)"
        ),
        "scenarios": [
            {
                "name": "bear",
                "probability": 0.25,
                "method": "dcf",
                "revenue_growth": 0.526500,
                "description": (
                    "ARK p25: ventas 2031E 1.202 BUSD (CAGR 52,6 % desde 95 BUSD en 2025A). "
                    "Margen FCF: base de TSLA (ARK no publica margen FCF)."
                ),
            },
            {
                "name": "base",
                "probability": 0.50,
                "method": "dcf",
                "revenue_growth": 0.574795,
                "description": (
                    "ARK media: ventas 2031E 1.449 BUSD (CAGR 57,5 % desde 95 BUSD en 2025A). "
                    "Margen FCF: base de TSLA (ARK no publica margen FCF)."
                ),
            },
            {
                "name": "bull",
                "probability": 0.25,
                "method": "dcf",
                "revenue_growth": 0.604678,
                "description": (
                    "ARK p75: ventas 2031E 1.622 BUSD (CAGR 60,5 % desde 95 BUSD en 2025A). "
                    "Margen FCF: base de TSLA (ARK no publica margen FCF)."
                ),
            },
        ],
    },
}
