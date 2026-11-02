"""10-K/10-Q -> facts FinancialFact-compatibles via edgartools.

Dos entradas, una sola fusion (las reglas son las de la via actual, con sus
tablas importadas, no copiadas):

- Snapshot/offline (produccion OCI): ``companyfacts`` oficial
  (``facts.us-gaap``) tal como lo sirve la SEC y tal como lo consume
  edgartools. ``entries_from_companyfacts`` replica ``_collect_by_concept``:
  por concepto y periodo gana el ``filed`` mas reciente; el flujo exige
  duracion real (FY 300-380 d, Q 70-110 d); el balance (sin ``start``) pasa;
  con anclas anuales el hecho solo entra anclado a su 10-K (fail closed).
- Live (dev): ``EntityFacts.get_all_facts()`` de edgartools (verificado en
  5.59.1: ``FinancialFact`` con concept/value/unit/period_start/period_end/
  fiscal_year/fiscal_period/filing_date/form_type/accession). Duck-typed para
  tests hermeticos.

``merge_entries`` replica ``_merge_for_metric``: alias colapsados por ``filed``,
partes disjuntas sumadas (``is_summed_component``), alcance
(``SCOPE_PRIORITY_METRICS``). El revenue bancario compone
``InterestIncomeExpenseNet+NoninterestIncome`` fail-closed como
``_compose_bank_revenue``.

Cada fact dict lleva las claves de ``FinancialFact`` (value Decimal, unit,
period, fiscal_year, fiscal_quarter, source_type="SEC", is_reported,
confidence) mas ``_concept`` (proveniencia por periodo, que el servicio mueve
a ``document.metadata_["xbrl_concept_by_metric_period"]`` como la via actual;
``FinancialFact`` no tiene columna libre).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from app.services.connectors.edgartools_concepts import (
    bank_revenue_components,
    bank_revenue_concept_label,
    concept_to_metric,
    revenue_concepts_for,
    xbrl_unit_key,
)
from app.services.financial_ingestion_service import (
    SCOPE_PRIORITY_METRICS,
    SEC_METRIC_MAP,
    is_summed_component,
)
from app.services.number_parsing import parse_machine_decimal as _decimal

ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}
QUARTERLY_FORMS = {"10-Q"}
QUARTERLY_PERIODS = {"Q1", "Q2", "Q3", "Q4"}

ANNUAL_MIN_SPAN = 300
ANNUAL_MAX_SPAN = 380
QUARTERLY_MIN_SPAN = 70
QUARTERLY_MAX_SPAN = 110
ANNUAL_CAP = 20
QUARTERLY_CAP = 12


def _normalized_month(end: str) -> str | None:
    """Mes fiscal normalizado (primeros 7 dias = mes anterior, drift 52/53 sem).

    Misma regla que ``_normalized_fiscal_month`` de la via actual.
    """
    try:
        parsed = date.fromisoformat(end[:10])
    except ValueError:
        return None
    year, month = parsed.year, parsed.month
    if parsed.day <= 7:
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    return f"{month:02d}"


def _span_days(start: str | None, end: str | None) -> int | None:
    if not start or not end:
        return None
    try:
        return (date.fromisoformat(str(end)[:10]) - date.fromisoformat(str(start)[:10])).days
    except ValueError:
        return None


def entries_from_companyfacts(
    us_gaap: dict[str, Any],
    concepts: list[str],
    unit_key: str,
    *,
    forms: set[str],
    periods: set[str],
    min_span: int | None,
    max_span: int | None,
    annual_anchors: dict[str, str] | None = None,
) -> dict[str, dict[str, dict[str, Any]]]:
    """``{concept: {end: entry}}`` (gana el ``filed`` mas reciente por celda).

    Replica ``_collect_by_concept``: filtro por form/fp, duracion real para
    flujo con ``start``, instantaneos sin filtro de duracion, y ancla anual
    fail-closed cuando ``annual_anchors is not None`` (sin ancla linkable el
    hecho anual no entra; ``{}`` = cero hechos anuales, como la via actual).
    """
    by_concept: dict[str, dict[str, dict[str, Any]]] = {}
    for concept in concepts:
        entries = us_gaap.get(concept, {}).get("units", {}).get(unit_key, [])
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if entry.get("form") not in forms or entry.get("fp") not in periods:
                continue
            if annual_anchors is not None:
                accn = str(entry.get("accn") or "")
                report_date = annual_anchors.get(accn)
                if not report_date:
                    continue
                entry_month = _normalized_month(str(entry.get("end") or ""))
                if entry_month is None or entry_month != _normalized_month(report_date):
                    continue
            start = entry.get("start")
            if start and min_span is not None and max_span is not None:
                span = _span_days(str(start), str(entry.get("end") or ""))
                if span is None or not min_span <= span <= max_span:
                    continue
            end = str(entry.get("end") or "")
            if not end:
                continue
            bucket = by_concept.setdefault(concept, {})
            current = bucket.get(end)
            if current is None or str(entry.get("filed") or "") > str(current.get("filed") or ""):
                bucket[end] = {**entry, "_concept": concept}
    return by_concept


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def entries_from_edgartools_facts(entity_facts: Any, concepts: list[str]) -> dict[str, dict[str, dict[str, Any]]]:
    """Normaliza ``EntityFacts.get_all_facts()`` (o una lista) a entries.

    Solo entran conceptos del mapa canonico (via ``concept_to_metric``) y
    unidades coherentes con la metrica (clave XBRL o canonica; sin unidad en
    el hecho se acepta, documentado para stubs). La particion anual /
    trimestral la hace el llamador por ``fp``/``form`` igual que en snapshots.
    """
    wanted = set(concepts)
    get_all = getattr(entity_facts, "get_all_facts", None)
    facts: Any = get_all() if callable(get_all) else entity_facts
    by_concept: dict[str, dict[str, dict[str, Any]]] = {}
    for fact in facts or []:
        concept = getattr(fact, "concept", None) or (fact.get("concept") if isinstance(fact, dict) else None)
        if not concept or str(concept) not in wanted or concept_to_metric(str(concept)) is None:
            continue
        concept = str(concept)
        if isinstance(fact, dict):
            end = _iso(fact.get("period_end"))
            start = _iso(fact.get("period_start"))
            val = fact.get("numeric_value", fact.get("value"))
            filed = _iso(fact.get("filing_date"))
            form = fact.get("form_type")
            fp = fact.get("fiscal_period")
            accn = _iso(fact.get("accession"))
            unit = fact.get("unit")
        else:
            end = _iso(getattr(fact, "period_end", None))
            start = _iso(getattr(fact, "period_start", None))
            val = getattr(fact, "numeric_value", None)
            if val is None:
                val = getattr(fact, "value", None)
            filed = _iso(getattr(fact, "filing_date", None))
            form = getattr(fact, "form_type", None)
            fp = getattr(fact, "fiscal_period", None)
            accn = _iso(getattr(fact, "accession", None))
            unit = getattr(fact, "unit", None)
        if not end or val is None:
            continue
        entry: dict[str, Any] = {
            "end": end,
            "filed": filed or "",
            "form": form,
            "fp": fp,
            "val": val,
            "_concept": concept,
        }
        if start:
            entry["start"] = start
        if accn:
            entry["accn"] = accn
        if unit:
            entry["_unit"] = unit
        bucket = by_concept.setdefault(concept, {})
        current = bucket.get(end)
        if current is None or str(entry["filed"]) > str(current.get("filed") or ""):
            bucket[end] = entry
    return by_concept


def _collapse_aliases(by_concept: dict[str, dict[str, dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    by_end: dict[str, dict[str, Any]] = {}
    for entries in by_concept.values():
        for entry in entries.values():
            end = str(entry.get("end") or "")
            current = by_end.get(end)
            if current is None or str(entry.get("filed") or "") > str(current.get("filed") or ""):
                by_end[end] = entry
    return by_end


def _collapse_by_scope(by_concept: dict[str, dict[str, dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    by_end: dict[str, dict[str, Any]] = {}
    for entries in by_concept.values():
        for end, entry in entries.items():
            by_end.setdefault(end, entry)
    return by_end


def _sum_disjoint(by_concept: dict[str, dict[str, dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    totals: dict[str, dict[str, Any]] = {}
    for concept, entries in by_concept.items():
        for end, entry in entries.items():
            value = _decimal(entry.get("val"))
            if value is None:
                continue
            bucket = totals.setdefault(
                end,
                {"val": Decimal("0"), "filed": "", "end": end, "_components": {}, "_latest": entry},
            )
            bucket["val"] = bucket["val"] + value
            bucket["_components"][concept] = str(value)
            filed = str(entry.get("filed") or "")
            if filed > str(bucket["filed"]):
                bucket["filed"] = filed
                bucket["_latest"] = entry
    for key, bucket in list(totals.items()):
        latest = bucket.pop("_latest")
        merged = {**latest, **bucket}
        if len(merged["_components"]) == 1:
            merged["_concept"] = next(iter(merged["_components"]))
        else:
            merged["_concept"] = "+".join(sorted(merged["_components"]))
        merged["val"] = float(merged["val"])
        totals[key] = merged
    return totals


def merge_entries(by_concept: dict[str, dict[str, dict[str, Any]]], metric: str) -> dict[str, dict[str, Any]]:
    """Fusion por periodo: replica ``_merge_for_metric`` (misma prioridad)."""
    if is_summed_component(metric):
        return _sum_disjoint(by_concept)
    if metric in SCOPE_PRIORITY_METRICS:
        return _collapse_by_scope(by_concept)
    return _collapse_aliases(by_concept)


def _compose_bank_revenue_entries(
    collected: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    """Suma fail-closed de ambas partes (replica ``_compose_bank_revenue``)."""
    parts = {concept: collected.get(concept, {}) for concept in bank_revenue_components()}
    interest = parts[bank_revenue_components()[0]]
    noninterest = parts[bank_revenue_components()[1]]
    composed: dict[str, dict[str, Any]] = {}
    for end, interest_entry in interest.items():
        other = noninterest.get(end)
        if other is None:
            continue
        left, right = _decimal(interest_entry.get("val")), _decimal(other.get("val"))
        if left is None or right is None:
            continue
        composed[end] = {**interest_entry, "val": float(left + right), "_concept": bank_revenue_concept_label()}
    return composed


def anchors_from_submissions(submissions: dict[str, Any], annual_forms: set[str] | None = None) -> dict[str, str]:
    """``{accn: reportDate}`` de filings anuales (ventana ``recent``).

    Simplificacion documentada de ``SECClient.annual_report_anchors`` (que
    fusiona ficheros historicos): el snapshot edgartools versiona la ventana
    util en ``submissions`` y la ingesta solo ancla lo declarado ahi.
    """
    allowed = annual_forms or ANNUAL_FORMS
    recent = (submissions.get("filings", {}) or {}).get("recent", {}) or {}
    accessions = recent.get("accessionNumber", []) or []
    anchors: dict[str, str] = {}
    for index, accession in enumerate(accessions):
        forms = recent.get("form", []) or []
        form = str(forms[index]) if index < len(forms) else ""
        if form not in allowed:
            continue
        dates = recent.get("reportDate", []) or []
        report_date = str(dates[index]) if index < len(dates) else ""
        if accession and report_date:
            anchors[str(accession)] = report_date
    return anchors


def _modal_month(ends: list[str]) -> str | None:
    """Mes modal de cierre sobre fines anuales (etiqueta trimestral).

    Simplificacion documentada de ``_modal_fiscal_end_month`` (que pondera
    flujos FY 300-380 d con ventana reciente): aqui la moda se computa sobre
    los fines anuales ya admitidos, que es la misma poblacion protegida.
    """
    counts: dict[str, int] = {}
    for end in ends:
        month = _normalized_month(end)
        if month:
            counts[month] = counts.get(month, 0) + 1
    if not counts:
        return None
    return max(counts, key=lambda m: (counts[m], m))


def quarter_label(end: str, modal_month: str | None, fallback_fp: str) -> str:
    """Etiqueta Qn por distancia al cierre (fallback: fp del hecho).

    Misma idea que ``_fiscal_quarter_from_end(...) or fp`` de la via actual:
    con mes modal se deriva (el fp de companyfacts es el de la presentacion,
    no el del dato); sin el, el fp declarado.
    """
    if modal_month:
        try:
            end_month = int(_normalized_month(end) or "0")
            close_month = int(modal_month)
            delta = (end_month - close_month) % 12
            if delta == 0:
                return "Q4"
            if delta in (3, 4, 5):
                return "Q1"
            if delta in (6, 7, 8):
                return "Q2"
            if delta in (9, 10, 11):
                return "Q3"
            # delta 1-2: fin imposible en trimestres sanos -> fallback honesto.
        except ValueError:
            pass
    return fallback_fp


def _collect_metric(
    us_gaap: dict[str, Any],
    concepts: list[str],
    unit_key: str,
    *,
    forms: set[str],
    periods: set[str],
    min_span: int | None,
    max_span: int | None,
    annual_anchors: dict[str, str] | None,
) -> dict[str, dict[str, dict[str, Any]]]:
    return entries_from_companyfacts(
        us_gaap, concepts, unit_key, forms=forms, periods=periods,
        min_span=min_span, max_span=max_span, annual_anchors=annual_anchors,
    )


def facts_from_companyfacts(
    companyfacts: dict[str, Any],
    *,
    bank_like: bool = False,
    annual_anchors: dict[str, str] | None = None,
    submissions: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Facts anuales + trimestrales desde companyfacts oficial.

    Devuelve ``(facts, concept_usage)``: facts con claves de ``FinancialFact``
    y concept_usage ``{metrica: {periodo: concepto}}`` para
    ``document.metadata_["xbrl_concept_by_metric_period"]`` (igual que la via
    actual). Si ``submissions`` viene sin ``annual_anchors``, las anclas se
    derivan de el; sin submissions y sin anclas, ``annual_anchors=None`` (sin
    chequeo de ancla, documentado para backfills).
    """
    us_gaap = (companyfacts.get("facts") or {}).get("us-gaap") or {}
    anchors = annual_anchors
    if anchors is None and submissions is not None:
        anchors = anchors_from_submissions(submissions)
    facts: list[dict[str, Any]] = []
    concept_usage: dict[str, dict[str, Any]] = {}

    annual_by_metric: dict[str, dict[str, dict[str, Any]]] = {}
    for metric, concepts, unit in SEC_METRIC_MAP:
        unit_key = xbrl_unit_key(metric)
        metric_concepts = revenue_concepts_for(concepts, bank_like) if metric == "revenue" else concepts
        by_end = merge_entries(
            _collect_metric(
                us_gaap, metric_concepts, unit_key, forms=ANNUAL_FORMS, periods={"FY"},
                min_span=ANNUAL_MIN_SPAN, max_span=ANNUAL_MAX_SPAN, annual_anchors=anchors,
            ),
            metric,
        )
        if metric == "revenue" and bank_like:
            for end, entry in _compose_bank_revenue_entries(
                _collect_metric(
                    us_gaap, list(bank_revenue_components()), unit_key, forms=ANNUAL_FORMS,
                    periods={"FY"}, min_span=ANNUAL_MIN_SPAN, max_span=ANNUAL_MAX_SPAN,
                    annual_anchors=anchors,
                )
            ).items():
                by_end.setdefault(end, entry)
        if by_end:
            annual_by_metric[metric] = dict(sorted(by_end.items(), key=lambda kv: str(kv[0]), reverse=True)[:ANNUAL_CAP])

    modal_month = _modal_month([end for by_end in annual_by_metric.values() for end in by_end])

    for metric, concepts, unit in SEC_METRIC_MAP:
        unit_key = xbrl_unit_key(metric)
        metric_concepts = revenue_concepts_for(concepts, bank_like) if metric == "revenue" else concepts
        by_end_q = merge_entries(
            _collect_metric(
                us_gaap, metric_concepts, unit_key, forms=QUARTERLY_FORMS, periods=QUARTERLY_PERIODS,
                min_span=QUARTERLY_MIN_SPAN, max_span=QUARTERLY_MAX_SPAN, annual_anchors=None,
            ),
            metric,
        )
        if metric == "revenue" and bank_like:
            for end, entry in _compose_bank_revenue_entries(
                _collect_metric(
                    us_gaap, list(bank_revenue_components()), unit_key, forms=QUARTERLY_FORMS,
                    periods=QUARTERLY_PERIODS, min_span=QUARTERLY_MIN_SPAN,
                    max_span=QUARTERLY_MAX_SPAN, annual_anchors=None,
                )
            ).items():
                by_end_q.setdefault(end, entry)
        for entry in sorted(by_end_q.values(), key=lambda e: str(e["end"]), reverse=True)[:QUARTERLY_CAP]:
            val = _decimal(entry.get("val"))
            if val is None:
                continue
            if metric == "capital_expenditure":
                val = -val
            fp = quarter_label(str(entry["end"]), modal_month, str(entry.get("fp") or ""))
            facts.append({
                "metric": metric, "value": val, "unit": unit,
                "period": f"{entry['end']}:{fp}", "fiscal_year": None, "fiscal_quarter": fp,
                "source_type": "SEC", "is_reported": True, "confidence": Decimal("0.9"),
                "_concept": entry.get("_concept"),
            })
            concept_usage.setdefault(metric, {})[f"{entry['end']}:{fp}"] = entry.get("_concept")

        for entry in sorted(
            (annual_by_metric.get(metric) or {}).values(), key=lambda e: str(e["end"]), reverse=True
        ):
            val = _decimal(entry.get("val"))
            if val is None:
                continue
            if metric == "capital_expenditure":
                val = -val
            facts.append({
                "metric": metric, "value": val, "unit": unit,
                "period": f"{entry['end']}:FY", "fiscal_year": int(str(entry["end"])[:4]),
                "fiscal_quarter": "FY", "source_type": "SEC", "is_reported": True,
                "confidence": Decimal("0.95"), "_concept": entry.get("_concept"),
            })
            concept_usage.setdefault(metric, {})[str(entry["end"])] = entry.get("_concept")
    return facts, concept_usage


def facts_from_edgartools_entity(
    entity_facts: Any,
    *,
    bank_like: bool = False,
    annual_anchors: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Facts desde ``EntityFacts`` live de edgartools (dev con red).

    Normaliza a entries y aplica la misma fusion/periodificacion que el
    snapshot: anual = ``fp == FY`` en formas anuales (300-380 d o instante),
    trimestral = ``fp Q1-Q4`` en 10-Q (70-110 d o instante). Con anclas, el
    anual exige ancla como en snapshots.
    """
    facts: list[dict[str, Any]] = []
    concept_usage: dict[str, dict[str, Any]] = {}
    annual_by_metric: dict[str, dict[str, dict[str, Any]]] = {}
    for metric, concepts, unit in SEC_METRIC_MAP:
        metric_concepts = revenue_concepts_for(concepts, bank_like) if metric == "revenue" else concepts
        collected = entries_from_edgartools_facts(entity_facts, metric_concepts)
        annual_raw = {
            concept: {
                end: entry for end, entry in entries.items()
                if str(entry.get("form") or "") in ANNUAL_FORMS
                and str(entry.get("fp") or "") == "FY"
                and (
                    not entry.get("start")
                    or (
                        (lambda s: s is not None and ANNUAL_MIN_SPAN <= s <= ANNUAL_MAX_SPAN)(
                            _span_days(entry.get("start"), entry.get("end"))
                        )
                    )
                )
            }
            for concept, entries in collected.items()
        }
        if annual_anchors is not None:
            annual_raw = {
                concept: {
                    end: entry for end, entry in entries.items()
                    if str(entry.get("accn") or "") in (annual_anchors or {})
                    and _normalized_month(str(entry.get("end") or ""))
                    == _normalized_month(annual_anchors[str(entry.get("accn") or "")])
                }
                for concept, entries in annual_raw.items()
            }
        by_end = merge_entries({c: e for c, e in annual_raw.items() if e}, metric)
        if metric == "revenue" and bank_like:
            bank_collected = entries_from_edgartools_facts(entity_facts, list(bank_revenue_components()))
            for end, entry in _compose_bank_revenue_entries(bank_collected).items():
                by_end.setdefault(end, entry)
        if by_end:
            annual_by_metric[metric] = dict(sorted(by_end.items(), key=lambda kv: str(kv[0]), reverse=True)[:ANNUAL_CAP])
    modal_month = _modal_month([end for by_end in annual_by_metric.values() for end in by_end])
    for metric, concepts, unit in SEC_METRIC_MAP:
        metric_concepts = revenue_concepts_for(concepts, bank_like) if metric == "revenue" else concepts
        collected = entries_from_edgartools_facts(entity_facts, metric_concepts)
        quarterly_raw = {
            concept: {
                end: entry for end, entry in entries.items()
                if str(entry.get("form") or "") in QUARTERLY_FORMS
                and str(entry.get("fp") or "") in QUARTERLY_PERIODS
                and (
                    not entry.get("start")
                    or (
                        (lambda s: s is not None and QUARTERLY_MIN_SPAN <= s <= QUARTERLY_MAX_SPAN)(
                            _span_days(entry.get("start"), entry.get("end"))
                        )
                    )
                )
            }
            for concept, entries in collected.items()
        }
        by_end_q = merge_entries({c: e for c, e in quarterly_raw.items() if e}, metric)
        for entry in sorted(by_end_q.values(), key=lambda e: str(e["end"]), reverse=True)[:QUARTERLY_CAP]:
            val = _decimal(entry.get("val"))
            if val is None:
                continue
            if metric == "capital_expenditure":
                val = -val
            fp = quarter_label(str(entry["end"]), modal_month, str(entry.get("fp") or ""))
            facts.append({
                "metric": metric, "value": val, "unit": unit,
                "period": f"{entry['end']}:{fp}", "fiscal_year": None, "fiscal_quarter": fp,
                "source_type": "SEC", "is_reported": True, "confidence": Decimal("0.9"),
                "_concept": entry.get("_concept"),
            })
            concept_usage.setdefault(metric, {})[f"{entry['end']}:{fp}"] = entry.get("_concept")
        for entry in sorted(
            (annual_by_metric.get(metric) or {}).values(), key=lambda e: str(e["end"]), reverse=True
        ):
            val = _decimal(entry.get("val"))
            if val is None:
                continue
            if metric == "capital_expenditure":
                val = -val
            facts.append({
                "metric": metric, "value": val, "unit": unit,
                "period": f"{entry['end']}:FY", "fiscal_year": int(str(entry["end"])[:4]),
                "fiscal_quarter": "FY", "source_type": "SEC", "is_reported": True,
                "confidence": Decimal("0.95"), "_concept": entry.get("_concept"),
            })
            concept_usage.setdefault(metric, {})[str(entry["end"])] = entry.get("_concept")
    return facts, concept_usage
