"""Reject sale histories/alternatives that the chat estimator cannot replay.

A purchase-only hypothetical is not a complete ledger: selecting the first
``vend*`` match can replace today's question with an earlier sale. Fail closed
before either the stored-position or purchase-lot route publishes an estimate.
"""
from __future__ import annotations

import re

# Exact verb forms, not arbitrary vend* (vendedor/vendible are not sale events).
_SALE_EVENT = re.compile(
    r"(?i)\b(?:vendo|vendes|vendemos|venden|vender|vender[ií]a(?:s|n|mos)?|"
    r"vendiera(?:s|n|mos)?|vendiese(?:s|n|mos)?|vender[ée]|vender[aá](?:s|n)?|"
    r"vend[ií]|vendi[oó]|vendimos|vendiste(?:is)?|vendieron|vend[ií]a(?:s|n|mos)?|"
    r"vendid[oa]s?)\b"
)
_HISTORICAL_SALE = re.compile(
    r"(?i)\b(?:vend[ií]|vendi[oó]|vendimos|vendiste(?:is)?|vendieron|"
    r"vend[ií]a(?:s|n|mos)?|vendid[oa]s?)\b"
    r"|\bventa\s+(?:pasada|anterior|realizada|previa)\b"
)


def sale_intent_issue(question: str) -> str | None:
    """An explicit clarification, never a substitute sale or a tax figure."""
    if _HISTORICAL_SALE.search(question or ""):
        return (
            "Has incluido una venta pasada. Esta estimación no reconstruye ventas previas escritas "
            "en el mensaje ni sus pérdidas diferidas. No he usado esa venta como si fuera la de hoy. "
            "Registra el historial completo en Cartera para simular sobre él, o confirma los lotes "
            "que siguen en cartera y una sola venta hipotética (cantidad y precio)."
        )
    if len(_SALE_EVENT.findall(question or "")) > 1:
        return (
            "Has descrito más de una venta o alternativa. Confirma una sola venta hipotética "
            "con su cantidad y precio; no he elegido ni combinado cláusulas para calcular el IRPF."
        )
    return None
