"""Escenarios de valoración declarados en datos, por emisor.

Los lee el motor de escenarios (``app/valuation/engines/scenario_engine.py``)
para las empresas cuyo modelo declarado es de la familia de escenarios,
capacidad o cartera de pedidos (p. ej. «scenario_auto_energy_fsd»). Es un
fichero de DATOS, como ``company_master.py`` o la tabla de ratios ADR: ningún
código decide nada por ticker. Sin entrada, el motor usa su juego por defecto
(bajista/base/alcista derivado de las entradas de la propia empresa).

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
motivo en ``trace.engine_fallback``): probabilidades en (0, 1] que suman 1
(±0,01), nombres únicos, método ``dcf`` o ``forward_multiple``, múltiplo > 0,
año entre 1 y 10, y ningún escenario toca el WACC ni la g terminal.

Vacío a propósito: las cifras por empresa necesitan fuente y las aprueba Nico.
"""

from __future__ import annotations

from typing import Any

VALUATION_SCENARIOS: dict[str, dict[str, Any]] = {}
