"""Lectura compartida del histórico de cambios de analistas de Yahoo.

``yf.Ticker(symbol).upgrades_downgrades`` es la misma tabla para el
histórico de objetivos (:mod:`app.services.analyst_history_service`), los
objetivos vigentes (:mod:`app.services.analyst_targets_service`) y el
colector de notas de analistas
(:mod:`app.services.analyst_note_collector`). Antes cada servicio repetía
la llamada y el recorrido de filas con su propio subconjunto de columnas;
aquí queda una sola lectura con el superset de campos que usan los tres y
cada servicio proyecta las claves que su contrato interno espera.
"""

from __future__ import annotations

from typing import Any


def fetch_upgrades_downgrades_records(ticker: Any) -> list[dict[str, Any]]:
    """Filas de ``ticker.upgrades_downgrades`` con el superset de campos usado en la app.

    Recibe el ``yf.Ticker`` ya construido para no duplicar conexiones cuando
    el llamante consulta más datos del mismo símbolo.
    """
    frame: Any = ticker.upgrades_downgrades
    records: list[dict[str, Any]] = []
    if frame is not None and len(frame) > 0:
        for index, item in frame.iterrows():
            records.append(
                {
                    "date": index,
                    "firm": item.get("Firm"),
                    "to_grade": item.get("ToGrade"),
                    "from_grade": item.get("FromGrade"),
                    "action": item.get("Action"),
                    "price_target_action": item.get("priceTargetAction"),
                    "price_target": item.get("currentPriceTarget"),
                    "prior_target": item.get("priorPriceTarget"),
                }
            )
    return records
