"""Cuerpo de la llamada dentro de una pagina HTML, con provenance verificable.

Delimitado SOLO por marcadores literales registrados por activo (nunca heuristica). Si un marcador
falta, es ambiguo o el orden es incoherente, no hay cuerpo: se abstiene. El hash del cuerpo
(`body_sha256`) distingue un cambio de la llamada de un cambio de menu/pie (`text_sha256`/bytes).
Un cuerpo extraido NO implica cumplimiento de ningun compromiso.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.services.commitment_primary_pipeline import PrimarySourceError, RegisteredDocument

# Indicios (no prueba) de seccion de preguntas/analistas; informativo, nunca un veredicto.
_QA_HINTS = ("Operator:", "Q&A", "Question:", "Analyst")


@dataclass(frozen=True)
class BodyProvenance:
    text: str
    start: int
    end: int
    body_sha256: str
    start_marker: str
    end_marker: str
    words: int
    qa_hints: tuple[str, ...]  # indicios encontrados; vacio = no se detecto (no prueba ausencia)


def extract_body(doc: RegisteredDocument, asset=None) -> BodyProvenance:
    """`asset` = VerifiedAsset del registro (lleva los marcadores); por defecto doc.asset."""
    a = asset if asset is not None else doc.asset
    start_marker = getattr(a, "body_start", None)
    end_marker = getattr(a, "body_end", None)
    if not start_marker or not end_marker:
        raise PrimarySourceError("Activo sin marcadores de cuerpo registrados")
    text = doc.text
    if text.count(start_marker) != 1:
        raise PrimarySourceError("Marcador de inicio ausente o ambiguo")
    start = text.index(start_marker) + len(start_marker)
    end = text.find(end_marker, start)
    if end == -1:
        raise PrimarySourceError("Marcador de fin ausente tras el inicio")
    body = text[start:end].strip()
    if len(body.split()) < 200:
        raise PrimarySourceError("Cuerpo extraido insuficiente")
    return BodyProvenance(
        text=body, start=start, end=end,
        body_sha256=hashlib.sha256(body.encode()).hexdigest(),
        start_marker=start_marker, end_marker=end_marker, words=len(body.split()),
        qa_hints=tuple(h for h in _QA_HINTS if h in body),
    )
