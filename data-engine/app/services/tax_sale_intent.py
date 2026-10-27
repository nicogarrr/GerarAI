"""Reject sale histories/alternatives that the chat estimator cannot replay.

A purchase-only hypothetical is not a complete ledger: selecting the first
``vend*`` match can replace today's question with an earlier sale. Fail closed
before either the stored-position or purchase-lot route publishes an estimate.
"""
from __future__ import annotations

import re

# Match the same broad repertoire consumed downstream, including vendiendo
# and venderemos. A conservative clarification is safer than letting a form
# outside a hand-maintained conjugation list select the first amount.
_SALE_EVENT = re.compile(r"(?i)\bvend\w*\b")
_HISTORICAL_SALE = re.compile(
    r"(?i)\b(?:vend[ií]|vendi[oó]|vendimos|vendiste(?:is)?|vendieron|"
    r"vend[ií]a(?:s|n|mos)?|vendid[oa]s?)\b"
    r"|\bventa\s+(?:pasada|anterior|realizada|previa)\b"
    r"|\b(?:hubo|hab[ií]a|hice|realic[ée]|efectu[ée])\s+(?:(?:ya|una|la|otra)\s+){0,3}venta\b"
)
_NEGATED_SALE = re.compile(
    r"(?i)\b(?:no|nunca|jam[aá]s)\s+(?:(?:he|has|ha|hemos|hab[ií]a|hab[ií]as|"
    r"estoy|estamos|quiero|quer[ií]a|voy|vamos|a|ya)\s+){0,4}vend\w*\b"
)


def sale_intent_issue(question: str) -> str | None:
    """An explicit clarification, never a substitute sale or a tax figure."""
    if _NEGATED_SALE.search(question or ""):
        return (
            "Hay una venta negada o corregida en el mensaje. Confirma una sola operación "
            "hipotética con cantidad y precio y qué historial sigue vigente; no he tomado "
            "los importes de la cláusula negada para calcular el IRPF."
        )
    if _HISTORICAL_SALE.search(question or ""):
        return (
            "El mensaje menciona una venta pasada o su ausencia. Esta estimación no reconstruye ventas previas escritas "
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
