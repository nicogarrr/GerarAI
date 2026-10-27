"""Esqueleto NEUTRAL de avisos de nivel de entrada (1-4) para la watchlist.

Esta pieza NO calcula niveles. La regla que convierte precios en un nivel es una
decision de producto que aun no existe: `LevelProvider` es la unica costura y no
hay implementacion por defecto (sin proveedor, no hay avisos). No hay umbrales,
ni periodicidad, ni mapeo a zonas de ningun producto externo.

Garantias que si fija este modulo, con independencia de la regla:
- Solo niveles enteros 1..4; cualquier otro valor se rechaza (no se redondea).
- Cada lectura declara modelo (version), fuente y fecha de datos y estado
  (provisional o confirmed); el criterio de esos estados lo fija el modelo
  validado, no este modulo. Un estado fuera de esos dos valores se rechaza.
- Un aviso solo sale al SUBIR a un nivel >= ``min_level`` (por defecto 2) desde
  el nivel actual guardado del ticker. Bajar de nivel (incluido salir de la
  zona a 1) actualiza el estado SIN avisar, asi que volver a subir avisa de
  nuevo. Repetir la misma lectura es idempotente: no genera nada.
- La huella es por MES de senal: el mismo nivel en el mismo mes no se repite
  aunque la lectura provisional cambie de dia.
- Sin lectura (None) no se inventa estado: ni aviso ni cambio del ultimo nivel.
- El texto es un aviso informativo con su fuente de regla; nunca una orden.
- No envia nada: devuelve eventos y texto; el envio vive en otra capa.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date
from typing import Protocol

VERSION = "entry-level-alert-v2"
MIN_LEVEL = 1
MAX_LEVEL = 4
DEFAULT_MIN_LEVEL = 2  # 1 = nivel normal: por si solo no merece aviso


STATUSES = ("provisional", "confirmed")


class LevelRuleNotConfigured(RuntimeError):
    """No hay regla de nivel definida: el sistema no inventa una."""


@dataclass(frozen=True)
class LevelReading:
    """Lectura de un proveedor para un ticker en una fecha de senal."""

    ticker: str
    level: int
    signal_date: date
    close: float | None
    rule_source: str  # nombre de la regla que la produjo, visible al usuario
    model_version: str = "sin-version"  # version exacta del modelo; sin ella no hay trazabilidad
    data_source: str = "sin-fuente"  # origen de los datos de precio usados
    data_as_of: date | None = None  # fecha de los ultimos datos usados
    status: str = "sin-estado"  # "provisional" | "confirmed"; el criterio lo define el modelo validado


@dataclass(frozen=True)
class EntryEvent:
    reading: LevelReading
    previous_level: int | None
    fingerprint: str


class LevelProvider(Protocol):
    def read(self, ticker: str) -> LevelReading | None:
        """Nivel actual del ticker, o None si no hay dato fiable."""


def validate_level(level: object) -> int:
    if isinstance(level, bool) or not isinstance(level, int) or not MIN_LEVEL <= level <= MAX_LEVEL:
        raise ValueError(f"nivel fuera de {MIN_LEVEL}..{MAX_LEVEL}: {level!r}")
    return level


def signal_period(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def fingerprint(tenant_id: int, reading: LevelReading) -> str:
    """Clave de idempotencia: tenant, ticker, nivel, MES de senal, version y estado."""
    raw = (
        f"{VERSION}:{tenant_id}:{reading.ticker.upper()}:{reading.level}:"
        f"{signal_period(reading.signal_date)}:{reading.model_version}:{reading.status}"
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def plan_events(
    tenant_id: int,
    readings: list[LevelReading | None],
    last_levels: Mapping[str, int],
    *,
    min_level: int = DEFAULT_MIN_LEVEL,
) -> tuple[list[EntryEvent], dict[str, int]]:
    """Eventos por subida de nivel y el estado actualizado.

    `last_levels` es el ultimo nivel LEIDO por ticker (no solo el avisado), asi
    el estado sabe cuando un ticker salio de su zona. No se muta.
    Avisa solo si el nivel nuevo es >= `min_level` y mayor que el guardado (o
    no habia estado). Las bajadas solo actualizan el estado.
    """
    min_level = validate_level(min_level)
    state = dict(last_levels)
    events: list[EntryEvent] = []
    seen: set[str] = set()
    for reading in readings:
        if reading is None:
            continue  # sin dato: no se inventa estado
        ticker = reading.ticker.strip().upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        level = validate_level(reading.level)
        if reading.status not in STATUSES:
            raise ValueError(f"estado invalido (provisional|confirmed): {reading.status!r}")
        previous = state.get(ticker)
        state[ticker] = level
        if previous == level:
            continue
        if level < min_level or (previous is not None and level < previous):
            continue  # bajada o nivel bajo el minimo: estado al dia, sin aviso
        normalized = replace(reading, ticker=ticker, level=level)
        events.append(
            EntryEvent(
                reading=normalized,
                previous_level=previous,
                fingerprint=fingerprint(tenant_id, normalized),
            )
        )
    return events, state


def collect_readings(provider: LevelProvider | None, tickers: list[str]) -> list[LevelReading | None]:
    if provider is None:
        raise LevelRuleNotConfigured("no hay regla de nivel configurada")
    return [provider.read(t) for t in tickers]


def render_email(event: EntryEvent) -> tuple[str, str]:
    """(asunto, cuerpo) en texto plano. Informativo; sin orden de compra ni venta."""
    r = event.reading
    subject = f"{r.ticker} entra en nivel {r.level}"
    prev = "sin aviso previo" if event.previous_level is None else f"antes: nivel {event.previous_level}"
    close = "sin dato" if r.close is None else f"{r.close:.2f}"
    body = "\n".join(
        [
            f"{r.ticker} ha entrado en el nivel {r.level} (de {MIN_LEVEL} a {MAX_LEVEL}; {MAX_LEVEL} es el mas alto).",
            f"Historial: {prev}.",
            f"Fecha de senal: {r.signal_date.isoformat()}",
            f"Cierre: {close}",
            f"Estado: {r.status}",
            f"Regla: {r.rule_source} (modelo {r.model_version})",
            f"Datos: {r.data_source}"
            + ("" if r.data_as_of is None else f", hasta {r.data_as_of.isoformat()}"),
            "",
            "Es un aviso informativo de tu watchlist, no una recomendacion ni una orden de compra o venta.",
        ]
    )
    return subject, body
