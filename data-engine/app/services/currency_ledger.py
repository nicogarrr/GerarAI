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

Reglas añadidas (doctrina aportada por Auditor 2; no verificadas por mi contra
el texto de las consultas):

- Entradas: ventas de acciones, al tipo con que tributaron (V0282-22).
- Salidas sin resultado propio: compras de valores y comisiones en la divisa
  consumen lotes FIFO; el resultado solo aparece al convertir a EUR
  (V0706-22 para comisiones).
- Anti-recompra: la perdida por convertir divisa a EUR no se integra en la
  parte cubierta por una adquisicion de la misma divisa en el año anterior o
  posterior (art. 33.5.e LIRPF, V1613-25), NO 2 meses. La perdida bloqueada se
  suma al valor de adquisicion de la divisa readquirida y se integra al
  convertirla. Direccion (anterior y posterior) segun el articulo; el texto
  no se ha podido contrastar aqui.
- Dividendos e intereses como entradas: sin consulta en punto, solo analogia;
  solo con ``income_by_analogy=True`` y etiquetado.
- Fondos/IIC comprados con divisa propia (V0775-21): fuera de alcance, el
  resultado queda ``incomplete``.

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
SOURCES = (
    "DGT V2466-08", "DGT V0234-07", "DGT V0282-22", "art. 14.2.e LIRPF",
    "DGT V0706-22", "DGT V1613-25", "art. 33.5.e LIRPF", "DGT V0775-21",
)
WASH_YEARS = 1  # art. 33.5.e LIRPF: un año, no 2 meses
ANALOGY_LABEL = "criterio por analogía, sin consulta"

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
class Outflow:
    """Salida de divisa SIN resultado propio (compra de valores, comision)."""

    day: date
    amount: Decimal
    kind: str = "compra"
    ref: str = ""


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


def _shift_year(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:  # 29 feb
        return day.replace(year=day.year + years, day=28)


def compute_currency_ledger(
    lots, conversions, start: date, end: date, *, opening_complete: bool = False, outflows=(),
    data_through: date | None = None,
) -> dict:
    """Ganancia por conversiones de ``start``..``end`` consumiendo lotes FIFO.

    ``opening_complete``: el llamador garantiza que ``lots`` incluye todo lo
    adquirido antes de ``start`` que sigue sin convertir. Si es False el
    resultado queda incompleto.

    ``data_through``: fecha hasta la que hay datos (por defecto, el ultimo
    movimiento conocido). Una perdida cuya ventana de 1 año acaba despues queda
    incompleta: una recompra futura aun podria bloquearla.

    ``outflows``: compras y comisiones en la divisa. Consumen FIFO sin
    resultado. El mismo dia se procesan antes que las conversiones.
    """
    conversions = sorted(conversions or [], key=lambda c: c.converted_on)
    if not conversions:
        return {
            "criterion": CRITERION, "status": NOT_COMPUTED, "gain_base": None,
            "reason": "sin conversiones reales de divisa como entrada", "rows": [],
            "unconverted": None, "blocked_loss_base": None, "sources": list(SOURCES),
        }
    lot_list = sorted(lots or [], key=lambda l: l.acquired_on)
    queue = [[l.acquired_on, l.amount, l.eur_value, l.origin] for l in lot_list]
    data_end = data_through or max(
        [c.converted_on for c in conversions]
        + [l.acquired_on for l in lot_list]
        + [o.day for o in outflows],
    )
    events = sorted(
        [(o.day, 0, o) for o in outflows] + [(c.converted_on, 1, c) for c in conversions],
        key=lambda e: (e[0], e[1]),
    )

    def consume(amount: Decimal, day: date):
        remaining, cost, ok = amount, Decimal("0"), True
        for q in queue:
            if remaining <= 0:
                break
            if q[0] > day or q[1] <= 0:
                continue
            take = min(q[1], remaining)
            if q[2] is None:
                ok = False
            else:
                part = q[2] * take / q[1]
                cost += part
                q[2] -= part
            q[1] -= take
            remaining -= take
        return cost, ok, remaining

    rows, total, blocked_total = [], Decimal("0"), Decimal("0")
    complete, reasons = True, []
    for day, _, ev in events:
        in_year = start <= day <= end
        if isinstance(ev, Outflow):
            _, ok, rest = consume(ev.amount, day)
            if rest > 0 or not ok:
                complete = False
                reasons.append(
                    f"{ev.kind} del {day} ({ev.ref}): "
                    + ("supera la divisa conocida" if rest > 0 else "lote sin valor en EUR")
                )
            continue
        conv = ev
        cost, ok, rest = consume(conv.amount, day)
        row_ok = ok and rest <= 0 and conv.ecb_rate is not None
        if conv.ecb_rate is None:
            reasons.append(f"falta cambio BCE del {day}")
        if not ok:
            reasons.append("falta valor en EUR de un lote consumido")
        if rest > 0:
            reasons.append(f"conversion del {day} supera la divisa conocida en {rest}")
        gain = conv.amount * conv.ecb_rate - cost if row_ok else None
        blocked = Decimal("0")
        window_open = False
        if gain is not None and gain < 0:
            lo, hi = _shift_year(day, -WASH_YEARS), _shift_year(day, WASH_YEARS)
            window_open = hi > data_end
            held = [q for q in queue if q[1] > 0 and lo <= q[0] <= hi]
            held_total = sum((q[1] for q in held), Decimal("0"))
            cover = min(conv.amount, held_total)
            if cover > 0:
                blocked = -gain * cover / conv.amount
                left = cover
                for q in held:
                    if left <= 0:
                        break
                    take = min(q[1], left)
                    if q[2] is None:
                        complete = False
                        reasons.append("lote readquirido sin valor en EUR")
                    else:
                        q[2] += blocked * take / cover
                    left -= take
            if window_open and in_year:
                reasons.append(
                    f"perdida del {day}: ventana de 1 año aun abierta, una recompra posterior la bloquearia"
                )
                complete = False
        integrated = None if gain is None else gain + blocked
        if in_year:
            if integrated is None:
                complete = False
            else:
                total += integrated
                blocked_total += blocked
        rows.append({
            "date": day.isoformat(), "amount": float(conv.amount),
            "transmission_value_base": None if conv.ecb_rate is None else float(conv.amount * conv.ecb_rate),
            "acquisition_value_base": float(cost) if row_ok else None,
            "gain_base": None if gain is None else float(gain),
            "blocked_loss_base": float(blocked), "window_open": window_open,
            "integrated_gain_base": None if integrated is None else float(integrated),
            "in_fiscal_year": in_year, "ref": conv.ref,
        })
    if not opening_complete:
        complete = False
        reasons.append("no se garantiza el saldo de divisa anterior al ejercicio")
    return {
        "criterion": CRITERION,
        "status": COMPUTED if complete else INCOMPLETE,
        "gain_base": float(total) if complete else None,
        "blocked_loss_base": float(blocked_total) if complete else None,
        "reason": "; ".join(dict.fromkeys(reasons)) or None,
        "rows": rows,
        "unconverted": float(sum(q[1] for q in queue)),
        "sources": list(SOURCES),
    }
