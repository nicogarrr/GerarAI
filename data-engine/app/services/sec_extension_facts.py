"""Plan C de la SEC: métricas que el emisor etiqueta con conceptos PROPIOS (extensiones).

companyfacts solo publica las taxonomías estándar: la inversión de CNQ
(``cnq:CashFlowsFromUsedInPropertyPlantandEquipmentClassifiedAsInvestingActivities``)
o el FRE de KKR (``kkr:FeeRelatedIncomeLoss``) no llegan nunca por ahí. Este
módulo lee, del ÚLTIMO informe anual con XBRL, la instancia y los linkbases de
etiquetas y de cálculo que EDGAR publica junto al filing, resuelve las
extensiones con las reglas generales de ``xbrl_extension_map`` y las añade al
payload de companyfacts con la misma forma (accession, form, filed, fy/fp), de
modo que pasan por las mismas reglas de ingesta (anclas por accession,
duración anual, divisa de reporte).

Coste de red acotado: solo se consulta si falta una métrica objetivo (capex
sin hecho estándar en el último ejercicio, o FRE/DE en una gestora u
holding), una vez por accession (la resolución queda en el documento fuente y
se reutiliza sin red mientras el último anual sea el mismo). Un fallo aquí
nunca rompe la ingesta de companyfacts: devuelve N/D con el motivo.
"""

from __future__ import annotations

import re
from typing import Any

from app.services import xbrl_extension_map as xm

SEC_CAPEX_METRIC = "capital_expenditure"
INVESTING_TOTALS = (
    "NetCashProvidedByUsedInInvestingActivities",
    "NetCashProvidedByUsedInInvestingActivitiesContinuingOperations",
    "CashFlowsFromUsedInInvestingActivities",
)
ASSET_MANAGER_METRICS = ("fee_related_earnings", "distributable_earnings")
_ASSET_MANAGER_WORDS = ("asset management", "capital markets", "private equity", "alternative asset",
                        "investment advice")
#: SIC de EDGAR de las gestoras (6282 «Investment Advice»: KKR, BX, APO, ARES, BAM…). La industria de la
#: ficha puede venir de un agregador con una etiqueta genérica («Financial Services» en KKR) y entonces
#: las palabras no bastan: el FRE etiquetado en su 10-K nunca se pedía.
ASSET_MANAGER_SIC = frozenset({6282})


def _sic(value: Any) -> int | None:
    try:
        return int(str(value).strip()) if value not in (None, "") else None
    except ValueError:
        return None


def is_asset_manager(company: Any, sic: Any = None) -> bool:
    """Gestora de activos por la industria o el sector de la ficha, o por el SIC (el de EDGAR si se pasa,
    si no la etiqueta ``sic:nnnn`` de la ficha); sin red.

    Ser «holding» no basta: un conglomerado (Berkshire) no publica FRE ni DE y
    cada refresh pagaría la descarga de su filing para nada."""
    text = " ".join(str(getattr(company, a, None) or "") for a in ("industry", "sector")).lower()
    if any(word in text for word in _ASSET_MANAGER_WORDS):
        return True
    code = _sic(sic)
    if code is None:
        from app.services.sic_classification import company_sic

        code = company_sic(company)
    return code in ASSET_MANAGER_SIC


#: Versión del resolvedor guardada con cada resolución: una resolución de una versión anterior se rehace una vez
#: (2: tablas HTML del informe anual para FRE/DE totales sin XBRL).
RESOLVER_VERSION = 2
#: Prefijo sintético del concepto de una cifra leída de una tabla HTML (no es una taxonomía).
HTML_TABLE_PREFIX = "html-table"

#: Piezas del filing que lee el plan C (linkbases primero: si faltan no se descarga la instancia, la pieza grande).
_DOC_SUFFIXES = (("lab", "_lab.xml"), ("cal", "_cal.xml"), ("instance", "_htm.xml"))


def _fetch_failed(cached: dict[str, Any]) -> bool:
    """La resolución guardada fue un fallo de descarga (no una ausencia real): no se reutiliza."""
    if cached.get("fetch_error"):
        return True
    return any(str((m or {}).get("motivo") or "").startswith("no se pudo leer")
               for m in (cached.get("metrics") or {}).values())


async def _fetch_documents(sec: Any, urls: dict[str, str], docs: dict[str, bytes]) -> tuple[str, Exception] | None:
    """Descarga en orden las piezas que faltan en ``docs``; la misma URL se lee una vez. (pieza, error) o None."""
    for kind, url in urls.items():
        if kind in docs:
            continue
        same = next((k for k, u in urls.items() if u == url and k in docs), None)
        if same is not None:
            docs[kind] = docs[same]
            continue
        try:
            body, _ctype = await sec.filing_document(url)
        except Exception as exc:  # noqa: BLE001 - el llamante decide (índice o N/D con motivo)
            return kind, exc
        docs[kind] = body
    return None


def _index_entries(index: bytes | str) -> list[tuple[str, int | None]]:
    """(nombre, bytes) de cada fichero del índice ``index.json`` de un filing."""
    import json

    try:
        payload = json.loads(index)
    except (TypeError, ValueError):
        return []
    items = ((payload or {}).get("directory") or {}).get("item") or []
    out: list[tuple[str, int | None]] = []
    for i in items:
        if isinstance(i, dict) and i.get("name"):
            raw = str(i.get("size") or "").strip()
            size = int(raw) if raw.isdigit() else None
            out.append((str(i["name"]), size))
    return out


def _index_items(index: bytes | str) -> list[str]:
    return [name for name, _size in _index_entries(index)]


#: Tope de bytes de un documento HTML del filing que se lee buscando la tabla (BN 40-F 2025: 6,5 MB).
HTML_DOC_MAX_BYTES = 20_000_000
#: Como mucho estos documentos HTML por filing (sin bucles: cada uno una vez).
HTML_DOC_MAX = 3
_NOT_REPORT_HTML = re.compile(r"^R\d+\.htm$|-index(-headers)?\.html?$|cert|consent", re.I)
#: Anexos numerados: solo los 13 (informe anual a los accionistas) y 99 (otros, p. ej. el informe anual de un 40-F)
#: pueden traer las tablas; contratos (10), valores (4), filiales (21), consentimientos (23)… no.
_EXHIBIT = re.compile(r"ex[-_]?(\d{1,3})", re.I)


def html_report_documents(entries: list[tuple[str, int | None]], primary: str) -> list[str]:
    """Documentos HTML del filing donde puede estar la tabla: el principal primero, luego el resto por tamaño.

    Fuera las páginas R*.htm del visor, los índices, certificaciones y consentimientos, y lo que pase del tope."""
    def exhibit_ok(name: str) -> bool:
        m = _EXHIBIT.search(name)
        return m is None or m.group(1)[:2] in ("13", "99")

    docs = [(n, s) for n, s in entries if n.lower().endswith((".htm", ".html")) and not _NOT_REPORT_HTML.search(n)
            and exhibit_ok(n) and (s is None or s <= HTML_DOC_MAX_BYTES)]
    docs.sort(key=lambda ns: (ns[0] != primary, -(ns[1] or 0)))
    return [n for n, _s in docs[:HTML_DOC_MAX]]


def _reporting_unit(taxonomy: dict[str, Any]) -> str | None:
    """Divisa más frecuente entre los hechos monetarios del payload (la de reporte del emisor)."""
    counts: dict[str, int] = {}
    for fact in taxonomy.values():
        for unit, entries in ((fact or {}).get("units") or {}).items():
            if len(unit) == 3 and unit.isalpha() and unit.isupper():
                counts[unit] = counts.get(unit, 0) + len(entries or [])
    return max(counts, key=lambda u: counts[u]) if counts else None


def filing_file_names(items: list[str], stem: str) -> dict[str, str]:
    """Nombres reales de etiquetas, cálculo e instancia según el índice del filing (puro).

    Preferencia: ``<stem>_lab.xml`` → cualquier ``*_lab.xml`` → el esquema ``.xsd`` (linkbases embebidos, como
    en los filings de Donnelley: BX 10-K 2025 solo publica ``bx-20251231.xsd`` y ``d48618d10k_htm.xml``). Igual
    para el cálculo. La instancia: ``<stem>_htm.xml`` → la única ``*_htm.xml``. Una pieza sin candidato no sale."""
    names = set(items)
    xsd = sorted(n for n in names if n.endswith(".xsd"))
    out: dict[str, str] = {}
    for kind, suffix in (("lab", "_lab.xml"), ("cal", "_cal.xml")):
        own = f"{stem}{suffix}"
        others = sorted(n for n in names if n.endswith(suffix))
        pick = own if own in names else (others[0] if len(others) == 1 else (xsd[0] if len(xsd) == 1 else None))
        if pick:
            out[kind] = pick
    inst = f"{stem}_htm.xml"
    instances = sorted(n for n in names if n.endswith("_htm.xml"))
    if inst in names:
        out["instance"] = inst
    elif len(instances) == 1:
        out["instance"] = instances[0]
    return out


def latest_annual_filing(submissions: dict[str, Any], forms: set[str]) -> dict[str, Any] | None:
    recent = ((submissions or {}).get("filings") or {}).get("recent") or {}
    cols = ("form", "accessionNumber", "filingDate", "reportDate", "primaryDocument", "isXBRL")
    for form, accn, filed, report, primary, is_xbrl in zip(*(recent.get(c) or [] for c in cols), strict=False):
        if form in forms:
            if not is_xbrl or not primary or not report:
                return None
            return {"form": form, "accn": accn, "filed": filed, "report": report, "primary": primary}
    return None


def _stem(primary_document: str) -> str:
    name = primary_document.rsplit("/", 1)[-1]
    return name[: -len(".htm")] if name.endswith(".htm") else name.rsplit(".", 1)[0]


def _has_annual(taxonomy: dict[str, Any], concepts: list[str], report_end: str) -> bool:
    for concept in concepts:
        for entries in ((taxonomy.get(concept) or {}).get("units") or {}).values():
            if any(isinstance(e, dict) and e.get("fp") == "FY" and str(e.get("end")) == report_end for e in entries):
                return True
    return False


def wanted_metrics(company: Any, taxonomy: dict[str, Any], metric_map: list[tuple[str, list[str], str]],
                   report_end: str, sic: Any = None) -> list[str]:
    """Métricas objetivo que el último ejercicio NO tiene con un concepto estándar."""
    wanted: list[str] = []
    concepts = {metric: list(c) for metric, c, _unit in metric_map}
    # Capex: solo si el emisor SÍ etiqueta su estado de flujos (total de inversión
    # en el último ejercicio) pero ningún concepto estándar de capex: es la huella
    # de un capex con concepto propio (CNQ). Sin estado de flujos no hay nada que leer.
    if _has_annual(taxonomy, list(INVESTING_TOTALS), report_end) and not _has_annual(
            taxonomy, concepts.get(SEC_CAPEX_METRIC, []), report_end):
        wanted.append(SEC_CAPEX_METRIC)
    if is_asset_manager(company, sic):
        wanted.extend(m for m in ASSET_MANAGER_METRICS if not _has_annual(taxonomy, concepts.get(m, []), report_end))
    return wanted


def companyfacts_entries(mapping: dict[str, Any], filing: dict[str, Any]) -> list[dict[str, Any]]:
    fiscal_year = int(str(filing["report"])[:4])
    out: list[dict[str, Any]] = []
    for row in mapping.get("values") or []:
        val = float(row["val"])
        entry: dict[str, Any] = {"end": row["end"], "val": int(val) if val.is_integer() else val,
                                 "accn": filing["accn"], "fy": fiscal_year, "fp": "FY", "form": filing["form"],
                                 "filed": filing["filed"], "_source": "filing_extension"}
        if row.get("start"):
            entry["start"] = row["start"]
        out.append(entry)
    return out


def apply_resolution(
    facts_data: dict[str, Any],
    taxonomy_key: str,
    metric_map: list[tuple[str, list[str], str]],
    provenance: dict[str, Any],
) -> list[tuple[str, list[str], str]]:
    """Inyecta en el payload los hechos resueltos y devuelve el mapa de métricas ampliado.

    El concepto de extensión va AL FINAL de la lista de su métrica: un concepto
    estándar del mismo periodo siempre gana."""
    filing = provenance["filing"]
    tax = facts_data.setdefault("facts", {}).setdefault(taxonomy_key, {})
    extra: dict[str, str] = {}
    for metric, mapping in (provenance.get("metrics") or {}).items():
        if mapping.get("status") == "N/D" or not mapping.get("concept"):
            continue
        concept, unit = str(mapping["concept"]), str(mapping.get("unit") or "")
        entries = companyfacts_entries(mapping, filing)
        if not entries or not unit:
            continue
        bucket = tax.setdefault(concept, {"units": {}}).setdefault("units", {}).setdefault(unit, [])
        have = {(e.get("accn"), e.get("start"), e.get("end")) for e in bucket if isinstance(e, dict)}
        bucket.extend(e for e in entries if (e["accn"], e.get("start"), e["end"]) not in have)
        extra[metric] = concept
    if not extra:
        return metric_map
    out: list[tuple[str, list[str], str]] = []
    seen: set[str] = set()
    for metric, concepts, unit in metric_map:
        seen.add(metric)
        out.append((metric, [*concepts, extra[metric]] if metric in extra else list(concepts), unit))
    out.extend((metric, [concept], "USD") for metric, concept in extra.items() if metric not in seen)
    return out


async def resolve_latest_filing(
    sec: Any,
    cik: str,
    company: Any,
    facts_data: dict[str, Any],
    taxonomy_key: str,
    metric_map: list[tuple[str, list[str], str]],
    forms: set[str],
    *,
    cached: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Resolución de extensiones del último anual: ``{"filing", "metrics", "urls"}`` o None si no hacía falta.

    Con ``cached`` del mismo accession se reutiliza sin red."""
    submissions = getattr(sec, "_last_submissions_payload", None) or await sec.submissions(cik)
    filing = latest_annual_filing(submissions, forms)
    if filing is None:
        return None
    taxonomy = (facts_data.get("facts") or {}).get(taxonomy_key) or {}
    wanted = wanted_metrics(company, taxonomy, metric_map, str(filing["report"]), sic=(submissions or {}).get("sic"))
    if not wanted:
        return None
    if cached and (cached.get("filing") or {}).get("accn") == filing["accn"] and set(wanted) <= set(
            cached.get("metrics") or {}) and not _fetch_failed(cached) and cached.get("resolver") == RESOLVER_VERSION:
        return {**cached, "reused": True}
    from app.services.connectors.sec import SECClient

    stem = _stem(str(filing["primary"]))
    names = {kind: f"{stem}{suffix}" for kind, suffix in _DOC_SUFFIXES}
    urls = {kind: SECClient.filing_document_url(cik, filing["accn"], name) for kind, name in names.items()}
    docs: dict[str, bytes] = {}
    index_entries: list[tuple[str, int | None]] | None = None
    failure = await _fetch_documents(sec, urls, docs)
    if failure is not None:
        # Los nombres <stem>_lab.xml/_cal.xml son la convención de unos agentes de presentación; otros
        # (BX 10-K 2025, d48618d10k.htm) nombran los linkbases por el esquema o los EMBEBEN en el .xsd.
        # Una lectura del índice del filing da los nombres reales; sin bucles: un solo reintento por pieza.
        try:
            index, _ctype = await sec.filing_document(SECClient.filing_document_url(cik, filing["accn"], "index.json"))
            index_entries = _index_entries(index)
            listed = filing_file_names([n for n, _s in index_entries], stem)
        except Exception:  # noqa: BLE001 - sin índice: N/D con el motivo de la primera pieza
            listed = {}
        retry = {k: SECClient.filing_document_url(cik, filing["accn"], n) for k, n in listed.items()
                 if k not in docs and n != names[k]}
        if retry:
            urls = {**urls, **retry}
            failure = await _fetch_documents(sec, urls, docs)
    if failure is not None:
        missing, exc = failure
        motivo = f"no se pudo leer {missing} del filing {filing['accn']} ({type(exc).__name__})"
        return {"filing": filing, "urls": urls, "fetch_error": missing, "resolver": RESOLVER_VERSION,
                "metrics": {m: xm.NotAvailable(m, motivo).as_dict() for m in wanted}}
    tax = xm.build_taxonomy(lab=docs["lab"], cal=docs["cal"])
    resolved = xm.resolve_extensions(tax, xm.parse_instance_facts(docs["instance"]), metrics=wanted)
    metrics = {m: r.as_dict() for m, r in resolved.items()}
    pending = [m for m in wanted if m in ASSET_MANAGER_METRICS and (metrics.get(m) or {}).get("status") == "N/D"]
    if pending:
        metrics = await _from_report_tables(sec, cik, filing, taxonomy, metrics, pending, index_entries)
    return {"filing": filing, "urls": urls, "resolver": RESOLVER_VERSION, "metrics": metrics}


async def _from_report_tables(
    sec: Any, cik: str, filing: dict[str, Any], taxonomy: dict[str, Any], metrics: dict[str, Any],
    pending: list[str], index_entries: list[tuple[str, int | None]] | None,
) -> dict[str, Any]:
    """FRE/DE totales que el XBRL no etiqueta: fila de una tabla anual del HTML del MISMO informe anual.

    BN (40-F 2025) solo etiqueta el DE por segmento; el total («Distributable earnings 6,008») está en las
    tablas del informe anual que acompaña al 40-F. Lector determinista (``filing_html_tables``); sin fila,
    sin escala o con tablas que no casan, la N/D se queda con su motivo ampliado."""
    from app.services import filing_html_tables as ft
    from app.services.connectors.sec import SECClient

    out = dict(metrics)
    unit = _reporting_unit(taxonomy)
    if unit is None:
        return out
    try:
        if index_entries is None:
            index, _ctype = await sec.filing_document(SECClient.filing_document_url(cik, filing["accn"], "index.json"))
            index_entries = _index_entries(index)
    except Exception as exc:  # noqa: BLE001 - sin índice: las N/D se quedan
        for m in pending:
            out[m] = {**out[m], "motivo": f"{out[m].get('motivo')}; índice del filing no legible ({type(exc).__name__})"}
        return out
    left = list(pending)
    read: list[str] = []
    for name in html_report_documents(index_entries, str(filing.get("primary") or "")):
        if not left:
            break
        url = SECClient.filing_document_url(cik, filing["accn"], name)
        try:
            body, _ctype = await sec.filing_document(url)
        except Exception:  # noqa: BLE001 - un documento ilegible no rompe la ingesta
            continue
        read.append(name)
        found = ft.resolve(body, left, source=name)
        for m, f in found.items():
            if f.conflict:
                out[m] = xm.NotAvailable(m, f"tablas del informe anual que no casan: {f.conflict}").as_dict()
            elif f.values:
                out[m] = {"metric": m, "concept": f"{HTML_TABLE_PREFIX}:{m}", "label": m, "rule": "tabla_html",
                          "evidence": f"{name}: " + "; ".join(f.evidence), "sign": 1, "unit": unit, "segment": None,
                          "source_url": url,
                          "values": [{"start": s, "end": e, "val": str(v)} for (s, e), v in sorted(f.values.items(),
                                                                                                  key=lambda kv: kv[0][1])]}
            left.remove(m)
    for m in left:
        out[m] = {**out[m], "motivo": f"{out[m].get('motivo')}; sin fila anual del total en las tablas HTML del "
                                      f"informe ({', '.join(read) or 'ningún documento HTML candidato bajo el tope'})"}
    return out
