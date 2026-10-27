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
- Un aviso solo sale al ENTRAR en un nivel distinto del ultimo avisado de ese
  ticker. Repetir la misma lectura es idempotente: no genera nada.
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

VERSION = "entry-level-alert-v1"
MIN_LEVEL = 1
MAX_LEVEL = 4


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


def fingerprint(tenant_id: int, reading: LevelReading) -> str:
    """Clave de idempotencia: tenant, ticker, nivel, fecha de senal, version y estado."""
    raw = (
        f"{VERSION}:{tenant_id}:{reading.ticker.upper()}:{reading.level}:"
        f"{reading.signal_date.isoformat()}:{reading.model_version}:{reading.status}"
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def plan_events(
    tenant_id: int,
    readings: list[LevelReading | None],
    last_notified: Mapping[str, int],
) -> tuple[list[EntryEvent], dict[str, int]]:
    """Eventos por entrada en un nivel nuevo y el estado actualizado.

    `last_notified` es el ultimo nivel avisado por ticker. No se muta.
    """
    state = dict(last_notified)
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
        if previous == level:
            continue
        normalized = replace(reading, ticker=ticker, level=level)
        events.append(
            EntryEvent(
                reading=normalized,
                previous_level=previous,
                fingerprint=fingerprint(tenant_id, normalized),
            )
        )
        state[ticker] = level
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
