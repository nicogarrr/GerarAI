"""Tesis larga de los agentes sobre el SOTP determinista (Nico, 8-nov-2026 11:57).

«Cifras 100 % deterministas + una tesis EXTENSA en prosa natural escrita por los
expertos que va narrando y explicando esas cifras (no las calcula).»

* El código calcula todas las cifras (``sotp_markers``) y se las da al modelo
  como MARCADORES (``{{sotp.base_per_share}}``). El modelo escribe la prosa
  con esos marcadores, nunca con números propios.
* ``validate_narrative`` rechaza cualquier número del texto que no venga de un
  marcador (salvo años y fechas); un reintento con la lista; si vuelve a
  fallar, se publica con esos números quitados (``strip_free_numbers``).
* ``render_narrative`` sustituye cada marcador por su valor al mostrar: la
  prosa puede variar entre ejecuciones, las cifras nunca.
* Caché: se guarda junto a la propuesta, con su huella (la del SOTP + versión
  del prompt de la tesis); misma huella → mismo texto, sin llamar al modelo.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from app.services.expert_team.experts import Reasoner

logger = logging.getLogger(__name__)

NARRATIVE_VERSION = "sotp-narrative-v1"
SECTIONS: tuple[tuple[str, str], ...] = (
    ("resumen", "Resumen"),
    ("negocio", "El negocio"),
    ("partes", "Desglose por partes"),
    ("dilucion_balance", "Dilución y balance"),
    ("casos", "Casos alcista, base y bajista"),
    ("que_puede_pasar", "Qué puede pasar: catalizadores y riesgos"),
    ("noticias", "Noticias recientes"),
    ("conclusion", "Conclusión"),
)
MARKER = re.compile(r"\{\{\s*([a-z0-9_.]+)\s*\}\}")
#: Años (1900–2099), fechas ISO y números de sección «1.» al inicio de línea se permiten.
_ALLOWED = re.compile(
    r"\b(?:19|20)\d{2}-\d{2}-\d{2}\b|\b(?:19|20)\d{2}\b"
    r"|\b(?:\d{1,2}-[KQF]|S-1|13[DFG]|Form\s?\d|F-\d)\b"  # formularios SEC (8-K, 10-Q, 20-F, 13F…)
)
_NUMBER = re.compile(r"[-−+]?\$?\d[\d.,]*\s*(?:%|\$|M\$|M|x|veces)?")
MAX_ATTEMPTS = 2

NARRATIVE_CONTRACT = (
    "Responde SOLO con JSON: {\"sections\": {"
    + ", ".join(f'"{key}": str' for key, _ in SECTIONS)
    + "}}. Cada sección, 1–3 párrafos en prosa natural en español. TODA cifra (precios, $/acción, %, "
    "millones, acciones, múltiplos, probabilidades) se escribe SOLO con un marcador de la lista, tal cual "
    "({{nombre}}): nunca escribas un número tú. Puedes usar años. Explica qué significan las cifras, de dónde "
    "salen y qué tendría que pasar para que cambien; no calcules nada nuevo."
)

NARRATIVE_PROMPT = (
    "Eres el REDACTOR DE LA TESIS del equipo de GerarAI. Te damos el desglose por partes ya calculado por el "
    "código (cifras como marcadores con su valor), la clasificación de los expertos, los avisos, los "
    "segmentos sin valorar y los titulares recientes. Escribe una tesis larga y clara para un inversor "
    "particular: qué es la empresa, cuánto vale cada parte y por qué, cuánto pesa la dilución y el balance, "
    "los tres casos, qué puede pasar y qué noticias importan. Sé honesto con lo que está sin probar. Nunca "
    "aportes cifras propias: usa los marcadores."
)


def _fmt_money(value: float | None, unit: str = "$") -> str:
    if value is None:
        return "N/D"
    sign = "−" if value < 0 else ""
    text = f"{abs(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{sign}{text} {unit}".strip()


def _fmt_millions(value: float | None, unit: str = "M$") -> str:
    if value is None:
        return "N/D"
    sign = "−" if value < 0 else ""
    text = f"{abs(value):,.0f}".replace(",", ".")
    return f"{sign}{text} {unit}"


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "N/D"
    return f"{value * 100:+.0f} %".replace("+", "+").replace("-", "−")


def _fmt_share_count(value: float | None) -> str:
    if value is None:
        return "N/D"
    return f"{value:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".") + " M"


def sotp_markers(model: Mapping[str, Any], result: Mapping[str, Any]) -> dict[str, str]:
    """Marcadores → valor ya formateado. Todo sale del modelo y de su cálculo (``run_user_sotp``)."""
    currency = str(model.get("currency") or "")
    unit = "$" if currency in ("USD", "") else currency
    munit = "M$" if currency in ("USD", "") else f"M {currency}"  # millones en la moneda del modelo
    scen = {s.get("key"): s for s in result.get("scenarios") or []}
    markers: dict[str, str] = {
        "sotp.base_per_share": _fmt_money(result.get("value_per_share"), unit),
        "sotp.bear_per_share": _fmt_money((scen.get("bear") or {}).get("value_per_share"), unit),
        "sotp.bull_per_share": _fmt_money((scen.get("bull") or {}).get("value_per_share"), unit),
        "sotp.price": _fmt_money(result.get("price"), unit),
        "sotp.vs_price": _fmt_pct(result.get("vs_price")),
        "sotp.discount_rate": f"{float(model.get('discount_rate') or 0) * 100:.1f} %".replace(".", ","),
        "sotp.valuation_year": str(model.get("valuation_year") or ""),
        "sotp.total_present_value": _fmt_millions(result.get("total_present_value"), munit),
        "dilution.current_shares": _fmt_share_count(model.get("shares_current")),
        "dilution.total_shares": _fmt_share_count(result.get("shares_diluted")),
        "dilution.new_shares": _fmt_share_count(
            (result.get("shares_diluted") or 0) - float(model.get("shares_current") or 0)
            if result.get("shares_diluted") is not None else None
        ),
    }
    for i, scenario in enumerate(model.get("scenarios") or []):
        key = scenario.get("key") or f"s{i}"
        if scenario.get("revenue_factor") is not None:
            markers[f"scenario.{key}.revenue_factor"] = f"{scenario['revenue_factor'] * 100:.0f} %"
        if scenario.get("multiple_factor") is not None:
            markers[f"scenario.{key}.multiple_factor"] = f"{scenario['multiple_factor'] * 100:.0f} %"
        if scenario.get("delay_years") is not None:
            markers[f"scenario.{key}.delay_years"] = f"{scenario['delay_years']:g}".replace(".", ",")
    for i, row in enumerate(result.get("rows") or [], start=1):
        prefix = f"part.{i}"
        markers[f"{prefix}.value_per_share"] = _fmt_money(row.get("value_per_share"), unit)
        if row.get("revenue") is not None:
            markers[f"{prefix}.revenue"] = _fmt_millions(row.get("revenue"), munit)
        if row.get("ebitda_margin") is not None:
            markers[f"{prefix}.margin"] = f"{row['ebitda_margin'] * 100:.0f} %"
        if row.get("multiple") is not None:
            markers[f"{prefix}.multiple"] = f"{row['multiple']:g}x".replace(".", ",")
        if row.get("probability") is not None:
            markers[f"{prefix}.probability"] = f"{row['probability'] * 100:.0f} %"
        if row.get("value") is not None:
            markers[f"{prefix}.value"] = _fmt_millions(row.get("value"), munit)
    for i, item in enumerate(model.get("dilution") or [], start=1):
        markers[f"dilution.{i}.shares"] = _fmt_share_count(item.get("shares"))
    return markers


def marker_catalog(model: Mapping[str, Any], result: Mapping[str, Any]) -> list[dict[str, str]]:
    """Lo que ve el modelo: cada marcador con su valor y qué es (nombres de partes incluidos)."""
    markers = sotp_markers(model, result)
    names = {f"part.{i}": row.get("name") for i, row in enumerate(result.get("rows") or [], start=1)}
    names.update({f"dilution.{i}": d.get("label") for i, d in enumerate(model.get("dilution") or [], start=1)})
    out = []
    for key, value in markers.items():
        stem = ".".join(key.split(".")[:2])
        out.append({"marker": "{{" + key + "}}", "value": value, "of": names.get(stem) or key})
    return out


def free_numbers(text: str) -> list[str]:
    """Números del texto que NO vienen de un marcador (años y fechas aparte)."""
    stripped = MARKER.sub(" ", text or "")
    stripped = _ALLOWED.sub(" ", stripped)
    stripped = re.sub(r"(?m)^\s*#*\s*\d+[.)]\s", " ", stripped)  # numeración de listas
    return [m.group(0).strip() for m in _NUMBER.finditer(stripped) if any(ch.isdigit() for ch in m.group(0))]


def unknown_markers(text: str, markers: Mapping[str, str]) -> list[str]:
    return sorted({m.group(1) for m in MARKER.finditer(text or "") if m.group(1) not in markers})


def strip_free_numbers(text: str) -> str:
    """Último recurso: quita los números libres (deja años, fechas y marcadores)."""
    protected: list[str] = []

    def keep(match: re.Match[str]) -> str:
        protected.append(match.group(0))
        return "\x00" + chr(0xE000 + len(protected) - 1) + "\x00"

    work = MARKER.sub(keep, text)
    work = _ALLOWED.sub(keep, work)
    work = _NUMBER.sub(lambda m: "" if any(ch.isdigit() for ch in m.group(0)) else m.group(0), work)
    work = re.sub("\x00(.)\x00", lambda m: protected[ord(m.group(1)) - 0xE000], work)
    work = re.sub(r"[ \t]{2,}", " ", work)
    return re.sub(r"\s+([,.;:)])", r"\1", work)


def render_narrative(sections: Mapping[str, str], markers: Mapping[str, str]) -> dict[str, str]:
    """Sustituye cada marcador por su valor; uno desconocido se quita (nunca se inventa)."""
    def sub(match: re.Match[str]) -> str:
        return markers.get(match.group(1), "")

    return {key: MARKER.sub(sub, text or "") for key, text in sections.items()}


def narrative_fingerprint(sotp_fingerprint: str | None, markers: Mapping[str, str]) -> str:
    # Solo los NOMBRES de los marcadores: sus valores se sustituyen al mostrar (un precio nuevo no reescribe la prosa).
    blob = json.dumps({"v": NARRATIVE_VERSION, "sotp": sotp_fingerprint, "markers": sorted(markers)},
                      ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


@dataclass
class NarrativeResult:
    status: str  # ok | cached | stripped | rejected | error | no_model
    sections: dict[str, str] = field(default_factory=dict)  # con marcadores (lo que se guarda)
    problems: list[str] = field(default_factory=list)
    llm_calls: int = 0
    fingerprint: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "sections": self.sections, "problems": self.problems[:20],
                "llm_calls": self.llm_calls, "fingerprint": self.fingerprint, "version": NARRATIVE_VERSION}


def _parse_sections(text: str) -> dict[str, str] | None:
    from app.llm.json import parse_json_response

    try:
        parsed = parse_json_response(text)
    except Exception:  # noqa: BLE001
        return None
    raw = parsed.get("sections") if isinstance(parsed, dict) else None
    if not isinstance(raw, dict):
        return None
    out = {key: str(raw.get(key) or "").strip() for key, _ in SECTIONS}
    return out if any(out.values()) else None


async def write_narrative(
    *,
    reasoner: Reasoner,
    model: Mapping[str, Any],
    result: Mapping[str, Any],
    context: Mapping[str, Any],
    sotp_fingerprint: str | None,
    cached: Mapping[str, Any] | None = None,
    max_tokens: int = 12000,
) -> NarrativeResult:
    """Pide la tesis con marcadores, la valida y reintenta una vez; nunca lanza."""
    markers = sotp_markers(model, result)
    fp = narrative_fingerprint(sotp_fingerprint, markers)
    if cached and cached.get("fingerprint") == fp and cached.get("sections"):
        return NarrativeResult(status="cached", sections=dict(cached["sections"]), fingerprint=fp)
    payload: dict[str, Any] = {
        "markers": marker_catalog(model, result),
        "parts": [{"marker_prefix": f"part.{i}", "name": r.get("name"), "why": r.get("why")}
                  for i, r in enumerate(result.get("rows") or [], start=1)],
        "summary": model.get("summary"),
        "warnings": model.get("warnings") or [],
        "unvalued": model.get("unvalued") or [],
        **dict(context),
    }
    system = f"{NARRATIVE_PROMPT}\n\n{NARRATIVE_CONTRACT}"
    out = NarrativeResult(status="rejected", fingerprint=fp)
    last: dict[str, str] | None = None
    for _ in range(MAX_ATTEMPTS):
        out.llm_calls += 1
        try:
            text = await reasoner(system, json.dumps(payload, ensure_ascii=False, default=str), max_tokens,
                                  "expert_team.redactor_tesis_sotp")
        except Exception as exc:  # noqa: BLE001
            out.status, out.problems = "error", [f"llm:{type(exc).__name__}"]
            return out
        sections = _parse_sections(text)
        if sections is None:
            out.problems = ["la respuesta no trae las secciones en JSON"]
            payload["problems_previous_answer"] = out.problems
            continue
        last = sections
        problems = []
        for key, body in sections.items():
            loose = free_numbers(body)
            if loose:
                problems.append(f"{key}: números sin marcador: {', '.join(loose[:6])}")
            bad = unknown_markers(body, markers)
            if bad:
                problems.append(f"{key}: marcadores que no existen: {', '.join(bad[:6])}")
        if not problems:
            out.status, out.sections, out.problems = "ok", sections, []
            return out
        out.problems = problems
        payload["problems_previous_answer"] = problems[:20]
    if last is not None:
        # Segundo fallo: se publica con los números libres quitados y sin marcadores inventados.
        cleaned = {k: MARKER.sub(lambda m: m.group(0) if m.group(1) in markers else "", strip_free_numbers(v))
                   for k, v in last.items()}
        out.status, out.sections = "stripped", cleaned
    return out


__all__ = [
    "NARRATIVE_VERSION",
    "SECTIONS",
    "NarrativeResult",
    "free_numbers",
    "marker_catalog",
    "narrative_fingerprint",
    "render_narrative",
    "sotp_markers",
    "strip_free_numbers",
    "unknown_markers",
    "write_narrative",
]
