"""Parte del accionista de los flujos consolidados cuando hay minoritarios.

Caso real (backtest PIT, 8-nov-2026): Brookfield (BN, 40-F) consolida filiales de las que tiene una parte;
el beneficio que GerarAI usa es el ATRIBUIBLE a la dominante (1.307 M en FY2025 frente a 3.235 M del total),
pero el flujo de caja operativo, el capex y las adquisiciones son los CONSOLIDADOS. La conversión de caja
(FCF / beneficio) salía inflada y la TIR base, 32–52 % en 2018–20, frente a un 10–20 %/año realizado.

Regla general: los flujos consolidados se multiplican por la parte del accionista de la dominante,
- del beneficio: dominante / (dominante + minoritarios), si los dos son del ejercicio y la parte cae en (0, 1];
- si no, del patrimonio: patrimonio de la dominante / (dominante + minoritarios del balance);
- sin dato de minoritarios, 1 (nada que repartir).
Función pura: la usan la valoración de la app y el backtest point-in-time (misma lógica).
"""
from __future__ import annotations

from collections.abc import Sequence

FROM_EARNINGS = "beneficio"
FROM_EQUITY = "patrimonio"


def attributable_share(
    *,
    net_income_parent: float | None,
    net_income_minority: float | None,
    equity_parent: float | None,
    equity_minority: float | None,
) -> tuple[float, str] | None:
    """(parte del accionista, de dónde sale) o None si no hay minoritarios conocidos."""
    if net_income_parent is not None and net_income_minority is not None:
        total = net_income_parent + net_income_minority
        if net_income_parent > 0 and total > 0:
            share = net_income_parent / total
            if 0.0 < share <= 1.0:
                return share, FROM_EARNINGS
    if equity_parent is not None and equity_minority is not None and equity_parent > 0 and equity_minority >= 0:
        return equity_parent / (equity_parent + equity_minority), FROM_EQUITY
    return None


def attributable_shares(
    net_income_parent: Sequence[float | None],
    net_income_minority: Sequence[float | None],
    equity_parent: Sequence[float | None],
    equity_minority: Sequence[float | None],
) -> list[tuple[float, str] | None]:
    """Parte por ejercicio; un ejercicio sin dato toma la del ejercicio conocido más cercano anterior
    (o posterior si no hay anterior). Todo None si ningún ejercicio tiene minoritarios."""
    raw = [attributable_share(net_income_parent=a, net_income_minority=b, equity_parent=c, equity_minority=d)
           for a, b, c, d in zip(net_income_parent, net_income_minority, equity_parent, equity_minority, strict=True)]
    known = [i for i, x in enumerate(raw) if x is not None]
    if not known:
        return raw
    out: list[tuple[float, str] | None] = []
    for i, x in enumerate(raw):
        if x is not None:
            out.append(x)
            continue
        prev = [k for k in known if k < i]
        out.append(raw[prev[-1]] if prev else raw[known[0]])
    return out


def scale_flows(values: Sequence[float | None], shares: Sequence[tuple[float, str] | None]) -> list[float | None]:
    """Flujo consolidado × parte del accionista de su ejercicio (sin parte conocida, igual)."""
    return [None if v is None else (v * s[0] if s is not None else v) for v, s in zip(values, shares, strict=True)]
