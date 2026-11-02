"""Validador de citas: una cifra solo vale si está en la evidencia que cita.

Reglas (además de la comprobación básica: cita existente, de ESTA corrida, de
ESTE experto y de una herramienta de su lista blanca):

- Cada número de ``claim.numbers`` y cada cifra escrita en ``claim.text`` debe
  aparecer en los datos (o la fecha de la fuente) de alguna evidencia citada.
- Tolerancia de redondeo relativa (0,5 % por defecto) y cambios de escala
  habituales al escribir (0,11 ↔ 11 %, 245 ↔ 245.000 millones…); las fechas
  de la fuente solo valen tal cual.
- Se aceptan formatos ES y EN («1.234,5», «1,234.5»). Los enteros de 0 a 10
  sin decimales («3 lentes», «2 escenarios») no se tratan como cifras.

Modo ``drop`` (defecto): la afirmación se descarta con el motivo. Modo
``mark``: se conserva marcada como «sin fuente» (motivo con prefijo ``mark:``).
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from typing import Any, Literal

from app.services.expert_team.experts import ExpertSpec, Validator, basic_citation_check
from app.services.expert_team.ledger import EvidenceLedger
from app.services.expert_team.models import Claim

MARK_PREFIX = "mark:"
_NUMBER = re.compile(r"(?<![\w.,])-?\d+(?:[.,]\d+)*")
_EVIDENCE_ID = re.compile(r"\bev-\d+\b")


def _readings(token: str) -> set[float]:
    """Todas las lecturas razonables de un número escrito (ES o EN)."""
    token = token.strip()
    out: set[float] = set()
    candidates = {token.replace(",", ""), token.replace(".", "").replace(",", ".")}
    if token.count(",") == 1 and "." not in token:
        candidates.add(token.replace(",", "."))
    if token.count(".") == 1 and "," not in token:
        candidates.add(token)
    for cand in candidates:
        try:
            out.add(float(cand))
        except ValueError:
            continue
    return out


def _numbers_in(value: Any) -> Iterable[float]:
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, int | float):
        if math.isfinite(value):
            yield float(value)
    elif isinstance(value, str):
        for token in _NUMBER.findall(value):
            yield from _readings(token)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _numbers_in(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _numbers_in(item)


def _close(a: float, b: float, rel_tol: float, *, scaled: bool = True) -> bool:
    """``a`` (escrito) frente a ``b`` (dato). El signo se escribe con palabras
    («cae un 5 %»): se compara en valor absoluto. Escalas: ratio↔% solo para
    ratios (|dato| ≤ 1,5 o |escrito| ≤ 1,5) y miles/millones/miles de millones."""
    a, b = abs(a), abs(b)
    if math.isclose(a, b, rel_tol=rel_tol, abs_tol=1e-9):
        return True
    if not scaled:
        return False
    if b <= 1.5 and math.isclose(a, b * 100, rel_tol=rel_tol):
        return True
    if a <= 1.5 and math.isclose(a * 100, b, rel_tol=rel_tol):
        return True
    return any(math.isclose(a, b * s, rel_tol=rel_tol) for s in (1e3, 1e6, 1e9, 1e-3, 1e-6, 1e-9))


def _is_trivial(token: str) -> bool:
    return token.isdigit() and int(token) <= 10


def figures_supported(text: str, source: Any, rel_tol: float = 0.005) -> bool:
    """Cada cifra escrita en ``text`` (salvo enteros 0–10 e ids ev-N) aparece en
    ``source`` (texto o datos), con la misma tolerancia y escalas que una afirmación."""
    known = list(_numbers_in(source))
    for token in _NUMBER.findall(_EVIDENCE_ID.sub(" ", text)):
        if _is_trivial(token):
            continue
        if not any(_close(r, k, rel_tol) for r in _readings(token) for k in known):
            return False
    return True


def citation_validator(*, mode: Literal["drop", "mark"] = "drop", rel_tol: float = 0.005) -> Validator:
    def validate(claim: Claim, ledger: EvidenceLedger, spec: ExpertSpec) -> str:
        reason = basic_citation_check(claim, ledger, spec)
        if not reason:
            data_numbers: list[float] = []
            source_numbers: list[float] = []  # fechas/ids de la fuente: solo coincidencia exacta
            for cid in claim.citations:
                evidence = ledger.get(cid)
                if evidence is not None:
                    data_numbers.extend(_numbers_in(evidence.data))
                    source_numbers.extend(_numbers_in(dict(evidence.source)))
            wanted: list[set[float]] = [{n} for n in claim.numbers]
            wanted += [_readings(t) for t in _NUMBER.findall(_EVIDENCE_ID.sub(" ", claim.text)) if not _is_trivial(t)]
            for readings in wanted:
                if not any(_close(r, k, rel_tol) for r in readings for k in data_numbers) and not any(
                    _close(r, k, rel_tol, scaled=False) for r in readings for k in source_numbers
                ):
                    reason = "number_not_in_evidence"
                    break
        if reason and mode == "mark":
            return MARK_PREFIX + reason
        return reason

    return validate
