"""Piezas puras del backtest PIT sin sesgo de supervivencia (sin DB, sin red, sin imports de la app).

* ``ExitEvent``/``load_exits``: altas/bajas/quiebras con retorno de salida.
* ``Membership``: universo historico por fecha (quien estaba en el indice en el mes t).
* ``exit_value``: lo que recupera una posicion al salir (quiebra = 0 salvo dato).
* ``is_delisted``: baja real vs hueco de datos vs fin de datos.
* ``eligible_at``: elegibilidad conocida EN t0 (sin mirar precios futuros).
* ``walk_forward_folds``/``cost_adjusted``: evaluacion fuera de muestra reproducible con costes.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

KINDS = ("bankruptcy", "delist_loss", "acquired", "merged", "unknown")
# Retorno de salida por defecto SOLO cuando el CSV no trae cifra. Conservador: la baja
# sin dato se trata como perdida total (cota inferior); la cota superior es 0.0.
DEFAULT_EXIT_RETURN = {
    "bankruptcy": -1.0,
    "delist_loss": -0.5,
    "acquired": 0.0,
    "merged": 0.0,
    "unknown": -1.0,
}


@dataclass(frozen=True)
class ExitEvent:
    symbol: str
    last_month: int  # indice de mes (year*12+month-1) del ultimo cierre negociado
    kind: str
    exit_return: float  # sobre el ultimo cierre; -1.0 = pierde todo


def _month(label: str) -> int:
    y, m = label.split("-")[:2]
    return int(y) * 12 + int(m) - 1


def load_exits(path: Path) -> dict[str, ExitEvent]:
    """CSV ``symbol,last_month(YYYY-MM),kind[,exit_return]``. Sin cifra -> DEFAULT_EXIT_RETURN."""
    out: dict[str, ExitEvent] = {}
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            kind = (row.get("kind") or "unknown").strip()
            if kind not in KINDS:
                raise ValueError(f"kind desconocido {kind!r} para {row.get('symbol')}")
            raw = (row.get("exit_return") or "").strip()
            ret = float(raw) if raw else DEFAULT_EXIT_RETURN[kind]
            if ret < -1.0:
                raise ValueError(f"exit_return < -100 % para {row['symbol']}")
            sym = row["symbol"].strip()
            out[sym] = ExitEvent(sym, _month(row["last_month"]), kind, ret)
    return out


@dataclass(frozen=True)
class Membership:
    """Intervalos [start, end] (meses, extremos incluidos; end None = sigue) por simbolo."""

    spans: dict[str, list[tuple[int, int | None]]]

    @classmethod
    def from_csv(cls, path: Path) -> Membership:
        spans: dict[str, list[tuple[int, int | None]]] = {}
        with open(path, newline="") as fh:
            for row in csv.DictReader(fh):
                end = (row.get("end") or "").strip()
                spans.setdefault(row["symbol"].strip(), []).append(
                    (_month(row["start"]), _month(end) if end else None)
                )
        return cls(spans)

    def has(self, symbol: str, t: int) -> bool:
        return any(a <= t and (b is None or t <= b) for a, b in self.spans.get(symbol, []))

    def at(self, t: int) -> list[str]:
        return sorted(s for s in self.spans if self.has(s, t))


def is_delisted(
    t: int, last_month: int | None, data_end: int, event: ExitEvent | None, *, grace: int = 1
) -> bool:
    """Baja real en el mes t: ya no hay precios despues de last_month Y (hay evento o la serie
    acaba antes del fin de los datos). Un hueco con precios posteriores NO es baja; el fin de
    los datos tampoco (evita tratar el corte del CSV como quiebra)."""
    if last_month is None or t <= last_month:
        return False
    if event is not None:
        return True
    return last_month < data_end - grace


def exit_value(
    shares: float, last_px: float, event: ExitEvent | None, *, cost: float, unknown: float
) -> float:
    """Caja recuperada. Sin evento: ``unknown`` (-1.0 cota inferior, 0.0 superior). Perdida total = 0."""
    ret = event.exit_return if event is not None else unknown
    gross = shares * last_px * (1.0 + ret)
    return max(gross, 0.0) * (1.0 - cost) if gross > 0 else 0.0


def eligible_at(
    symbols: Iterable[str],
    t0: int,
    *,
    has_price_at: dict[str, bool],
    level_prev: dict[str, bool],
    first_filing: dict[str, int | None],
    membership: Membership | None,
) -> list[str]:
    """Elegibles con informacion disponible EN t0: precio en t0, veredicto de t0-1, primer filing
    <= t0 y pertenencia historica. NUNCA exige precios posteriores a t0 (ese era el filtro de supervivencia)."""
    out = []
    for s in symbols:
        if not has_price_at.get(s) or not level_prev.get(s):
            continue
        ff = first_filing.get(s)
        if ff is not None and ff > t0:
            continue
        if membership is not None and not membership.has(s, t0):
            continue
        out.append(s)
    return out


def walk_forward_folds(
    months: Sequence[int], *, train: int, test: int, step: int | None = None
) -> list[tuple[list[int], list[int]]]:
    """Folds expansivos train->test sin solape: el test siempre es posterior al train."""
    step = step or test
    folds = []
    i = train
    while i + test <= len(months):
        folds.append((list(months[:i]), list(months[i : i + test])))
        i += step
    return folds


def cost_adjusted(
    gross_monthly: Sequence[float], turnover_monthly: Sequence[float], *, bps: float
) -> list[float]:
    """Resta ``bps`` por unidad de rotacion mensual a cada retorno (coste explicito, reproducible)."""
    if len(gross_monthly) != len(turnover_monthly):
        raise ValueError("longitudes distintas")
    return [r - t * bps / 1e4 for r, t in zip(gross_monthly, turnover_monthly, strict=True)]
