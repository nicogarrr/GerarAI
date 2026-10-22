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
# Solo intencion en PRIMERA PERSONA (la direccion habla de si misma). "es esperado que"/"will be" sobre
# mercados o terceros NO cuentan: se marcan aparte y no entran como candidatos.
_FORWARD = re.compile(
    r"\b(we expect|we anticipate|we plan to|we intend to|we will|we are going to|we aim to|"
    r"we target|we remain committed to|we are committed to|we continue to expect|"
    r"we expect to|we'll be|we're on track|we are on track)\b",
    re.I,
)
_CHECKABLE = re.compile(
    r"\b(20\d{2})\b|\b(first|second|third|fourth|Q[1-4])\s+quarter\b|\bQ[1-4]\b|"
    r"\$\s?\d[\d.,]*|\d[\d.,]*\s?(%|percent|billion|million|satellites|MW|GW)",
    re.I,
)
_CONDITIONAL = re.compile(r"\b(if|unless|subject to|depending on|assuming|absent|provided that)\b", re.I)
_NEGATION = re.compile(r"\b(not|no longer|do not|don't|aren't|won't|cannot|isn't)\b", re.I)
_THIRD_PARTY = re.compile(
    r"\b(?:is|are|was|were)\s+expected\s+to\b|\b(?:market|industry|Department|Government|Commission|Agency|"
    r"regulator\w*)\b"
)
_QUARTER_END = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
_ORD = {"first": 1, "second": 2, "third": 3, "fourth": 4}


NORMALIZATION_ID = "ws_collapse_v1"


@dataclass
class Candidate:
    quote_literal: str
    speaker: str
    speaker_role: str
    due_date_hint: date | None
    due_basis: str  # "year_end_hint" | "quarter_end_hint" | "none"
    flags: list[str] = field(default_factory=list)
    char_start: int = 0  # offsets sobre normalize_for_locator(texto), NO sobre el original
    char_end: int = 0
    normalization: str = NORMALIZATION_ID
    context_before: str = ""
    context_after: str = ""
    support_quote: str = ""  # frase previa del mismo turno (<=300 chars), contexto, no compromiso
    parser: str = "lineas_hablante"  # "lineas_hablante" | "bloques_pdf"
    source_status: str = "suggested"  # nunca "verified": lo decide una persona con la fuente


def normalize_for_locator(text: str) -> str:
    """Normalizacion publica ws_collapse_v1: NBSP->espacio, colapsa blancos, strip."""
    return re.sub(r"\s+", " ", text.replace("\u00a0", " ")).strip()


_normalize = normalize_for_locator


def locator_for(c: Candidate) -> str:
    """Localizador explicito para transcript_locator: indica la normalizacion usada."""
    return f"{c.normalization}:{c.char_start}-{c.char_end}"


_ANALYST_ROLE = re.compile(
    r"research|analyst|equity|securities|capital markets|bank|asset management|sell[- ]side",
    re.I,
)


def _roster(lines: list[str]) -> dict[str, str]:
    """Cargos de la presentacion. Solo ANTES del turno del operador (Q&A) y sin cargos de analista."""
    roster: dict[str, str] = {}
    for line in lines:
        if roster and line.strip().startswith("Operator:"):
            break
        m = _ROLE_HEADER.match(line.strip())
        if m and not line.startswith(" " * 4) and not _ANALYST_ROLE.search(m.group(2)):
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


_BLOCK_NAME = re.compile(r"^[A-Z][\w.'’-]+(?: [A-Z][\w.'’-]*\.?){1,3}$")
_BLOCK_ROLE = re.compile(
    r"^(?:Chief|Co-|CEO|CFO|COO|CTO|President|Chair\w*|Director|Head|VP|Vice|Managing|Executive|Founder|"
    r"Treasurer|Senior Vice|General Counsel|Principal)\b[\w ,&/.\-–]{0,110}$"
)
_BLOCK_OTHER = re.compile(
    r"^(?:Analyst\b|.*\b(?:Inc\.?|LLC|Ltd\.?|Securities|Capital|Research|Bank|ISI|Partners|Markets|Asset Management)\b.*)$"
)


def _turns_blocks(text: str) -> tuple[list[tuple[str, str, str]], dict[str, str]]:
    """Transcripciones PDF en bloques: linea de nombre + linea de cargo + texto. (hablante, cargo, texto).

    Solo cuentan hablantes con cargo directivo; analistas/operador cortan el turno (no se mezclan).
    """
    lines = [ln.strip() for ln in text.replace("\f", "\n").splitlines()]
    turns: list[tuple[str, str, list[str]]] = []
    roster: dict[str, str] = {}
    cur: int | None = None
    i = 0
    while i < len(lines):
        ln = lines[i]
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if not ln or ln.isdigit() or set(ln) <= {".", " "}:
            i += 1
            continue
        if re.match(r"^Operator\b", ln):
            cur = None
            i += 1
            continue
        if _BLOCK_NAME.match(ln) and nxt:
            if _BLOCK_ROLE.match(nxt) and not _ANALYST_ROLE.search(nxt):
                roster.setdefault(ln, nxt)
                turns.append((ln, nxt, []))
                cur = len(turns) - 1
                i += 2
                continue
            if _BLOCK_OTHER.match(nxt):
                cur = None
                i += 2
                continue
        if cur is not None:
            turns[cur][2].append(ln)
        i += 1
    return [(w, r, " ".join(p)) for w, r, p in turns], roster


_ABBREV = re.compile(
    r"(?:\b(?:U\.S|U\.K|E\.U|Inc|Corp|Co|Ltd|Mr|Ms|Mrs|Dr|vs|e\.g|i\.e|approx|No|St|Jr|Sr)|\b[A-Z])\.$"
)


def _split_sentences(text: str) -> list[str]:
    """Parte en frases sin cortar tras abreviaturas (U.S., Inc., Mr., inicial suelta)."""
    out: list[str] = []
    start = 0
    for m in re.finditer(r"[.!?]\s+(?=[A-Z“\"])", text):
        head = text[start : m.start() + 1]
        if _ABBREV.search(head):
            continue
        out.append(text[start : m.start() + 1].strip())
        start = m.end()
    tail = text[start:].strip()
    if tail:
        out.append(tail)
    return [x for x in out if x]


_HORIZON = re.compile(r"\b(?:by|until)\s+(?:the\s+)?(?:end\s+of\s+(?:the|this)\s+year|year[- ]end)\b", re.I)


def _due_hint(sentence: str, call_date: date | None = None) -> tuple[date | None, str]:
    q = re.search(r"\b(first|second|third|fourth)\s+quarter(?:\s+of)?\s+(20\d{2})", sentence, re.I)
    if q:
        month, day = _QUARTER_END[_ORD[q.group(1).lower()]]
        return date(int(q.group(2)), month, day), "quarter_end_hint"
    # Solo con el anio pegado a la expresion; "this year" o un anio de referencia
    # (p. ej. "above 2025 operating income") NO generan fecha.
    y = re.search(r"\b(?:full[- ]year|remaining quarters of|by the end of|end of)\s+(20\d{2})\b", sentence, re.I)
    if y:
        return date(int(y.group(1)), 12, 31), "year_end_hint"
    # "by year-end" / "by the end of the year": SIN anio en la frase. Se interpreta con el anio de
    # la llamada (dato aportado por quien llama), explicitado en due_basis; es una inferencia.
    if call_date is not None and _HORIZON.search(sentence):
        return date(call_date.year, 12, 31), "year_end_inferred_from_call_year"
    return None, "none"


def extract_candidates(
    transcript_text: str, *, max_candidates: int = 40, call_date: date | None = None
) -> list[Candidate]:
    return extract_with_diagnostics(transcript_text, max_candidates=max_candidates, call_date=call_date)[0]


def extract_with_diagnostics(
    transcript_text: str, *, max_candidates: int = 40, call_date: date | None = None
) -> tuple[list[Candidate], dict]:
    """(candidatos, {parser, management_turns}). management_turns == 0 => formato NO soportado
    (no se reconocen hablantes directivos): NO equivale a "sin compromisos"."""
    lines = transcript_text.splitlines()
    roster = _roster(lines)
    haystack = _normalize(transcript_text.replace("\f", "\n"))
    parser = "lineas_hablante"
    turns = _turns(transcript_text, roster)
    if not turns:
        block_turns, roster = _turns_blocks(transcript_text)
        turns = [(w, b) for w, _r, b in block_turns]
        parser = "bloques_pdf"
    diag = {"parser": parser, "management_turns": len(turns)}
    out: list[Candidate] = []
    seen: set[str] = set()
    for speaker, body in turns:
        prev = ""
        for sentence in _split_sentences(_normalize(body)):
            previous, prev = prev, sentence
            checkable = _CHECKABLE.search(sentence) or (_HORIZON.search(sentence) and re.search(r"\d", sentence))
            if _BOILERPLATE.search(sentence) or not _FORWARD.search(sentence) or not checkable:
                continue
            if len(sentence) < 25 or len(sentence) > 600 or sentence in seen:
                continue
            start = haystack.find(sentence)
            if start < 0:  # la cita debe ser subcadena exacta; si no, se descarta
                continue
            seen.add(sentence)
            due, basis = _due_hint(sentence, call_date)
            flags = []
            if _CONDITIONAL.search(sentence):
                flags.append("conditional")
            if _NEGATION.search(sentence):
                flags.append("negation_present")
            if _THIRD_PARTY.search(sentence):
                flags.append("mercado_o_tercero_mencionado")
            if basis == "year_end_inferred_from_call_year":
                flags.append("due_year_inferred")
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
                    context_before=haystack[max(0, start - 80) : start],
                    context_after=haystack[start + len(sentence) : start + len(sentence) + 80],
                    support_quote=previous[:300] if previous and haystack.find(previous) >= 0 else "",
                    parser=parser,
                )
            )
            if len(out) >= max_candidates:
                return out, diag
    return out, diag
