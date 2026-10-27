"""Proveedor de niveles 1-4 para el esqueleto ``entry_level_alerts`` (PR #2258).

Conecta el motor DCA (``dca_signal_engine``) con la costura ``LevelProvider``
del esqueleto neutral de avisos de nivel, sin modificarlo:

* nivel 1..4 = multiplo DCA del motor (1X..4X). Las zonas de recorte del motor
  no existen en el esqueleto (solo 1..4): se leen como nivel 1 (aportacion
  normal) y se conservan en ``trim_level`` para quien las quiera mostrar.
* ``status``: mes en formacion -> ``provisional``; mes cerrado -> ``confirmed``.
* ``model_version`` = ``DcaParams.version``; ``data_source`` = origen de barras.

El import del esqueleto es perezoso: si ese modulo aun no esta en la rama, este
proveedor sigue importando y ``read`` lanza ``RuntimeError`` explicito.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.services.dca_signal_engine import (
    DEFAULT_PARAMS,
    DailyBar,
    DcaParams,
    MonthlyVerdict,
    current_verdict,
)

RULE_SOURCE = "Formula DCA de Nico (motor dca_signal_engine)"

BarsLoader = Callable[[str], tuple[Iterable[DailyBar], str] | None]


def reading_level(verdict: MonthlyVerdict) -> int:
    """Nivel 1..4 del esqueleto: los recortes cuentan como aportacion normal."""
    return verdict.level if verdict.level >= 1 else 1


@dataclass
class DcaEngineLevelProvider:
    """Implementa ``entry_level_alerts.LevelProvider`` con el motor DCA.

    ``load_bars(ticker)`` devuelve ``(barras_diarias, fuente)`` o ``None`` si no
    hay datos fiables (sin dato no se inventa lectura).
    """

    load_bars: BarsLoader
    params: DcaParams = DEFAULT_PARAMS
    today: date | None = None

    def verdict(self, ticker: str) -> tuple[MonthlyVerdict, str] | None:
        loaded = self.load_bars(ticker)
        if loaded is None:
            return None
        bars, source = loaded
        verdict = current_verdict(bars, params=self.params, today=self.today)
        if verdict is None:
            return None
        return verdict, source

    def read(self, ticker: str) -> Any:
        try:
            from app.services.entry_level_alerts import LevelReading
        except ImportError as exc:  # pragma: no cover - depende de la rama
            raise RuntimeError("entry_level_alerts no esta disponible en esta rama") from exc
        found = self.verdict(ticker)
        if found is None:
            return None
        verdict, source = found
        return LevelReading(
            ticker=ticker.strip().upper(),
            level=reading_level(verdict),
            signal_date=verdict.signal_date,
            close=verdict.close,
            rule_source=RULE_SOURCE,
            model_version=self.params.version,
            data_source=source,
            data_as_of=verdict.signal_date,
            status="provisional" if verdict.status == "forming" else "confirmed",
        )
