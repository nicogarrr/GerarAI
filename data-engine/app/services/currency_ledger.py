"""Libro de divisas FIFO para la conversion posterior de USD (u otra) a EUR.

Criterio (cada regla cita su fuente; nada inventado):

- La conversion de divisa a euros es una transmision distinta de la venta
  del valor y genera su propia ganancia o perdida patrimonial
  (art. 14.2.e LIRPF; DGT V2466-08, V0234-07, V0282-22).
- Valor de adquisicion de la divisa = valor en euros usado al computar la
  venta que la genero (importe nativo x cambio BCE de la fecha de esa venta).
  Es el mismo cambio con el que la venta se declara, asi no se cuenta dos veces.
- Valor de transmision = importe convertido x cambio BCE del dia de la
  conversion.
- Orden de consumo: FIFO (art. 37.2 LIRPF por analogia a valores
  homogeneos; la consulta aplica FIFO a la divisa). Pendiente de revision por
  gestor.

Sin datos no se inventa: si falta un cambio, un lote previo o hay mas
conversion que divisa conocida, el resultado es ``None`` y ``status`` lo marca.
Nunca se devuelve 0 como si fuese un dato conocido.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

CRITERION = "currency_ledger_fifo_v1"
SOURCES = ("DGT V2466-08", "DGT V0234-07", "DGT V0282-22", "art. 14.2.e LIRPF")

NOT_COMPUTED = "not_computed"
INCOMPLETE = "incomplete"
COMPUTED = "computed"


@dataclass(frozen=True)
class CurrencyLot:
    """Divisa recibida: importe nativo y su valor en EUR a efectos fiscales."""

    acquired_on: date
    amount: Decimal
    eur_value: Decimal | None  # None si falta el cambio de la venta de origen
    origin: str = ""


@dataclass(frozen=True)
class Conversion:
    """Conversion real de divisa a EUR (p. ej. extracto del broker)."""

    converted_on: date
    amount: Decimal
    ecb_rate: Decimal | None  # EUR por unidad de divisa, BCE del dia
    ref: str = ""


def lots_from_sales(sales) -> list[CurrencyLot]:
    """Lotes de divisa a partir de ventas de valores ya calculadas.

    ``sales``: iterable de dicts con ``date``, ``proceeds_native``,
    ``proceeds_base`` (puede ser None) y opcional ``ref``.
    """
    return [
        CurrencyLot(
            s["date"],
            Decimal(str(s["proceeds_native"])),
            None if s.get("proceeds_base") is None else Decimal(str(s["proceeds_base"])),
            s.get("ref", ""),
        )
        for s in sales
        if s.get("proceeds_native") is not None and Decimal(str(s["proceeds_native"])) > 0
    ]


def compute_currency_ledger(lots, conversions, start: date, end: date, *, opening_complete: bool = False) -> dict:
    """Ganancia por conversiones de ``start``..``end`` consumiendo lotes FIFO.

    ``opening_complete``: el llamador garantiza que ``lots`` incluye todo lo
    adquirido antes de ``start`` que sigue sin convertir. Si es False y alguna
    conversion consume divisa sin lote conocido, queda incompleta.
    """
    conversions = sorted(conversions or [], key=lambda c: c.converted_on)
    if not conversions:
        return {
            "criterion": CRITERION, "status": NOT_COMPUTED, "gain_base": None,
            "reason": "sin conversiones reales de divisa como entrada", "rows": [],
            "unconverted": None, "sources": list(SOURCES),
        }
    queue: deque[list] = deque(
        [l.acquired_on, l.amount, l.eur_value, l.origin]
        for l in sorted(lots or [], key=lambda l: l.acquired_on)
    )
    rows, total, complete, reasons = [], Decimal("0"), True, []
    for conv in conversions:
        # Solo lotes ya adquiridos en la fecha de la conversion.
        remaining = conv.amount
        cost = Decimal("0")
        row_ok = conv.ecb_rate is not None
        if conv.ecb_rate is None:
            reasons.append(f"falta cambio BCE del {conv.converted_on}")
        eligible = [q for q in queue if q[0] <= conv.converted_on]
        for q in eligible:
            if remaining <= 0:
                break
            take = min(q[1], remaining)
            if q[2] is None:
                row_ok = False
                reasons.append(f"falta valor en EUR del lote {q[0]}")
            else:
                cost += q[2] * take / q[1]
                q[2] -= q[2] * take / q[1]
            q[1] -= take
            remaining -= take
        queue = deque(q for q in queue if q[1] > 0)
        if remaining > 0:
            row_ok = False
            reasons.append(
                f"conversion del {conv.converted_on} supera la divisa conocida en {remaining}"
            )
        gain = conv.amount * conv.ecb_rate - cost if row_ok else None
        in_year = start <= conv.converted_on <= end
        if in_year:
            if gain is None:
                complete = False
            else:
                total += gain
        rows.append({
            "date": conv.converted_on.isoformat(), "amount": float(conv.amount),
            "transmission_value_base": None if conv.ecb_rate is None else float(conv.amount * conv.ecb_rate),
            "acquisition_value_base": float(cost) if row_ok else None,
            "gain_base": None if gain is None else float(gain),
            "in_fiscal_year": in_year, "ref": conv.ref,
        })
    if not opening_complete:
        complete = False
        reasons.append("no se garantiza el saldo de divisa anterior al ejercicio")
    return {
        "criterion": CRITERION,
        "status": COMPUTED if complete else INCOMPLETE,
        "gain_base": float(total) if complete else None,
        "reason": "; ".join(dict.fromkeys(reasons)) or None,
        "rows": rows,
        "unconverted": float(sum(q[1] for q in queue)),
        "sources": list(SOURCES),
    }
