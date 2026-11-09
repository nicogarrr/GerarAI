"""Mapeo general de extensiones XBRL/ESEF a conceptos estándar.

Problema (nov-2026): la ingesta lee solo las taxonomías estándar (us-gaap,
ifrs-full). Lo que el emisor etiqueta con conceptos PROPIOS se perdía:

* gestoras alternativas: el FRE (*fee-related earnings*) y el DE
  (*distributable earnings*) no tienen concepto estándar; KKR los etiqueta como
  ``kkr:FeeRelatedIncomeLoss`` (segmento de gestión de activos) y Brookfield
  como ``bn:DistributableEarnings`` (por segmento);
* capex bajo un concepto propio: CNQ (40-F) declara la inversión en
  inmovilizado del estado de flujos como
  ``cnq:CashFlowsFromUsedInPropertyPlantandEquipmentClassifiedAsInvestingActivities``;
* deuda ESEF propia: Airbus declara ``airbus:LongtermFinancingLiabilities`` y
  ``airbus:ShorttermFinancingLiabilities`` en lugar de los totales IFRS.

Este módulo decide, SIN modelos y sin listas por emisor, qué concepto de
extensión equivale a cada métrica interna, con tres pruebas por orden de
fuerza, todas leídas de la propia taxonomía del filing:

1. ``ancla_esef``: el anclaje ESEF obligatorio (arcrole *wider-narrower* del
   linkbase de definición). Una extensión cuyos conceptos más estrechos son
   todos partes estándar de la métrica es esa métrica (Airbus: «Financing
   liabilities» ⊃ LongtermBorrowings + NoncurrentLeaseLiabilities).
2. ``calculo+etiqueta``: la relación de cálculo con el padre (la extensión
   suma en el total del estado que corresponde, p. ej. flujos de inversión) Y
   una etiqueta que nombra la magnitud.
3. ``etiqueta``: solo para KPIs sin concepto estándar (FRE, DE): la etiqueta
   estándar del emisor nombra la magnitud.

Cada resultado lleva el concepto, la etiqueta, la regla y la evidencia; si no
hay candidata, o hay varias que discrepan, o solo hay cifras por segmento sin
un total, la métrica queda N/D con su motivo. El signo se orienta al del
concepto estándar con el peso del cálculo (un capex declarado negativo con
peso +1 es la misma salida de caja que un «Purchase of PP&E» positivo con
peso −1). Nada se estima: cada valor es un hecho del filing.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from lxml import etree

XLINK = "{http://www.w3.org/1999/xlink}"
ANCHOR_ARCROLE_SUFFIX = "/wider-narrower"
STANDARD_PREFIXES = frozenset({"us-gaap", "ifrs-full", "dei", "srt", "esef_cor", "country", "currency"})
# Ejes que no cambian el alcance consolidado de un segmento: «partidas de
# consolidación = segmentos operativos» acompaña a cada cifra por segmento.
NEUTRAL_MEMBERS = frozenset({
    ("srt:ConsolidationItemsAxis", "us-gaap:OperatingSegmentsMember"),
})
SEGMENT_AXES = frozenset({"us-gaap:StatementBusinessSegmentsAxis", "ifrs-full:SegmentsAxis"})
LABEL_ROLE_PRIORITY = ("label", "terseLabel", "verboseLabel")

RULE_ANCHOR = "ancla_esef"
RULE_CALC = "calculo+etiqueta"
RULE_LABEL = "etiqueta"
_RULE_RANK = {RULE_ANCHOR: 0, RULE_CALC: 1, RULE_LABEL: 2}


# --------------------------------------------------------------------------
# Taxonomía de extensión (linkbases del filing)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CalcArc:
    parent: str
    weight: Decimal
    role: str


@dataclass
class ExtensionTaxonomy:
    """Etiquetas, cálculo y anclajes de la taxonomía del emisor, por QName ``prefijo:Local``."""

    labels: dict[str, str] = field(default_factory=dict)
    calc_parents: dict[str, list[CalcArc]] = field(default_factory=dict)
    wider: dict[str, set[str]] = field(default_factory=dict)
    narrower: dict[str, set[str]] = field(default_factory=dict)


def concept_from_href(href: str | None) -> str | None:
    """``kkr-20251231.xsd#kkr_FeeRelatedIncomeLoss`` -> ``kkr:FeeRelatedIncomeLoss``.

    El id del elemento en las taxonomías SEC/ESEF es ``prefijo_Local``; el
    prefijo puede llevar guiones (``ifrs-full``, ``us-gaap``) pero no ``_``."""
    if not href or "#" not in href:
        return None
    frag = href.rsplit("#", 1)[1]
    prefix, sep, local = frag.partition("_")
    if not sep or not prefix or not local:
        return None
    return f"{prefix}:{local}"


def _parse(xml: bytes) -> Any:
    parser = etree.XMLParser(huge_tree=True, resolve_entities=False, no_network=True)
    return etree.fromstring(xml, parser=parser)


def _links(root: Any, link_local: str) -> Iterable[Any]:
    for el in root.iter():
        if isinstance(el.tag, str) and etree.QName(el).localname == link_local:
            yield el


def _locators(link: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    for el in link:
        if isinstance(el.tag, str) and etree.QName(el).localname == "loc":
            concept = concept_from_href(el.get(XLINK + "href"))
            if concept:
                out[str(el.get(XLINK + "label"))] = concept
    return out


def parse_label_linkbase(xml: bytes, *, lang: str | None = None) -> dict[str, str]:
    """Etiqueta estándar (o, en su defecto, la breve o la detallada) de cada concepto."""
    root = _parse(xml)
    found: dict[str, dict[str, str]] = {}
    for link in _links(root, "labelLink"):
        locs = _locators(link)
        texts: dict[str, list[tuple[str, str]]] = {}
        for el in link:
            if isinstance(el.tag, str) and etree.QName(el).localname == "label":
                el_lang = el.get("{http://www.w3.org/XML/1998/namespace}lang")
                if lang and el_lang and not el_lang.lower().startswith(lang.lower()):
                    continue
                role = str(el.get(XLINK + "role") or "").rsplit("/", 1)[-1]
                text = " ".join((el.text or "").split())
                if text:
                    texts.setdefault(str(el.get(XLINK + "label")), []).append((role, text))
        for el in link:
            if isinstance(el.tag, str) and etree.QName(el).localname == "labelArc":
                concept = locs.get(str(el.get(XLINK + "from")))
                if concept is None:
                    continue
                for role, text in texts.get(str(el.get(XLINK + "to")), []):
                    found.setdefault(concept, {}).setdefault(role, text)
    out: dict[str, str] = {}
    for concept, by_role in found.items():
        for role in LABEL_ROLE_PRIORITY:
            if role in by_role:
                out[concept] = by_role[role]
                break
    return out


def parse_calculation_linkbase(xml: bytes) -> dict[str, list[CalcArc]]:
    root = _parse(xml)
    out: dict[str, list[CalcArc]] = {}
    for link in _links(root, "calculationLink"):
        role = str(link.get(XLINK + "role") or "").rsplit("/", 1)[-1]
        locs = _locators(link)
        for el in link:
            if not (isinstance(el.tag, str) and etree.QName(el).localname == "calculationArc"):
                continue
            parent, child = locs.get(str(el.get(XLINK + "from"))), locs.get(str(el.get(XLINK + "to")))
            try:
                weight = Decimal(str(el.get("weight")))
            except InvalidOperation:
                continue
            if parent and child:
                out.setdefault(child, []).append(CalcArc(parent=parent, weight=weight, role=role))
    return out


def parse_definition_anchors(xml: bytes) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Anclajes ESEF: (más amplios, más estrechos) de cada concepto."""
    root = _parse(xml)
    wider: dict[str, set[str]] = {}
    narrower: dict[str, set[str]] = {}
    for link in _links(root, "definitionLink"):
        locs = _locators(link)
        for el in link:
            if not (isinstance(el.tag, str) and etree.QName(el).localname == "definitionArc"):
                continue
            if not str(el.get(XLINK + "arcrole") or "").endswith(ANCHOR_ARCROLE_SUFFIX):
                continue
            wide, narrow = locs.get(str(el.get(XLINK + "from"))), locs.get(str(el.get(XLINK + "to")))
            if wide and narrow:
                narrower.setdefault(wide, set()).add(narrow)
                wider.setdefault(narrow, set()).add(wide)
    return wider, narrower


PACKAGE_MAX_MEMBER_BYTES = 64 * 1024 * 1024


def taxonomy_from_package(zip_bytes: bytes, *, lang: str = "en") -> ExtensionTaxonomy:
    """Taxonomía de extensión de un paquete ESEF (zip): ``*_lab*.xml``, ``*_cal.xml`` y ``*_def.xml``.

    Con varias etiquetas por idioma gana la del idioma pedido (``_lab-en.xml``)."""
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = [i for i in zf.infolist() if i.file_size <= PACKAGE_MAX_MEMBER_BYTES and "/META-INF/" not in i.filename]

        def pick(pattern: str) -> bytes | None:
            hits = sorted((i for i in names if re.search(pattern, i.filename.rsplit("/", 1)[-1])),
                          key=lambda i: (f"-{lang}." not in i.filename, i.filename))
            return zf.read(hits[0]) if hits else None

        return build_taxonomy(lab=pick(r"_lab(-[a-z]{2})?\.xml$"), cal=pick(r"_cal\.xml$"),
                              defn=pick(r"_def\.xml$"), lang=lang)


def build_taxonomy(
    *, lab: bytes | None = None, cal: bytes | None = None, defn: bytes | None = None, lang: str | None = "en"
) -> ExtensionTaxonomy:
    tax = ExtensionTaxonomy()
    if lab:
        tax.labels = parse_label_linkbase(lab, lang=lang)
    if cal:
        tax.calc_parents = parse_calculation_linkbase(cal)
    if defn:
        tax.wider, tax.narrower = parse_definition_anchors(defn)
    return tax


# --------------------------------------------------------------------------
# Hechos
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ExtFact:
    concept: str
    value: Decimal
    end: str
    start: str | None = None
    unit: str = ""
    members: tuple[tuple[str, str], ...] = ()


def is_extension(concept: str) -> bool:
    prefix = concept.split(":", 1)[0]
    return ":" in concept and prefix not in STANDARD_PREFIXES


def _monetary(unit: str) -> bool:
    head = unit.split(":")[-1].split("/")[0]
    return len(head) == 3 and head.isalpha() and head.isupper() and "/" not in unit


def parse_instance_facts(xml: bytes) -> list[ExtFact]:
    """Hechos numéricos de una instancia XBRL (``*_htm.xml`` de EDGAR) CON sus miembros."""
    root = _parse(xml)
    xbrli = "{http://www.xbrl.org/2003/instance}"
    units: dict[str, str] = {}
    for unit in root.findall(xbrli + "unit"):
        measures = [" ".join((m.text or "").split()) for m in unit.iter(xbrli + "measure")]
        units[str(unit.get("id"))] = "/".join(m.split(":")[-1] for m in measures)
    contexts: dict[str, tuple[str | None, str, tuple[tuple[str, str], ...]]] = {}
    for ctx in root.findall(xbrli + "context"):
        period = ctx.find(xbrli + "period")
        if period is None:
            continue
        instant = period.findtext(xbrli + "instant")
        start, end = period.findtext(xbrli + "startDate"), period.findtext(xbrli + "endDate")
        members = tuple(sorted(
            (str(m.get("dimension")), " ".join((m.text or "").split()))
            for m in ctx.iter("{http://xbrl.org/2006/xbrldi}explicitMember")
        ))
        if instant:
            contexts[str(ctx.get("id"))] = (None, instant.strip(), members)
        elif end:
            contexts[str(ctx.get("id"))] = ((start or "").strip() or None, end.strip(), members)
    out: list[ExtFact] = []
    for el in root:
        if not isinstance(el.tag, str) or el.get("contextRef") is None or el.get("unitRef") is None:
            continue
        if el.get("{http://www.w3.org/2001/XMLSchema-instance}nil") == "true":
            continue
        qn = etree.QName(el)
        prefix = el.prefix or (root.nsmap and next((p for p, ns in root.nsmap.items() if ns == qn.namespace), None))
        if not prefix:
            continue
        ctx = contexts.get(str(el.get("contextRef")))
        if ctx is None:
            continue
        try:
            value = Decimal((el.text or "").strip())
        except InvalidOperation:
            continue
        start, end, members = ctx
        out.append(ExtFact(concept=f"{prefix}:{qn.localname}", value=value, end=end, start=start,
                           unit=units.get(str(el.get("unitRef")), ""), members=members))
    return out


def facts_from_xbrl_json(facts: Mapping[str, Any]) -> list[ExtFact]:
    """Hechos de un snapshot ESEF normalizado (``normalize_xbrl_json``): solo alcance base (sin ejes)."""
    out: list[ExtFact] = []
    for concept, by_unit in facts.items():
        if not isinstance(by_unit, Mapping):
            continue
        for unit, entries in by_unit.items():
            for entry in entries or []:
                if entry.get("dims"):
                    continue
                try:
                    value = Decimal(str(entry.get("val")))
                except InvalidOperation:
                    continue
                end = entry.get("end") or entry.get("instant")
                if not end:
                    continue
                out.append(ExtFact(concept=concept, value=value, end=str(end),
                                   start=entry.get("start"), unit=str(unit)))
    return out


# --------------------------------------------------------------------------
# Reglas por métrica (generales: nombres de conceptos ESTÁNDAR y patrones de etiqueta)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class TargetRule:
    metric: str
    duration: bool
    # Partes estándar de la métrica: una extensión cuyos anclajes estrechos son
    # TODOS de este conjunto (y al menos uno de ``core``) es la métrica.
    parts: frozenset[str] = frozenset()
    core: frozenset[str] = frozenset()
    # Anclajes amplios admisibles (la extensión es una parte de este total).
    wider_ok: frozenset[str] = frozenset()
    # Totales del estado en los que debe sumar la extensión (regla de cálculo).
    calc_parents: frozenset[str] = frozenset()
    label: re.Pattern[str] | None = None
    label_exclude: re.Pattern[str] | None = None
    # Peso estándar del concepto en su total: el signo se orienta a él.
    standard_weight: Decimal = Decimal("1")
    # KPI sin concepto estándar: basta la etiqueta.
    label_only: bool = False
    note: str = ""


def _std(*names: str) -> frozenset[str]:
    return frozenset(names)


_CAPEX_PARTS = _std(
    "ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
    "ifrs-full:PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities",
    "ifrs-full:PurchaseOfPropertyPlantAndEquipmentIntangibleAssetsOtherThanGoodwillInvestmentPropertyAndOtherNoncurrentAssets",
    "ifrs-full:PurchaseOfInvestmentProperty",
    "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment",
    "us-gaap:PaymentsToAcquireProductiveAssets",
    "us-gaap:PaymentsToAcquireIntangibleAssets",
)
_CAPEX_CORE = _std(
    "ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
    "ifrs-full:PurchaseOfPropertyPlantAndEquipmentIntangibleAssetsOtherThanGoodwillInvestmentPropertyAndOtherNoncurrentAssets",
    "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment",
    "us-gaap:PaymentsToAcquireProductiveAssets",
)
_INVESTING_TOTALS = _std(
    "ifrs-full:CashFlowsFromUsedInInvestingActivities",
    "us-gaap:NetCashProvidedByUsedInInvestingActivities",
    "us-gaap:NetCashProvidedByUsedInInvestingActivitiesContinuingOperations",
)
_NONCURRENT_DEBT_PARTS = _std(
    "ifrs-full:LongtermBorrowings",
    "ifrs-full:NoncurrentPortionOfNoncurrentBorrowings",
    "ifrs-full:NoncurrentPortionOfNoncurrentBondsIssued",
    "ifrs-full:NoncurrentPortionOfNoncurrentLoansReceived",
    "ifrs-full:NoncurrentLeaseLiabilities",
)
_NONCURRENT_DEBT_CORE = _std(
    "ifrs-full:LongtermBorrowings",
    "ifrs-full:NoncurrentPortionOfNoncurrentBorrowings",
    "ifrs-full:NoncurrentPortionOfNoncurrentBondsIssued",
    "ifrs-full:NoncurrentPortionOfNoncurrentLoansReceived",
)
_CURRENT_DEBT_PARTS = _std(
    "ifrs-full:CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings",
    "ifrs-full:ShorttermBorrowings",
    "ifrs-full:CurrentPortionOfLongtermBorrowings",
    "ifrs-full:CurrentBondsIssuedAndCurrentPortionOfNoncurrentBondsIssued",
    "ifrs-full:CurrentLoansReceivedAndCurrentPortionOfNoncurrentLoansReceived",
    "ifrs-full:CurrentLeaseLiabilities",
)
_CURRENT_DEBT_CORE = _CURRENT_DEBT_PARTS - {"ifrs-full:CurrentLeaseLiabilities"}
_DEBT_LABEL = re.compile(r"\b(borrowings?|financing liabilit|financial debt|debt|loans?|bonds?|notes payable)\b", re.I)
_DEBT_EXCLUDE = re.compile(
    r"\b(lease liabilit\w*$|derivative|trade|provision|deferred|contract liabilit|pension|repayment|proceeds|"
    r"issuance|interest (paid|expense)|fair value|other than)\b", re.I)

TARGET_RULES: tuple[TargetRule, ...] = (
    TargetRule(
        metric="capital_expenditure",
        duration=True,
        parts=_CAPEX_PARTS,
        core=_CAPEX_CORE,
        wider_ok=_INVESTING_TOTALS | _std(
            "ifrs-full:PurchaseOfPropertyPlantAndEquipmentIntangibleAssetsOtherThanGoodwillInvestmentPropertyAndOtherNoncurrentAssets"),
        calc_parents=_INVESTING_TOTALS,
        label=re.compile(r"\b(property,? plant|capital expenditure|productive assets|tangible (fixed )?assets|fixed assets)\b", re.I),
        label_exclude=re.compile(
            r"\b(proceeds|disposal|sale|sold|gain|loss|depreciation|impairment|acquisitions? of (subsidiar|business)|"
            r"exploration|mineral)\b", re.I),
        standard_weight=Decimal("-1"),
        note="salida de caja por inversión en inmovilizado (signo del «Purchase of PP&E» estándar)",
    ),
    TargetRule(
        metric="financial_liabilities_noncurrent",
        duration=False,
        parts=_NONCURRENT_DEBT_PARTS,
        core=_NONCURRENT_DEBT_CORE,
        wider_ok=_std("ifrs-full:NoncurrentFinancialLiabilities", "ifrs-full:NoncurrentLiabilities"),
        calc_parents=_std("ifrs-full:NoncurrentLiabilities"),
        label=_DEBT_LABEL,
        label_exclude=_DEBT_EXCLUDE,
        note="deuda financiera no corriente",
    ),
    TargetRule(
        metric="financial_liabilities_current",
        duration=False,
        parts=_CURRENT_DEBT_PARTS,
        core=_CURRENT_DEBT_CORE,
        wider_ok=_std("ifrs-full:CurrentFinancialLiabilities", "ifrs-full:CurrentLiabilities",
                      "ifrs-full:CurrentLiabilitiesOtherThanLiabilitiesIncludedInDisposalGroupsClassifiedAsHeldForSale"),
        calc_parents=_std("ifrs-full:CurrentLiabilities",
                          "ifrs-full:CurrentLiabilitiesOtherThanLiabilitiesIncludedInDisposalGroupsClassifiedAsHeldForSale"),
        label=_DEBT_LABEL,
        label_exclude=_DEBT_EXCLUDE,
        note="deuda financiera corriente",
    ),
    TargetRule(
        metric="fee_related_earnings",
        duration=True,
        label=re.compile(r"\bfee[- ]related (earnings|income|profit)\b", re.I),
        label_exclude=re.compile(r"\b(per (share|unit)|margin|revenues?|expenses?|compensation|member|tax)\b", re.I),
        label_only=True,
        note="FRE: beneficio por comisiones de gestión (sin concepto estándar)",
    ),
    TargetRule(
        metric="distributable_earnings",
        duration=True,
        label=re.compile(r"\bdistributable (operating )?earnings\b", re.I),
        label_exclude=re.compile(r"\b(per (share|unit)|margin|member|tax)\b", re.I),
        label_only=True,
        note="DE: beneficio distribuible (sin concepto estándar)",
    ),
)
RULES_BY_METRIC = {rule.metric: rule for rule in TARGET_RULES}


# --------------------------------------------------------------------------
# Resolución
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ExtensionMapping:
    metric: str
    concept: str
    label: str
    rule: str
    evidence: str
    sign: int
    # (start, end) -> valor orientado al signo del concepto estándar.
    values: dict[tuple[str | None, str], Decimal]
    unit: str
    segment: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric, "concept": self.concept, "label": self.label, "rule": self.rule,
            "evidence": self.evidence, "sign": self.sign, "unit": self.unit, "segment": self.segment,
            "values": [{"start": s, "end": e, "val": str(v)} for (s, e), v in sorted(
                self.values.items(), key=lambda kv: (kv[0][1], kv[0][0] or ""))],
        }


@dataclass(frozen=True)
class NotAvailable:
    metric: str
    motivo: str

    def as_dict(self) -> dict[str, Any]:
        return {"metric": self.metric, "status": "N/D", "motivo": self.motivo}


Resolution = ExtensionMapping | NotAvailable


def _days(start: str | None, end: str) -> int | None:
    from datetime import date

    if not start:
        return None
    try:
        return (date.fromisoformat(end[:10]) - date.fromisoformat(start[:10])).days
    except ValueError:
        return None


def _annual(fact: ExtFact) -> bool:
    days = _days(fact.start, fact.end)
    return days is not None and 300 <= days <= 380


def _anchor_evidence(concept: str, rule: TargetRule, tax: ExtensionTaxonomy) -> str | None:
    narrow = tax.narrower.get(concept, set())
    wide = tax.wider.get(concept, set())
    if narrow and narrow <= rule.parts and narrow & rule.core:
        return "ancla ESEF: " + " + ".join(sorted(narrow)) + (f" ⊂ {sorted(wide)[0]}" if wide else "")
    return None


def _calc_arc(concept: str, rule: TargetRule, tax: ExtensionTaxonomy) -> CalcArc | None:
    for arc in tax.calc_parents.get(concept, []):
        if arc.parent in rule.calc_parents:
            return arc
    return None


def _label_ok(label: str, rule: TargetRule) -> bool:
    if rule.label is None or not rule.label.search(label):
        return False
    return not (rule.label_exclude and rule.label_exclude.search(label))


def _sign(concept: str, rule: TargetRule, tax: ExtensionTaxonomy, calc: CalcArc | None) -> int:
    """+1 si la extensión ya tiene el signo del concepto estándar; −1 si es el contrario.

    El peso de cálculo dice cómo suma en su total: con peso igual al estándar
    el signo es el mismo; con peso opuesto, el contrario. Sin relación de
    cálculo se toma el signo declarado (no se adivina)."""
    arc = calc
    if arc is None:
        for candidate in tax.calc_parents.get(concept, []):
            if candidate.parent in rule.calc_parents or candidate.parent in rule.wider_ok:
                arc = candidate
                break
    if arc is None or arc.weight == 0:
        return 1
    return 1 if (arc.weight > 0) == (rule.standard_weight > 0) else -1


def _scope(facts: list[ExtFact]) -> tuple[list[ExtFact], str | None, str | None]:
    """(hechos usables, segmento, motivo N/D).

    Gana el alcance consolidado (sin miembros). Si el concepto solo se declara
    por segmento y en UN único segmento, esa cifra es la del emisor (FRE de
    KKR: solo existe en gestión de activos) y queda anotado. Con varios
    segmentos y sin total, sumar omitiría corporativo y eliminaciones: N/D."""
    consolidated = [f for f in facts if not (set(f.members) - NEUTRAL_MEMBERS)]
    if consolidated:
        return consolidated, None, None
    by_member: dict[tuple[tuple[str, str], ...], list[ExtFact]] = {}
    for fact in facts:
        rest = tuple(sorted(set(fact.members) - NEUTRAL_MEMBERS))
        by_member.setdefault(rest, []).append(fact)
    segment_only = {k: v for k, v in by_member.items() if len(k) == 1 and k[0][0] in SEGMENT_AXES}
    if len(segment_only) == 1 and len(by_member) == 1:
        (key, rows), = segment_only.items()
        return rows, key[0][1], None
    if segment_only:
        names = ", ".join(sorted(k[0][1].split(":")[-1] for k in segment_only))
        return [], None, (f"solo por segmento ({len(segment_only)}: {names}) sin total consolidado etiquetado; "
                          "sumar segmentos omitiría corporativo y eliminaciones")
    return [], None, "solo en desgloses dimensionales, sin cifra consolidada"


@dataclass
class _Candidate:
    rank: int
    concept: str
    label: str
    rule: str
    evidence: str
    sign: int
    rows: list[ExtFact]
    segment: str | None


def _candidate(concept: str, rows: list[ExtFact], rule: TargetRule, tax: ExtensionTaxonomy) -> _Candidate | None:
    label = tax.labels.get(concept, "")
    calc: CalcArc | None = None
    evidence: str | None = None
    if rule.label_only:
        if not _label_ok(label, rule):
            return None
        which, evidence = RULE_LABEL, f"etiqueta estándar del emisor «{label}» ({rule.note})"
    elif evidence := _anchor_evidence(concept, rule, tax):
        which = RULE_ANCHOR
    elif (calc := _calc_arc(concept, rule, tax)) is not None and _label_ok(label, rule):
        which = RULE_CALC
        evidence = f"suma en {calc.parent} (peso {calc.weight:+g}) y la etiqueta «{label}» nombra la magnitud"
    else:
        return None
    return _Candidate(rank=_RULE_RANK[which], concept=concept, label=label, rule=which, evidence=evidence,
                      sign=_sign(concept, rule, tax, calc), rows=rows, segment=None)


def _resolve_one(rule: TargetRule, by_concept: dict[str, list[ExtFact]], tax: ExtensionTaxonomy) -> Resolution:
    candidates: list[_Candidate] = []
    refused: list[str] = []
    for concept in sorted(by_concept):
        rows = [f for f in by_concept[concept] if (f.start is not None) == rule.duration]
        if rule.duration:
            rows = [f for f in rows if _annual(f)]
        if not rows:
            continue
        cand = _candidate(concept, rows, rule, tax)
        if cand is None:
            continue
        usable, segment, why_not = _scope(rows)
        if why_not:
            refused.append(f"{concept}: {why_not}")
            continue
        cand.rows, cand.segment = usable, segment
        if segment:
            cand.evidence += f"; declarado solo en el segmento {segment.split(':')[-1]}"
        candidates.append(cand)
    if not candidates:
        return NotAvailable(rule.metric, "; ".join(refused) if refused else (
            "ningún concepto de extensión del filing equivale a la métrica "
            "(ni por anclaje ESEF, ni por cálculo+etiqueta, ni por etiqueta)"))
    best = min(c.rank for c in candidates)
    valued: list[tuple[_Candidate, dict[tuple[str | None, str], Decimal]]] = []
    for cand in (c for c in candidates if c.rank == best):
        values: dict[tuple[str | None, str], Decimal] = {}
        conflict = False
        for fact in cand.rows:
            key, val = (fact.start, fact.end), fact.value * cand.sign
            conflict = conflict or (key in values and values[key] != val)
            values[key] = val
        if conflict:
            refused.append(f"{cand.concept}: dos valores distintos para el mismo periodo")
            continue
        valued.append((cand, values))
    if not valued:
        return NotAvailable(rule.metric, "; ".join(refused))
    chosen, values = valued[0]
    disagree = [c.concept for c, v in valued[1:] if any(k in values and values[k] != x for k, x in v.items())]
    if disagree:
        return NotAvailable(rule.metric, f"ambigua: {chosen.concept} y {', '.join(disagree)} cumplen la misma "
                                         "regla con cifras distintas")
    units = sorted({f.unit for f in chosen.rows})
    return ExtensionMapping(metric=rule.metric, concept=chosen.concept, label=chosen.label, rule=chosen.rule,
                            evidence=chosen.evidence, sign=chosen.sign, values=values,
                            unit=units[0] if len(units) == 1 else "/".join(units), segment=chosen.segment)


def resolve_extensions(
    tax: ExtensionTaxonomy,
    facts: Iterable[ExtFact],
    *,
    metrics: Iterable[str] | None = None,
) -> dict[str, Resolution]:
    """Una resolución por métrica pedida: el concepto de extensión que la etiqueta, o N/D con motivo."""
    by_concept: dict[str, list[ExtFact]] = {}
    for fact in facts:
        if is_extension(fact.concept) and _monetary(fact.unit):
            by_concept.setdefault(fact.concept, []).append(fact)
    return {
        rule.metric: _resolve_one(rule, by_concept, tax)
        for rule in (RULES_BY_METRIC[m] for m in (metrics or RULES_BY_METRIC) if m in RULES_BY_METRIC)
    }
