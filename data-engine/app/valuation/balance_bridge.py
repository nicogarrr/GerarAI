"""Puente de balance para la deuda neta del punto de partida (regla ``caja-deuda-v1``). Puro.

La deuda neta de la TIR mezclaba saldos de cierres distintos: cada partida tomaba su último dato, así que
unas inversiones a corto de 2019 se sumaban a la caja de 2026 y una deuda del agregador (Yahoo, con los
arrendamientos operativos dentro) se restaba de la caja del último 10-Q. Reglas generales:

1. El ancla es el cierre de la caja (``cash_and_equivalents``, el último balance con caja).
2. Las inversiones a corto solo se suman si son del MISMO cierre que la caja; un dato de otro cierre no se
   suma y se avisa con su fecha (un saldo viejo no prueba que sigan ahí).
3. La deuda total se usa tal cual si es de fuente primaria; si es de otro cierre se avisa con las dos fechas.
4. Deuda de un agregador (Yahoo/FMP): su «total debt» incluye los arrendamientos (operativos incluidos).
   - US GAAP: el alquiler operativo ya resta en el EBITDA, así que se descuentan los pasivos por
     arrendamiento operativo del filing primario del MISMO cierre (una sola vez). Si el resto es ≈ 0 (|x| ≤
     0,5 % del bruto), la deuda financiera es 0 con su fórmula. Sin ese dato, se usa con aviso.
   - IFRS: los arrendamientos ya están dentro del total del agregador; no se suman otra vez.
"""
from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from datetime import date
from typing import Any

RULE = "caja-deuda-v1"
#: Fuentes primarias (filing del emisor). El resto son agregadores.
PRIMARY_SOURCES = ("SEC", "ESEF", "CNMV", "COMPANIES_HOUSE", "DERIVED")
#: Tolerancia para dar por nula la deuda que queda tras quitar los arrendamientos operativos.
ZERO_TOLERANCE = 0.005


def _end(cite: Mapping[str, Any] | None) -> str:
    end = str((cite or {}).get("period") or "").split(":")[0]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", end):
        return ""
    try:
        return date.fromisoformat(end).isoformat()
    except ValueError:
        return ""


def _val(cite: Mapping[str, Any] | None) -> float | None:
    try:
        v = (cite or {}).get("value")
        value = None if v is None else float(v) / 1_000_000.0
        return value if value is not None and math.isfinite(value) else None
    except (TypeError, ValueError, OverflowError):
        return None


def is_primary(cite: Mapping[str, Any] | None) -> bool:
    st = str((cite or {}).get("source_type") or "").upper()
    return st in PRIMARY_SOURCES


def short_term_investments(point: Mapping[str, Mapping[str, Any]]) -> tuple[float, dict[str, Any] | None, str | None]:
    """(millones a sumar, cita usada o None, aviso o None). Solo del mismo cierre que la caja."""
    sti = point.get("short_term_investments")
    if not sti:
        return 0.0, None, None
    anchor, end = _end(point.get("cash_and_equivalents")), _end(sti)
    v = _val(sti)
    if v is None:
        return 0.0, None, None
    if not end or not anchor:
        return 0.0, None, f"inversiones a corto: cierre desconocido de caja o inversiones; no se suman ({RULE})"
    if end != anchor:
        if not v:
            return 0.0, None, None
        return 0.0, None, (f"inversiones a corto: el último dato ({v:,.0f} M, {end}) no es del balance de la caja "
                           f"({anchor}); no se suman ({RULE})")
    return v, dict(sti), None


def financial_debt(point: Mapping[str, Mapping[str, Any]], *, ifrs: bool,
                   lease_at: Callable[[str], Mapping[str, Any] | None] | None = None,
                   ) -> tuple[float | None, dict[str, Any] | None, bool, list[str]]:
    """(deuda financiera en millones o None, cita, arrendamientos_ya_dentro, avisos).

    ``lease_at(periodo)`` (``AAAA-MM-DD:FY``) devuelve la cita primaria de ``operating_lease_liabilities`` de ese cierre (o None);
    sin ella solo se mira el último dato del punto."""
    warnings: list[str] = []
    debt = point.get("total_debt")
    v = _val(debt)
    if debt is None or v is None:
        return None, None, False, warnings
    anchor, end = _end(point.get("cash_and_equivalents")), _end(debt)
    if not anchor or not end:
        return None, None, False, [f"deuda total: cierre desconocido de caja o deuda; no se usa ({RULE})"]
    cite: dict[str, Any] = dict(debt)
    if is_primary(debt):
        if anchor and end and end != anchor:
            warnings.append(f"deuda total del cierre {end} y caja del {anchor}: el último filing sin deuda total "
                            f"etiquetada, se usa la del cierre anterior ({RULE})")
        return v, cite, False, warnings
    source = str(debt.get("source_type") or "agregador")
    if ifrs:
        warnings.append(f"deuda total de {source} ({end}): bajo IFRS ya incluye los arrendamientos, no se suman "
                        f"otra vez ({RULE})")
        return v, cite, True, warnings
    lease = point.get("operating_lease_liabilities")
    if (lease is None or str(lease.get("period") or "") != str(debt.get("period") or "")) and lease_at is not None:
        lease = lease_at(str(debt.get("period") or "")) or (lease if lease is not None and _end(lease) == end else None)
    lv = _val(lease)
    if lease is not None and lv is not None and is_primary(lease) and _end(lease) == end and 0 < lv <= v * (1 + ZERO_TOLERANCE):
        rest = v - lv
        if abs(rest) <= v * ZERO_TOLERANCE:
            rest = 0.0
        cite = {"metric": "total_debt", "value": rest * 1_000_000.0, "period": debt.get("period"),
                "source_type": "DERIVED", "rule": RULE,
                "formula": (f"deuda total de {source} {v:,.2f} M − pasivos por arrendamiento operativo del filing "
                            f"{lv:,.2f} M (mismo cierre {end}; US GAAP: el alquiler ya está en el EBITDA)"),
                "inputs": [dict(debt), dict(lease)]}
        warnings.append(f"deuda financiera = deuda de {source} − arrendamientos operativos del filing ({end}): "
                        f"{v:,.1f} → {rest:,.1f} M ({RULE})")
        if anchor and end != anchor:
            warnings.append(f"deuda del cierre {end} y caja del {anchor} ({RULE})")
        return rest, cite, False, warnings
    warnings.append(f"deuda total de {source} ({end}), sin dato del filing del mismo cierre: puede incluir "
                    f"arrendamientos operativos ({RULE})")
    return v, cite, False, warnings


def same_close(point: Mapping[str, Mapping[str, Any]], metric: str) -> bool:
    """El saldo ``metric`` es del mismo cierre que la caja (el ancla del punto de partida)."""
    cite = point.get(metric)
    end, anchor = _end(cite), _end(point.get("cash_and_equivalents"))
    return bool(cite) and bool(end) and bool(anchor) and end == anchor


def stale_note(point: Mapping[str, Mapping[str, Any]], metric: str, label: str) -> str | None:
    """Aviso con fechas si el último dato de ``metric`` es de un cierre anterior al de la caja."""
    cite = point.get(metric)
    if not cite or same_close(point, metric):
        return None
    end, anchor = _end(cite), _end(point.get("cash_and_equivalents"))
    if not end or not anchor or end >= anchor:
        return None
    return (f"{label}: el último dato publicado es del {end}, no del balance de la caja ({anchor}); "
            f"se usa con esa fecha ({RULE})")
