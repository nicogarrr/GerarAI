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

from typing import Any

from app.services import xbrl_extension_map as xm

SEC_CAPEX_METRIC = "capital_expenditure"
INVESTING_TOTALS = (
    "NetCashProvidedByUsedInInvestingActivities",
    "NetCashProvidedByUsedInInvestingActivitiesContinuingOperations",
    "CashFlowsFromUsedInInvestingActivities",
)
ASSET_MANAGER_METRICS = ("fee_related_earnings", "distributable_earnings")
_ASSET_MANAGER_WORDS = ("asset management", "capital markets", "private equity", "alternative asset")


def is_asset_manager(company: Any) -> bool:
    """Gestora de activos por la industria o el sector de la ficha; sin red.

    Ser «holding» no basta: un conglomerado (Berkshire) no publica FRE ni DE y
    cada refresh pagaría la descarga de su filing para nada."""
    text = " ".join(str(getattr(company, a, None) or "") for a in ("industry", "sector")).lower()
    return any(word in text for word in _ASSET_MANAGER_WORDS)


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
                   report_end: str) -> list[str]:
    """Métricas objetivo que el último ejercicio NO tiene con un concepto estándar."""
    wanted: list[str] = []
    concepts = {metric: list(c) for metric, c, _unit in metric_map}
    # Capex: solo si el emisor SÍ etiqueta su estado de flujos (total de inversión
    # en el último ejercicio) pero ningún concepto estándar de capex: es la huella
    # de un capex con concepto propio (CNQ). Sin estado de flujos no hay nada que leer.
    if _has_annual(taxonomy, list(INVESTING_TOTALS), report_end) and not _has_annual(
            taxonomy, concepts.get(SEC_CAPEX_METRIC, []), report_end):
        wanted.append(SEC_CAPEX_METRIC)
    if is_asset_manager(company):
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
    wanted = wanted_metrics(company, taxonomy, metric_map, str(filing["report"]))
    if not wanted:
        return None
    if cached and (cached.get("filing") or {}).get("accn") == filing["accn"] and set(wanted) <= set(
            cached.get("metrics") or {}):
        return {**cached, "reused": True}
    from app.services.connectors.sec import SECClient

    stem = _stem(str(filing["primary"]))
    urls = {kind: SECClient.filing_document_url(cik, filing["accn"], f"{stem}{suffix}")
            # Linkbases primero: si faltan no se descarga la instancia (la pieza grande).
            for kind, suffix in (("lab", "_lab.xml"), ("cal", "_cal.xml"), ("instance", "_htm.xml"))}
    docs: dict[str, bytes] = {}
    try:
        for kind, url in urls.items():
            body, _ctype = await sec.filing_document(url)
            docs[kind] = body
    except Exception as exc:  # noqa: BLE001 - sin documentos: N/D con motivo, companyfacts sigue igual
        missing = next(k for k in urls if k not in docs)
        motivo = f"no se pudo leer {missing} del filing {filing['accn']} ({type(exc).__name__})"
        return {"filing": filing, "urls": urls,
                "metrics": {m: xm.NotAvailable(m, motivo).as_dict() for m in wanted}}
    tax = xm.build_taxonomy(lab=docs["lab"], cal=docs["cal"])
    resolved = xm.resolve_extensions(tax, xm.parse_instance_facts(docs["instance"]), metrics=wanted)
    return {"filing": filing, "urls": urls, "metrics": {m: r.as_dict() for m, r in resolved.items()}}
