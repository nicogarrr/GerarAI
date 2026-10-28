"""Modo "analisis" del chat de la biblioteca: respuesta estructurada, validada o nada.

El modelo propone; aqui se valida todo. Si algo no encaja (JSON incompleto, citas que no
estan en los fragmentos enviados, probabilidades que no suman 100, cifras que no vienen del
contexto) se descarta el analisis entero y el chat degrada a fragmentos citados.
"""

from __future__ import annotations

import json
import re

from app.services.prompt_registry import get_prompt

NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
DISCLAIMER = "No es consejo financiero. Doctrina de la biblioteca, no datos actuales de empresas."
PROMPT = get_prompt("knowledge_analysis", allow_remote=False)
SYSTEM_PROMPT = PROMPT.text
_MAX_TEXT = 700


def build_messages(question: str, sources: dict) -> list[tuple[str, str]]:
    user = json.dumps(
        {
            "question": question,
            "sources": [
                {
                    "chunk_id": i,
                    "text": s["text"],
                    "author": s["citation"]["author"],
                    "title": s["citation"]["title"],
                }
                for i, s in sources.items()
            ],
        },
        ensure_ascii=False,
    )
    return [("system", SYSTEM_PROMPT), ("user", user)]


def _numbers(text: str) -> set[str]:
    return set(NUMBER.findall(text))


def clean_quote(quote, sent: str) -> str | None:
    """Cita literal de verdad: sin bordes en blanco, >=20 caracteres alfanumericos y dentro del texto enviado."""
    if not isinstance(quote, str):
        return None
    quote = quote.strip()
    if not 20 <= len(quote) <= 900 or sum(c.isalnum() for c in quote) < 20:
        return None
    # Los modelos colapsan saltos de linea y espacios dobles al copiar. Solo se
    # tolera esa diferencia de espacios en blanco: se devuelve el tramo EXACTO
    # del texto enviado (nunca la version del modelo), asi la cita sigue siendo
    # literal. Los bordes no pueden cortar una palabra ("precio" no vale dentro
    # de "sobreprecio" ni "valor" como prefijo de "valorado"). Palabras distintas
    # o puntos suspensivos se rechazan.
    words = quote.split()
    if not words:
        return None
    body = r"\s+".join(re.escape(w) for w in words)
    left = r"(?<!\w)" if words[0][0].isalnum() or words[0][0] == "_" else ""
    right = r"(?!\w)" if words[-1][-1].isalnum() or words[-1][-1] == "_" else ""
    match = re.search(left + body + right, sent)
    if match is None:
        return None
    span = match.group(0)
    # Los espacios del texto original pueden inflar el tramo: se revalida.
    if not 20 <= len(span) <= 900:
        return None
    return span


def _plain(value, low: int = 1, high: int = _MAX_TEXT) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if low <= len(value) <= high else None


def _cited(item, sources: dict) -> dict | None:
    """Un punto con cita: texto + cita literal. Las cifras del texto deben estar en la cita."""
    if not isinstance(item, dict) or type(item.get("chunk_id")) is not int:
        return None
    source = sources.get(item["chunk_id"])
    text = _plain(item.get("text"))
    quote = clean_quote(item.get("quote"), source["text"]) if source else None
    if not source or text is None or quote is None:
        return None
    if not _numbers(text) <= _numbers(quote):
        return None
    out = {"text": text, "citation": {**source["citation"], "quote": quote}}
    name = item.get("nombre")
    if name is not None:
        name = _plain(name, 1, 120)
        if name is None:
            return None
        out["nombre"] = name
    return out


def validate(payload, sources: dict) -> dict | None:
    """Devuelve el analisis limpio o None. Nada parcial: o esta completo o no se muestra."""
    if not isinstance(payload, dict):
        return None
    context_numbers = set().union(*(_numbers(s["text"]) for s in sources.values())) if sources else set()

    tesis = payload.get("tesis")
    if not isinstance(tesis, list) or len(tesis) != 3:
        return None
    tesis_ok = [_cited(item, sources) for item in tesis]
    error = _cited(payload.get("error"), sources)
    if error is None or any(item is None for item in tesis_ok):
        return None

    escenarios = payload.get("escenarios")
    if not isinstance(escenarios, list) or len(escenarios) != 3:
        return None
    scen_ok = []
    for item in escenarios:
        if not isinstance(item, dict):
            return None
        name, trigger, prob = (
            _plain(item.get("nombre"), 1, 120),
            _plain(item.get("disparador")),
            item.get("probabilidad"),
        )
        if name is None or trigger is None or type(prob) is not int or not 0 <= prob <= 100:
            return None
        # Sin cita propia: las cifras del escenario solo pueden venir del contexto enviado.
        if not (_numbers(name) | _numbers(trigger)) <= context_numbers:
            return None
        scen_ok.append({"nombre": name, "probabilidad": prob, "disparador": trigger})
    if sum(s["probabilidad"] for s in scen_ok) != 100:
        return None

    modelos = payload.get("modelos")
    if not isinstance(modelos, list) or not 1 <= len(modelos) <= 4:
        return None
    modelos_ok = [_cited(item, sources) for item in modelos]
    if any(item is None or "nombre" not in item for item in modelos_ok):
        return None

    no_se = payload.get("no_se")
    if not isinstance(no_se, list) or not 1 <= len(no_se) <= 4:
        return None
    no_se_ok = [_plain(item) for item in no_se]
    if (
        any(item is None for item in no_se_ok)
        or not set().union(*(_numbers(t) for t in no_se_ok)) <= context_numbers
    ):
        return None

    return {
        "tesis": tesis_ok,
        "error": error,
        "escenarios": scen_ok,
        "modelos": modelos_ok,
        "no_se": no_se_ok,
        "probabilidades": "Estimación del modelo, no un dato.",
        "aviso": DISCLAIMER,
    }
