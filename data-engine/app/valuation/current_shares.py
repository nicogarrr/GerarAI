"""Acciones vigentes del punto de partida (regla «acciones-vigentes-v1», pre-registrada el 9-nov-2026).

El valor por acción divide el capital de HOY: las acciones de la portada del último informe
(``dei:EntityCommonStockSharesOutstanding`` del 10-Q/10-K), sumando TODAS las clases, no la media diluida de un
ejercicio ya cerrado. Caso real: ASTS valorada con 256 M (media diluida de 2025) cuando la portada del 10-Q de
agosto de 2026 dice 389 M (A 299,8 + B 11,2 + C 78,2).

Reglas (generales, ningún emisor):

1. Portada posterior al cierre del último ejercicio → manda. Una suma de clases (hecho derivado por clase) es el
   total por construcción. Una portada SIN desglose por debajo del 80 % de la media diluida puede ser una sola
   clase y se descarta; por encima de 3× la escala es sospechosa y se descarta. Las dos con su motivo.
2. Sin portada válida → media diluida del ejercicio, con aviso.
3. Estructura Up-C (unidades de la filial canjeables por acciones, con clases B/C de voto sin derechos
   económicos en la cotizada): si hay ≥ 2 clases, minoritarios > 0 y la fracción de acciones de las clases
   distintas de la mayor (≥ 2 %) cuadra a ±10 pp con la de los minoritarios (minoritarios / patrimonio total; si
   falta, beneficio de minoritarios / beneficio total), esas clases SON los minoritarios. Se cuentan como
   acciones o se restan como minoritarios, nunca las dos cosas:

   - bases sobre el EV (EV/EBITDA, EV/ventas, DCF): todas las clases y minoritarios a 0;
   - bases sobre el beneficio atribuible (PER, P/VC, FFO): solo la clase mayor (la cotizada).
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

RULES_VERSION = "acciones-vigentes-v1"
COVER_MIN_RATIO = 0.8
COVER_MAX_RATIO = 3.0
UPC_TOLERANCE = 0.10
UPC_MIN_OTHER = 0.02
EV_BASES = ("ev_ebitda", "ev_sales", "dcf")


def _provenance(source_metadata: Mapping[str, Any] | None, period: str | None) -> Mapping[str, Any] | None:
    prov = source_metadata.get("class_shares_provenance") if isinstance(source_metadata, Mapping) else None
    if not isinstance(prov, Mapping):
        return None
    end = str(period or "").split(":")[0]
    if prov.get("as_of") and end and str(prov.get("as_of")) != end:
        return None
    return prov


def is_class_sum(source_metadata: Mapping[str, Any] | None, period: str | None) -> bool:
    """True si el hecho es la suma de clases de ESA portada (también la convertida a la clase cotizada)."""
    return _provenance(source_metadata, period) is not None


def class_members(source_metadata: Mapping[str, Any] | None, period: str | None) -> dict[str, float] | None:
    """{clase: acciones} de la procedencia por clase de un hecho derivado, si es de esa misma portada (None si
    las clases se convirtieron a la cotizada con un ratio: no son unidades 1:1)."""
    prov = _provenance(source_metadata, period)
    if prov is None:
        return None
    out: dict[str, float] = {}
    for member, value in dict(prov.get("members") or {}).items():
        try:
            v = float(value)
        except (TypeError, ValueError):
            return None
        if v > 0:
            out[str(member)] = v
    return out if len(out) >= 2 and not prov.get("conversion_ratios") else None


def _ratio(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or den <= 0 or num <= 0:
        return None
    return num / den


def up_c(members: Mapping[str, float] | None, *, minority_interest: float | None, total_equity: float | None,
         ni_minority: float | None = None, ni_total: float | None = None) -> dict[str, Any] | None:
    """La prueba Up-C de la regla 3, o None. Puro (mismas unidades en minoritarios y patrimonio)."""
    if not members or len(members) < 2 or not minority_interest or minority_interest <= 0:
        return None
    total = sum(members.values())
    listed = max(members, key=lambda m: (members[m], m))
    other = 1.0 - members[listed] / total
    if other < UPC_MIN_OTHER:
        return None
    nci_share, basis = None, None
    if total_equity and total_equity > minority_interest:
        nci_share, basis = minority_interest / total_equity, "minoritarios / patrimonio total"
    elif ni_minority is not None and ni_total:
        nci_share, basis = _ratio(abs(ni_minority), abs(ni_total)), "beneficio de minoritarios / beneficio total"
    if nci_share is None or abs(nci_share - other) > UPC_TOLERANCE:
        return None
    return {"rules": RULES_VERSION, "listed_class": listed, "listed_shares": members[listed],
            "paired_classes": sorted(m for m in members if m != listed),
            "paired_shares": total - members[listed], "total_shares": total,
            "share_of_paired_classes": other, "share_of_minorities": nci_share, "minorities_basis": basis,
            "tolerance": UPC_TOLERANCE}


def cover_check(cover: float | None, diluted: float | None, *, by_class: bool) -> str | None:
    """None si la portada vale; si no, el motivo para descartarla."""
    if cover is None or cover <= 0:
        return "sin portada"
    if by_class or diluted is None or diluted <= 0:
        return None
    r = cover / diluted
    if r < COVER_MIN_RATIO:
        return (f"portada sin desglose por clase al {r:.0%} de la media diluida: puede ser una sola clase")
    if r > COVER_MAX_RATIO:
        return f"portada {r:.1f}× la media diluida: escala sospechosa"
    return None


def short(member: str) -> str:
    m = member.replace("Member", "")
    for pre in ("CommonClass", "CapitalClass", "Class"):
        if m.startswith(pre):
            return m[len(pre):]
    return m


__all__ = ["COVER_MAX_RATIO", "COVER_MIN_RATIO", "EV_BASES", "RULES_VERSION", "UPC_MIN_OTHER", "UPC_TOLERANCE",
           "class_members", "cover_check", "is_class_sum", "short", "up_c"]
