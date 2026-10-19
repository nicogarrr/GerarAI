"""Textual year-on-year changes, never a claim of financial materiality.

Only comparable reported periods are paired. Missing sections are unknown,
not evidence of a deletion. Quotes retain their original language and figures.
"""
from __future__ import annotations

import re
from datetime import date
from difflib import SequenceMatcher

SECTION_LABELS = {
    "risk_factors": "Factores de riesgo",
    "guidance": "Perspectivas y guidance",
    "related_parties": "Partes relacionadas",
}
_HEADINGS = {
    "risk_factors": re.compile(r"^(?:item\s+1a[.\s:-]*|\d+[.\s]*)?(?:risk factors|factores de riesgo)\s*[.:]?\s*$", re.I),
    "guidance": re.compile(r"^(?:\d+[.\s]*)?(?:guidance|outlook|business outlook|financial outlook|perspectivas|previsiones)\s*[.:]?\s*$", re.I),
    "related_parties": re.compile(r"^(?:(?:note|nota|item)\s+\d+[.\s:-]*|\d+[.\s]*)?(?:related[- ]party (?:transactions|disclosures)|related parties|transacciones con partes (?:relacionadas|vinculadas)|partes (?:relacionadas|vinculadas))\s*[.:]?\s*$", re.I),
}
_ITEM = re.compile(r"^(?:item\s+\d+[a-z]?[.\s:-]|(?:note|nota)\s+\d+[.\s:-])", re.I)
_GUIDANCE = re.compile(r"\b(?:guidance|outlook|forecast|expects? (?:revenue|sales|earnings)|previsiones|perspectivas)\b", re.I)
_RELATED = re.compile(r"\b(?:related[- ]part(?:y|ies)|partes (?:relacionadas|vinculadas))\b", re.I)


def normalized(text: str) -> str:
    return " ".join(text.split())


def reported_period(metadata: dict) -> date | None:
    value = metadata.get("period_of_report") or metadata.get("report_date")
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def comparable(current: dict, previous: dict) -> bool:
    """Same base form and year-ago reported end, including 52/53-week years."""
    form = current.get("form")
    if form not in {"10-K", "10-Q", "20-F", "40-F", "annual_report"} or form != previous.get("form"):
        return False
    now, before = reported_period(current), reported_period(previous)
    if now is None or before is None or now.year - before.year != 1:
        return False
    # Explicit quarter identity, when present, must also agree.
    if current.get("fiscal_quarter") != previous.get("fiscal_quarter"):
        return False
    try:
        anniversary = before.replace(year=now.year)
    except ValueError:
        anniversary = before.replace(year=now.year, day=28)
    return abs((now - anniversary).days) <= 15


def excerpt_units(chunks: list[dict]) -> list[dict]:
    """Deduplicate overlapping ingestion chunks without losing quote identity."""
    units, seen = [], set()
    for chunk in chunks:
        for line in chunk["text"].splitlines():
            pieces = [line] if any(pattern.fullmatch(normalized(line)) for pattern in _HEADINGS.values()) else re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚ])", line)
            for sentence in pieces:
                text = normalized(sentence)
                if not text or text in seen:
                    continue
                seen.add(text)
                units.append({"text": text, "chunk_id": chunk["id"], "chunk_index": chunk["chunk_index"]})
    return units


def sections(chunks: list[dict]) -> dict[str, list[dict]]:
    units = excerpt_units(chunks)
    found: dict[str, list[dict]] = {key: [] for key in SECTION_LABELS}
    active = None
    for unit in units:
        text = unit["text"]
        heading = next((key for key, pattern in _HEADINGS.items() if pattern.fullmatch(text)), None)
        if heading:
            active = heading
            continue
        if _ITEM.match(text):
            active = None
        # Inline guidance / related-party statements are useful even where
        # PDF/HTML extraction lost headings. No inline risk inference.
        key = active
        if key is None and _GUIDANCE.search(text):
            key = "guidance"
        if key is None and _RELATED.search(text):
            key = "related_parties"
        if key and len(text) >= 30:
            found[key].append(unit)
    return found


def compare_sections(current: list[dict], previous: list[dict], *, limit: int = 20) -> dict:
    new, old = sections(current), sections(previous)
    result = []
    for key, label in SECTION_LABELS.items():
        before, after = old[key], new[key]
        if not before or not after:
            result.append({"section": key, "label": label, "status": "insufficient_data", "changes": [],
                           "reason": "Sin texto identificable en uno o ambos informes."})
            continue
        if len(before) > 5000 or len(after) > 5000:
            result.append({"section": key, "label": label, "status": "insufficient_data", "changes": [],
                           "reason": "Sección demasiado extensa para la comparación acotada."})
            continue
        matcher = SequenceMatcher(a=[u["text"] for u in before], b=[u["text"] for u in after], autojunk=False)
        changes = []
        count = 0
        for tag, i, j, k, l in matcher.get_opcodes():
            if tag == "equal":
                continue
            count += 1
            if len(changes) < limit:
                changes.append({"kind": {"replace": "modified", "insert": "added", "delete": "removed"}[tag],
                                "before": before[i:j][:5], "after": after[k:l][:5],
                                "quotes_truncated": j - i > 5 or l - k > 5})
        result.append({"section": key, "label": label, "status": "changed" if count else "unchanged",
                       "changes": changes, "change_count": count, "truncated": count > limit})
    return {"status": "changed" if any(s["status"] == "changed" for s in result)
            else "unchanged" if all(s["status"] == "unchanged" for s in result) else "partial",
            "method": "derived_text_diff", "label": "Comparación textual, no materialidad financiera",
            "sections": result}
