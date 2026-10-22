"""Extraccion DETERMINISTA de compromisos candidatos desde texto de transcripcion.

Reglas de honestidad:
- Solo propone candidatos. Nunca crea promesas autenticadas ni decide cumplimiento.
- Cada cita es una subcadena exacta del texto (espacios normalizados); si no se
  puede verificar, el candidato se descarta.
- Solo habla la direccion: hablantes con cargo en la cabecera de la presentacion.
  Preguntas de analistas y operador se ignoran.
- Condicionales, negaciones y "no esperamos" se marcan en flags: no se resuelven.
- due_date_hint es una sugerencia derivada del periodo citado, no una fecha dicha.
- Sin LLM, sin red, sin coste.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

_ROLE_HEADER = re.compile(
    r"^([A-Z][\w.'’-]+(?: [A-Z][\w.'’-]+){1,3}), ((?:Chief|Co-|CEO|CFO|COO|CTO|President|Chair|"
    r"Director|Head|VP|Vice|Managing|Executive|Founder|Treasurer)[\w ,&/-]{0,60})\s*$"
)
_TURN = re.compile(r"^\s{0,2}([A-Z][\w.'’-]+(?: [A-Z][\w.'’-]+){0,3}):\s{1,}(\S.*)$")
_BOILERPLATE = re.compile(
    r"forward[- ‐]looking|undertake no obligation|actual results may differ|safe harbor|"
    r"press release|non[- ‐]GAAP|reconciliation",
    re.I,
)
_FORWARD = re.compile(
    r"\b(we expect|we anticipate|we plan to|we intend to|we will|we are going to|we aim to|"
    r"we target|on track to|we remain committed to|we are committed to|we continue to expect|"
    r"we expect to|is expected to|are expected to|will be)\b",
    re.I,
)
_CHECKABLE = re.compile(
    r"\b(20\d{2})\b|\b(first|second|third|fourth|Q[1-4])\s+quarter\b|\bQ[1-4]\b|"
    r"\$\s?\d[\d.,]*|\d[\d.,]*\s?(%|percent|billion|million|satellites|MW|GW)",
    re.I,
)
_CONDITIONAL = re.compile(r"\b(if|unless|subject to|depending on|assuming|absent|provided that)\b", re.I)
_NEGATION = re.compile(r"\b(not|no longer|do not|don't|aren't|won't|cannot|isn't)\b", re.I)
_QUARTER_END = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
_ORD = {"first": 1, "second": 2, "third": 3, "fourth": 4}


@dataclass
class Candidate:
    quote_literal: str
    speaker: str
    speaker_role: str
    due_date_hint: date | None
    due_basis: str  # "year_end_hint" | "quarter_end_hint" | "none"
    flags: list[str] = field(default_factory=list)
    char_start: int = 0
    char_end: int = 0
    source_status: str = "suggested"  # nunca "verified": lo decide una persona con la fuente


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\u00a0", " ")).strip()


def _roster(lines: list[str]) -> dict[str, str]:
    roster: dict[str, str] = {}
    for line in lines:
        m = _ROLE_HEADER.match(line.strip())
        if m and not line.startswith(" " * 4):
            roster[m.group(1)] = m.group(2).strip()
    return roster


def _turns(text: str, roster: dict[str, str]) -> list[tuple[str, str]]:
    """Devuelve (hablante, texto) solo para hablantes con cargo conocido."""
    turns: list[tuple[str, list[str]]] = []
    current: str | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.isdigit():
            continue
        header = _ROLE_HEADER.match(stripped)
        if header and not raw.startswith("    "):
            current = header.group(1)
            turns.append((current, []))
            continue
        m = _TURN.match(raw)
        if m and (m.group(1) in roster or m.group(1) in ("Operator",) or len(raw) - len(raw.lstrip()) <= 2):
            current = m.group(1)
            turns.append((current, [m.group(2)]))
            continue
        if current is not None and turns:
            turns[-1][1].append(stripped)
    return [(who, " ".join(parts)) for who, parts in turns if who in roster]


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z“\"])", text) if s.strip()]


def _due_hint(sentence: str) -> tuple[date | None, str]:
    q = re.search(r"\b(first|second|third|fourth)\s+quarter(?:\s+of)?\s+(20\d{2})", sentence, re.I)
    if q:
        month, day = _QUARTER_END[_ORD[q.group(1).lower()]]
        return date(int(q.group(2)), month, day), "quarter_end_hint"
    # Solo con el anio pegado a la expresion; "this year" o un anio de referencia
    # (p. ej. "above 2025 operating income") NO generan fecha.
    y = re.search(r"\b(?:full[- ]year|remaining quarters of|by the end of|end of)\s+(20\d{2})\b", sentence, re.I)
    if y:
        return date(int(y.group(1)), 12, 31), "year_end_hint"
    return None, "none"


def extract_candidates(transcript_text: str, *, max_candidates: int = 40) -> list[Candidate]:
    lines = transcript_text.splitlines()
    roster = _roster(lines)
    haystack = _normalize(transcript_text)
    out: list[Candidate] = []
    seen: set[str] = set()
    for speaker, body in _turns(transcript_text, roster):
        for sentence in _split_sentences(_normalize(body)):
            if _BOILERPLATE.search(sentence) or not _FORWARD.search(sentence) or not _CHECKABLE.search(sentence):
                continue
            if len(sentence) < 25 or len(sentence) > 600 or sentence in seen:
                continue
            start = haystack.find(sentence)
            if start < 0:  # la cita debe ser subcadena exacta; si no, se descarta
                continue
            seen.add(sentence)
            due, basis = _due_hint(sentence)
            flags = []
            if _CONDITIONAL.search(sentence):
                flags.append("conditional")
            if _NEGATION.search(sentence):
                flags.append("negation_present")
            out.append(
                Candidate(
                    quote_literal=sentence,
                    speaker=speaker,
                    speaker_role=roster[speaker],
                    due_date_hint=due,
                    due_basis=basis,
                    flags=flags,
                    char_start=start,
                    char_end=start + len(sentence),
                )
            )
            if len(out) >= max_candidates:
                return out
    return out
