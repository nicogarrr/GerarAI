"""Parser iXBRL (inline XBRL) de paquetes ESEF descargados del emisor.

filings.xbrl.org (el indice gratuito que alimenta los snapshots ESEF) no
indexa Irlanda: `filter[country]=IE` devuelve 0 filings (verificado
2026-10-19). Kerry Group publica su paquete ESEF (zip ESMA: xhtml iXBRL +
taxonomia de extension) en kerry.com, asi que la cobertura IE entra por un
parser iXBRL propio que produce EXACTAMENTE el mismo layout normalizado que
`normalize_xbrl_json` (xBRL-JSON): {concepto: {unidad: [{start|end|instant,
val, decimals, lei, dims}]}}.

Contrato de veracidad: solo se emiten hechos declarados por el emisor en el
documento. Las transformaciones ixt (num-dot-decimal, fixed-zero, ...) se
aplican segun el registro de transformaciones iXBRL (es la lectura canonica
del hecho, no un calculo). Un hecho sin contexto, sin unidad o con valor
irreconocible se DESCARTA (contado en `dropped`), nunca se adivina. Los
hechos dimensionados conservan sus ejes en `dims`: los consumidores solo leen
el consolidado (dims == []), igual que en el carril del indice.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, BinaryIO

from lxml import etree

IX_NS = "http://www.xbrl.org/2013/inlineXBRL"
XBRLI_NS = "http://www.xbrl.org/2003/instance"
XBRDI_NS = "http://xbrl.org/2006/xbrldi"

_IX = "{" + IX_NS + "}"
_XBRLI = "{" + XBRLI_NS + "}"
_XBRDI = "{" + XBRDI_NS + "}"

_BASE_DIMENSIONS = {"entity", "period", "unit", "concept", "identifier", "scheme"}


@dataclass(frozen=True)
class _Context:
    start: str | None
    end: str | None
    instant: str | None
    lei: str | None
    dims: tuple[str, ...]  # ejes dimensionales (prefijados), ordenados


def _text(elem: etree._Element) -> str:
    return "".join(elem.itertext())


def _collect_continuations(
    elem: etree._Element, by_id: dict[str, etree._Element]
) -> str:
    """Texto del hecho siguiendo la cadena ix:continuation (iXBRL 1.1).

    Las cifras partidas entre spans enlazan con continuationRef; el valor
    completo es la concatenacion en orden de la cadena."""
    parts = [_text(elem)]
    ref = elem.get("continuationRef")
    seen: set[str] = set()
    while ref and ref not in seen:
        seen.add(ref)
        nxt = by_id.get(ref)
        if nxt is None:
            break
        parts.append(_text(nxt))
        ref = nxt.get("continuationRef")
    return "".join(parts)


def _transform_numeric(raw: str, fmt: str | None) -> Decimal | None:
    """Valor canonico del hecho segun su formato ixt declarado.

    Devuelve None cuando el formato es desconocido o el texto no es una cifra
    reconocible: mejor perder el hecho que inventar su valor."""
    text = "".join(raw.split())
    if not text:
        return None
    fmt_local = (fmt or "num-dot-decimal").rsplit(":", 1)[-1]
    if fmt_local in {"fixed-zero", "numdash", "num-dash"} or text in {"-", "—", "–"}:
        return Decimal(0)
    if fmt_local in {"num-dot-decimal", "numdotdecimal"}:
        text = text.replace(",", "")
    elif fmt_local in {"num-comma-decimal", "numcommadecimal"}:
        text = text.replace(".", "").replace(",", ".")
    elif fmt_local in {"num-space-dot", "numspacedot"}:
        text = text.replace(" ", "").replace(" ", "")
    elif fmt_local in {"num-space-comma", "numspacecomma"}:
        text = text.replace(" ", "").replace(" ", "").replace(",", ".")
    else:
        return None  # formato ixt no revisado: no se interpreta
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return -value if negative else value


def parse_ixbrl_facts(source: str | BinaryIO) -> dict[str, Any]:
    """xhtml iXBRL -> layout normalizado identico a normalize_xbrl_json.

    Devuelve {"facts": {concepto: {unidad: [entradas]}}, "dropped": n,
    "entity_lei": lei_mas_frecuente}."""
    # huge_tree: los informes ESEF llevan nodos de texto de varios MB
    # (el limite por defecto de libxml2 rechaza informes reales, p.ej.
    # Kerry FY2021 linea 192).
    tree = etree.parse(source, etree.XMLParser(huge_tree=True))
    root = tree.getroot()

    contexts: dict[str, _Context] = {}
    units: dict[str, str] = {}
    continuations: dict[str, etree._Element] = {}

    for elem in root.iter():
        if elem.tag == _XBRLI + "context" and elem.get("id"):
            lei = None
            start = end = instant = None
            dims: list[str] = []
            for child in elem.iter():
                if child.tag == _XBRLI + "identifier":
                    lei = (child.text or "").strip() or None
                elif child.tag == _XBRLI + "startDate":
                    start = (child.text or "").strip() or None
                elif child.tag == _XBRLI + "endDate":
                    end = (child.text or "").strip() or None
                elif child.tag == _XBRLI + "instant":
                    instant = (child.text or "").strip() or None
                elif child.tag in {_XBRDI + "explicitMember", _XBRDI + "typedMember"}:
                    axis = (child.get("dimension") or "").strip()
                    # Typed dimensions carry scope too, even though their
                    # member value is XML rather than a QName. A malformed
                    # missing axis must never look consolidated either.
                    dims.append(axis or "__unknown_dimension__")
            contexts[elem.get("id")] = _Context(
                start=start, end=end, instant=instant, lei=lei, dims=tuple(sorted(dims))
            )
        elif elem.tag == _XBRLI + "unit" and elem.get("id"):
            divide = elem.find(_XBRLI + "divide")
            if divide is not None:
                num = divide.find(_XBRLI + "unitNumerator/" + _XBRLI + "measure")
                den = divide.find(_XBRLI + "unitDenominator/" + _XBRLI + "measure")
                num_t = (num.text or "").strip() if num is not None else ""
                den_t = (den.text or "").strip() if den is not None else ""
                # Mismo convenio que filings.xbrl.org: "iso4217:EUR/xbrli:shares".
                if num_t and den_t:
                    units[elem.get("id")] = f"{num_t}/{den_t}"
            else:
                measure = elem.find(_XBRLI + "measure")
                if measure is not None and (measure.text or "").strip():
                    units[elem.get("id")] = (measure.text or "").strip()
        elif elem.tag == _IX + "continuation" and elem.get("id"):
            continuations[elem.get("id")] = elem

    facts: dict[str, dict[str, list[dict[str, Any]]]] = {}
    dropped = 0
    lei_counts: dict[str, int] = {}

    for elem in root.iter(_IX + "nonFraction"):
        name = (elem.get("name") or "").strip()
        ctx = contexts.get(elem.get("contextRef") or "")
        unit = units.get(elem.get("unitRef") or "")
        raw = _collect_continuations(elem, continuations)
        value = _transform_numeric(raw, elem.get("format"))
        if not name or ctx is None or not unit or value is None:
            dropped += 1
            continue
        scale_raw = elem.get("scale")
        if scale_raw:
            try:
                value = value * (Decimal(10) ** int(scale_raw))
            except (ValueError, InvalidOperation):
                dropped += 1
                continue
        if (elem.get("sign") or "").strip() == "-":
            value = -value
        if ctx.lei:
            lei_counts[ctx.lei] = lei_counts.get(ctx.lei, 0) + 1
        entry: dict[str, Any] = {}
        if ctx.start:
            entry["start"] = ctx.start
        if ctx.end:
            entry["end"] = ctx.end
        if ctx.instant:
            entry["instant"] = ctx.instant
        entry["val"] = format(value, "f")
        entry["decimals"] = elem.get("decimals")
        entry["lei"] = ctx.lei
        entry["dims"] = list(ctx.dims)
        facts.setdefault(name, {}).setdefault(unit, []).append(entry)

    for concepts in facts.values():
        for entries in concepts.values():
            entries.sort(key=lambda e: e.get("end") or e.get("instant") or "")

    entity_lei = max(lei_counts, key=lambda lei: lei_counts[lei]) if lei_counts else None
    return {"facts": facts, "dropped": dropped, "entity_lei": entity_lei}


def parse_entity_name(source: str | BinaryIO) -> str | None:
    """Nombre legal declarado (ifrs-full:NameOfReportingEntity...) con cadena
    de continuaciones; None si el documento no lo declara."""
    tree = etree.parse(source, etree.XMLParser(huge_tree=True))
    root = tree.getroot()
    continuations = {
        e.get("id"): e for e in root.iter(_IX + "continuation") if e.get("id")
    }
    for elem in root.iter(_IX + "nonNumeric"):
        if (elem.get("name") or "").strip() == (
            "ifrs-full:NameOfReportingEntityOrOtherMeansOfIdentification"
        ):
            name = _collect_continuations(elem, continuations).strip()
            return " ".join(name.split()) or None
    return None
