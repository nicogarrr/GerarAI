"""Citas numeradas y su verificacion contra el texto almacenado y el original."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.services.knowledge_rag.domain import normalize_ws, sha256_hex


@dataclass
class Citation:
    number: int
    chunk_id: str
    quote: str  # texto literal del hijo (lo que se cita)
    context: str  # texto del padre (para ampliar)
    parent_id: str
    source_id: int
    source_sha256: str
    title: str
    author: str | None
    source_uri: str
    language: str
    doc_type: str
    corpus: str
    rights: str
    published_date: str | None
    as_of: str | None
    section_path: list[str]
    page_start: int | None
    page_end: int | None
    bboxes: list[dict[str, Any]]
    char_start: int
    char_end: int
    text_sha256: str
    scores: dict[str, float | None] = field(default_factory=dict)
    verified: bool = False
    verification: list[str] = field(default_factory=list)

    def public(self, *, include_context: bool = True) -> dict[str, Any]:
        data = asdict(self)
        if not include_context:
            data.pop("context")
        return data


@dataclass
class VerificationResult:
    ok: bool
    failures: list[str]
    checks: list[str]


def verify_citation(
    *,
    quote: str,
    parent_text: str,
    char_start: int,
    char_end: int,
    text_sha256: str,
    parent_text_sha256: str | None = None,
    source_bytes: bytes | None = None,
    source_sha256: str | None = None,
    reference_page_text: str | None = None,
) -> VerificationResult:
    """Comprueba que la cita es literal y rastreable.

    1. ``parent_text[char_start:char_end] == quote`` (la cita sale del padre).
    2. sha256(quote) coincide con el hash registrado en la ingesta.
    3. (opcional) el padre no cambio desde la ingesta.
    4. (opcional) los bytes originales tienen el sha256 de la fuente.
    5. (opcional) el texto de la pagina del original (extraido por el verificador
       con otra herramienta) contiene la cita normalizando espacios.
    Solo 1 y 2 son obligatorios en consulta; 3-5 los activa quien audita.
    """
    failures: list[str] = []
    checks: list[str] = []
    # Python normaliza índices negativos y finales fuera del texto, y acepta
    # bool como int. Eso puede validar una ubicación inexistente o vacía.
    valid_span = (
        type(char_start) is int
        and type(char_end) is int
        and 0 <= char_start < char_end <= len(parent_text)
    )
    if not quote.strip():
        failures.append("empty_quote")
    if not valid_span:
        failures.append("invalid_quote_span")
    elif parent_text[char_start:char_end] != quote:
        failures.append("quote_not_in_parent_span")
    else:
        checks.append("quote_matches_parent_span")
    if sha256_hex(quote) != text_sha256:
        failures.append("quote_hash_mismatch")
    else:
        checks.append("quote_hash")
    if parent_text_sha256 is not None:
        if sha256_hex(parent_text) != parent_text_sha256:
            failures.append("parent_hash_mismatch")
        else:
            checks.append("parent_hash")
    if source_bytes is not None and source_sha256 is not None:
        if sha256_hex(source_bytes) != source_sha256:
            failures.append("source_file_hash_mismatch")
        else:
            checks.append("source_file_hash")
    if reference_page_text is not None:
        if normalize_ws(quote).lower() not in normalize_ws(reference_page_text).lower():
            failures.append("quote_not_in_reference_page")
        else:
            checks.append("quote_in_reference_page")
    return VerificationResult(ok=not failures, failures=failures, checks=checks)


def format_context(citations: list[Citation]) -> str:
    """Bloque listo para el LLM: pasajes numerados [n] con su origen."""
    lines: list[str] = []
    for c in citations:
        where = f"p.{c.page_start}" if c.page_start else "sin pagina"
        if c.page_end and c.page_end != c.page_start:
            where = f"pp.{c.page_start}-{c.page_end}"
        head = f"[{c.number}] {c.title}" + (f" - {c.author}" if c.author else "")
        lines.append(f"{head} ({where}; {' > '.join(c.section_path) or 'sin seccion'})\n{c.context}")
    return "\n\n".join(lines)
