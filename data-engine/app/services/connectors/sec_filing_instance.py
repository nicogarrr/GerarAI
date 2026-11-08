"""Plan B de la SEC: hechos del propio filing (instancia XBRL) cuando companyfacts aún no lo trae.

Caso real (auditoría de valor intrínseco, 8-nov-2026): el 20-F de TSMC del ejercicio 2025 (presentado el
16-abr-2026, accession 0001628280-26-025362) está en EDGAR con su XBRL en línea, pero la API companyfacts no
tiene ni un hecho IFRS suyo. La app valoraba TSM con 2024 y mezclaba el balance de 2025 de un agregador.

Fuente: el XBRL ya extraído que EDGAR publica junto a cada filing en línea (``<documento>_htm.xml``), la
misma presentación oficial que alimenta companyfacts. Se leen solo hechos sin dimensiones de las taxonomías
estándar (us-gaap, ifrs-full, dei), en el mismo formato que companyfacts, para que pasen por las mismas reglas
de ingesta (anclas por accession, duraciones, alcance). Las extensiones del emisor no se leen.
"""
from __future__ import annotations

from typing import Any

from lxml import etree

XBRLI = "http://www.xbrl.org/2003/instance"
_TAXONOMIES = (("fasb.org/us-gaap", "us-gaap"), ("xbrl.ifrs.org", "ifrs-full"), ("xbrl.sec.gov/dei", "dei"))


def taxonomy_of(namespace: str | None) -> str | None:
    ns = namespace or ""
    for marker, key in _TAXONOMIES:
        if marker in ns:
            return key
    return None


def _measure(text: str | None) -> str:
    local = (text or "").strip().split(":")[-1]
    return local.upper() if len(local) == 3 and local.isalpha() else local


def _units(root: Any) -> dict[str, str]:
    """unitRef -> unidad de companyfacts («TWD», «shares», «TWD/shares», «pure»)."""
    out: dict[str, str] = {}
    for unit in root.iter(f"{{{XBRLI}}}unit"):
        uid = unit.get("id")
        divide = unit.find(f"{{{XBRLI}}}divide")
        if divide is not None:
            num = divide.find(f"{{{XBRLI}}}unitNumerator/{{{XBRLI}}}measure")
            den = divide.find(f"{{{XBRLI}}}unitDenominator/{{{XBRLI}}}measure")
            out[uid] = f"{_measure(num.text if num is not None else '')}/{_measure(den.text if den is not None else '')}"
        else:
            m = unit.find(f"{{{XBRLI}}}measure")
            out[uid] = _measure(m.text if m is not None else "")
    return out


def _contexts(root: Any) -> dict[str, tuple[str | None, str | None]]:
    """contextRef -> (inicio, fin) de los contextos SIN dimensiones."""
    out: dict[str, tuple[str | None, str | None]] = {}
    for ctx in root.iter(f"{{{XBRLI}}}context"):
        if ctx.find(f".//{{{XBRLI}}}segment") is not None or ctx.find(f"{{{XBRLI}}}scenario") is not None:
            continue
        period = ctx.find(f"{{{XBRLI}}}period")
        if period is None:
            continue
        instant = period.findtext(f"{{{XBRLI}}}instant")
        start = period.findtext(f"{{{XBRLI}}}startDate")
        end = period.findtext(f"{{{XBRLI}}}endDate") or instant
        out[ctx.get("id")] = (None if instant else start, end)
    return out


def parse_instance(xml: bytes, *, accn: str, form: str, filed: str, fiscal_year: int) -> dict[str, Any]:
    """Hechos del filing con la forma de companyfacts: {taxonomía: {concepto: {"units": {unidad: [...]}}}}."""
    root = etree.fromstring(xml, parser=etree.XMLParser(huge_tree=True, resolve_entities=False, no_network=True))
    units = _units(root)
    contexts = _contexts(root)
    facts: dict[str, dict[str, Any]] = {}
    seen: set[tuple] = set()
    for el in root:
        if not isinstance(el.tag, str) or el.get("contextRef") is None or el.get("unitRef") is None:
            continue
        qname = etree.QName(el)
        taxonomy = taxonomy_of(qname.namespace)
        period = contexts.get(el.get("contextRef"))
        unit = units.get(el.get("unitRef"))
        if taxonomy is None or period is None or not unit or el.get("{http://www.w3.org/2001/XMLSchema-instance}nil") == "true":
            continue
        try:
            value = float((el.text or "").strip())
        except ValueError:
            continue
        start, end = period
        key = (taxonomy, qname.localname, unit, start, end)
        if key in seen:
            continue
        seen.add(key)
        entry: dict[str, Any] = {"end": end, "val": int(value) if value.is_integer() else value, "accn": accn,
                                 "fy": fiscal_year, "fp": "FY", "form": form, "filed": filed,
                                 "_source": "filing_instance"}
        if start:
            entry["start"] = start
        (facts.setdefault(taxonomy, {}).setdefault(qname.localname, {"units": {}})["units"]
         .setdefault(unit, []).append(entry))
    return _single_reporting_currency(facts)


def _currency_of(unit: str) -> str | None:
    head = unit.split("/")[0]
    return head if len(head) == 3 and head.isupper() else None


def _single_reporting_currency(facts: dict[str, Any]) -> dict[str, Any]:
    """Solo la divisa de los estados: un 20-F puede traer además una traducción de conveniencia (TSM: TWD y
    algunas cifras en USD). Gana la divisa con más hechos; las unidades sin divisa (acciones) se quedan."""
    counts: dict[str, int] = {}
    for concepts in facts.values():
        for body in concepts.values():
            for unit, entries in body["units"].items():
                if (ccy := _currency_of(unit)) is not None:
                    counts[ccy] = counts.get(ccy, 0) + len(entries)
    if len(counts) <= 1:
        return facts
    main = max(counts, key=lambda c: counts[c])
    for concepts in facts.values():
        for body in concepts.values():
            body["units"] = {u: e for u, e in body["units"].items() if _currency_of(u) in (None, main)}
    return facts


def accessions_in(facts_data: dict[str, Any], *, financial_only: bool = True) -> set[str]:
    """Accessions con hechos en companyfacts. Con ``financial_only`` solo cuentan us-gaap/ifrs-full: TSM
    tiene su 20-F de 2025 en companyfacts solo con la portada (dei), sin un hecho financiero."""
    out: set[str] = set()
    for taxonomy, concepts in (facts_data.get("facts") or {}).items():
        if financial_only and taxonomy not in ("us-gaap", "ifrs-full"):
            continue
        for body in concepts.values():
            for entries in ((body or {}).get("units") or {}).values():
                for entry in entries:
                    if isinstance(entry, dict) and entry.get("accn"):
                        out.add(str(entry["accn"]))
    return out


def merge_into(facts_data: dict[str, Any], parsed: dict[str, Any]) -> int:
    """Añade al payload de companyfacts los hechos del filing que no tenga. Devuelve cuántos."""
    added = 0
    root = facts_data.setdefault("facts", {})
    for taxonomy, concepts in parsed.items():
        for concept, body in concepts.items():
            target = root.setdefault(taxonomy, {}).setdefault(concept, {"units": {}}).setdefault("units", {})
            for unit, entries in body["units"].items():
                bucket = target.setdefault(unit, [])
                have = {(e.get("accn"), e.get("start"), e.get("end")) for e in bucket if isinstance(e, dict)}
                for entry in entries:
                    if (entry["accn"], entry.get("start"), entry["end"]) not in have:
                        bucket.append(entry)
                        added += 1
    return added


def latest_annual_missing(submissions: dict[str, Any], present: set[str], forms: set[str]) -> dict[str, Any] | None:
    """El último filing anual con XBRL cuyo accession no está en companyfacts (o None)."""
    recent = ((submissions or {}).get("filings") or {}).get("recent") or {}
    cols = ("form", "accessionNumber", "filingDate", "reportDate", "primaryDocument", "isXBRL")
    rows = zip(*(recent.get(c) or [] for c in cols), strict=False)
    for form, accn, filed, report, primary, is_xbrl in rows:
        if form not in forms:
            continue
        if accn in present or not is_xbrl or not primary or not report:
            return None
        return {"form": form, "accn": accn, "filed": filed, "report": report, "primary": primary}
    return None


def instance_name(primary_document: str) -> str:
    stem = primary_document.rsplit("/", 1)[-1]
    stem = stem[: -len(".htm")] if stem.endswith(".htm") else stem.rsplit(".", 1)[0]
    return f"{stem}_htm.xml"
