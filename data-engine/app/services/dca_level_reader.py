"""Lectura del nivel DCA por ticker, con degradación limpia («sin nivel»).

El motor DCA (``dca_signal_engine`` + tabla ``dca_signal_states``) llega en su
propia PR. Esta costura deja que los consumidores (Cerebro, cartera, inicio)
lo lean YA sin depender de ella:

* si el modelo ``DcaSignalState`` no existe en ``app.models`` (motor aún no
  mergeado) o la tabla no está migrada, ``read_dca_levels`` devuelve ``None``:
  el consumidor dice «sin nivel DCA», nunca inventa uno;
* si existe, devuelve el último veredicto guardado por símbolo, sin recalcular.

Cuando el motor esté en ``main`` no hay que tocar nada aquí.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

# Copia de las etiquetas del motor por si ``dca_signal_engine`` no está; si
# está, mandan las suyas (``ZONES``).
_FALLBACK_ZONES: dict[int, dict[str, str]] = {
    4: {"label": "4X DCA", "zone": "Zona de compra extrema"},
    3: {"label": "3X DCA", "zone": "Zona de compra fuerte"},
    2: {"label": "2X DCA", "zone": "Zona de compra"},
    1: {"label": "1X DCA", "zone": "Zona de aportacion normal"},
    -1: {"label": "RECORTE LIGERO", "zone": "Zona de recorte ligero"},
    -2: {"label": "RECORTE FUERTE", "zone": "Zona de recorte fuerte"},
}
NO_LEVEL_TEXT = "sin nivel"


@dataclass(frozen=True)
class DcaLevelReading:
    symbol: str
    level: int
    label: str
    zone: str
    status: str
    period: str
    signal_date: date | None
    close: float | None
    currency: str | None
    params_version: str | None
    evaluated_at: datetime | None

    @property
    def forming(self) -> bool:
        return self.status == "forming"


def _state_model() -> Any | None:
    import app.models as models

    return getattr(models, "DcaSignalState", None)


def _zones() -> dict[int, dict[str, str]]:
    try:
        engine = importlib.import_module("app.services.dca_signal_engine")
    except Exception:  # noqa: BLE001 - motor no disponible en esta rama
        return _FALLBACK_ZONES
    zones = getattr(engine, "ZONES", None)
    return zones if isinstance(zones, dict) else _FALLBACK_ZONES


def dca_engine_available() -> bool:
    return _state_model() is not None


def read_dca_levels(
    db: Session, tenant: int, symbols: list[str] | None = None
) -> dict[str, DcaLevelReading] | None:
    """Último nivel DCA por símbolo del tenant; ``None`` si el motor no está."""
    model = _state_model()
    if model is None:
        return None
    query = select(model).where(model.tenant_id == tenant)
    if symbols:
        query = query.where(model.symbol.in_([s.strip().upper() for s in symbols if s.strip()]))
    try:
        rows = db.scalars(query).all()
    except SQLAlchemyError:
        # Modelo presente pero tabla sin migrar: igual que «sin motor».
        db.rollback()
        return None
    zones = _zones()
    out: dict[str, DcaLevelReading] = {}
    for row in rows:
        level = int(row.level)
        zone = zones.get(level) or zones.get(1) or _FALLBACK_ZONES[1]
        out[str(row.symbol).upper()] = DcaLevelReading(
            symbol=str(row.symbol).upper(),
            level=level,
            label=str(zone.get("label", f"{level}X DCA")),
            zone=str(zone.get("zone", "")),
            status=str(row.status or ""),
            period=str(row.period or ""),
            signal_date=row.signal_date,
            close=float(row.close) if row.close is not None else None,
            currency=row.currency,
            params_version=row.params_version,
            evaluated_at=row.evaluated_at,
        )
    return out
