"""Conservative SEC KPI observations. Never publishes or approves facts.

Only explicit, single-period rows and complete inline-XBRL fragments are
accepted. Missing context, dimensions, units or aliases mean no observation.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from io import StringIO
from xml.etree import ElementTree as ET

VERSION = "sec-ir-kpi-deterministic-v1"
# Exact standard concepts only. Extensions require a reviewed mapping.
CONCEPTS = {
    "RevenueFromContractWithCustomerExcludingAssessedTax": "revenue",
    "Revenues": "revenue", "SalesRevenueNet": "revenue",
    "Assets": "total_assets", "Liabilities": "total_liabilities",
    "NetIncomeLoss": "net_income", "OperatingIncomeLoss": "operating_income",
    "CashAndCashEquivalentsAtCarryingValue": "cash_and_equivalents",
}
UNITS = {"USD", "EUR", "GBP", "count", "percent", "%", "decimal"}
SCALES = {0: "", 3: "thousand", 6: "million", 9: "billion"}
NUMBER = r"[-(]?\d[\d,.]*(?:\))?"
ROW = re.compile(
    rf"^\s*(?P<label>[^|\t:]+?)\s*[|\t:]\s*(?P<period>(?:FY|Q[1-4])20\d{{2}})"
    rf"\s*[|\t:]\s*(?P<unit>USD|EUR|GBP|count|percent|%|decimal)"
    rf"(?:\s+(?P<scale>thousand|million|billion))?\s*[|\t:]\s*(?P<value>{NUMBER})\s*$",
    re.IGNORECASE,
)


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _observation(key, label, value, unit, period, chunk, quote, **trace):
    return {"metric_key": key, "raw_label": label, "raw_value": value,
            "raw_unit": unit, "period": period, "fiscal_year": int(period[-4:]),
            "fiscal_quarter": period[:-4], "chunk_id": chunk.id,
            "quote": quote, "confidence": 1.0, "_deterministic": trace}


def extract(chunks, registry, *, source_type: str, cik: str | None = None):
    if source_type.upper() not in {"SEC", "IR"}:
        return []
    active = {row.metric_key: row for row in registry if row.active}
    aliases = {}
    for key, row in active.items():
        for label in [key, *(row.aliases or [])]:
            aliases.setdefault(str(label).strip().casefold(), set()).add(key)
    observations = []
    for chunk in chunks:
        for line in chunk.text.splitlines():
            match = ROW.fullmatch(line)
            if match is None:
                continue
            fields = match.groupdict()
            keys = aliases.get(fields["label"].strip().casefold(), set())
            if len(keys) != 1:
                continue
            key = next(iter(keys))
            unit = fields["unit"].upper() if fields["unit"].upper() in {"USD", "EUR", "GBP"} else fields["unit"].lower()
            canonical = active[key].canonical_unit
            if unit in {"USD", "EUR", "GBP"} and canonical != unit:
                continue
            if unit not in {"USD", "EUR", "GBP"} and canonical != ("decimal" if unit in {"percent", "%", "decimal"} else "count"):
                continue
            observations.append(_observation(key, fields["label"], fields["value"],
                " ".join(x for x in (unit, fields["scale"]) if x), fields["period"].upper(),
                chunk, line.strip(), parser="explicit-row"))
        if source_type.upper() == "SEC":
            observations.extend(_xbrl(chunk, active, cik))
    # Contradictory repeated values are kept as review candidates, not resolved
    # by guessing which occurrence/taxonomy/period is authoritative.
    if source_type.upper() == "IR":
        observations.extend(_ir_narrative(chunks, active, adjacent_context=True))
    observations.extend(_explicit_money(chunks, active))
    values = {}
    for observation in observations:
        values.setdefault((observation["metric_key"], observation["period"]), set()).add(
            (observation["raw_value"], observation["raw_unit"]))
    for observation in observations:
        observation["_conflict"] = len(values[(observation["metric_key"], observation["period"])]) > 1
    return observations


def _xbrl(chunk, active, cik):
    if not cik or "nonFraction" not in chunk.text:
        return []
    try:
        namespaces = dict(value for _, value in ET.iterparse(StringIO(chunk.text), events=("start-ns",)))
        if not re.fullmatch(r"https?://fasb.org/us-gaap/20\d{2}(?:-\d{2}-\d{2})?", namespaces.get("us-gaap", "")):
            return []
        if not re.fullmatch(r"https?://xbrl.sec.gov/dei/20\d{2}(?:-\d{2}-\d{2})?", namespaces.get("dei", "")):
            return []
        root = ET.fromstring(chunk.text)
    except ET.ParseError:
        return []
    contexts, units = {}, {}
    for element in root.iter():
        if element.tag == "{http://www.xbrl.org/2003/instance}context":
            contexts[element.get("id")] = element
        if element.tag == "{http://www.xbrl.org/2003/instance}unit":
            measures = [e.text for e in element.iter() if _local(e.tag) == "measure"]
            if len(measures) == 1 and not any(_local(e.tag) == "divide" for e in element.iter()):
                units[element.get("id")] = measures[0]
    result = []
    for fact in root.iter():
        if fact.tag != "{http://www.xbrl.org/2013/inlineXBRL}nonFraction":
            continue
        name = fact.get("name", "")
        key = CONCEPTS.get(name.removeprefix("us-gaap:")) if name.startswith("us-gaap:") else None
        if key not in active or fact.get("format") or fact.get("nil") or fact.get("{http://www.w3.org/2001/XMLSchema-instance}nil") or fact.get("sign") not in {None, "-"}:
            continue
        context = contexts.get(fact.get("contextRef"))
        if context is None:
            continue
        nodes = list(context.iter())
        if any(_local(e.tag) in {"segment", "scenario", "explicitMember", "typedMember"} for e in nodes):
            continue
        identifiers = [e.text for e in nodes if _local(e.tag) == "identifier"]
        if len(identifiers) != 1 or str(identifiers[0]).lstrip("0") != str(cik).lstrip("0"):
            continue
        fiscal_years = [e.text for e in root.iter()
            if e.tag == "{http://www.xbrl.org/2013/inlineXBRL}nonNumeric" and e.get("name") == "dei:DocumentFiscalYearFocus"
            and e.get("contextRef") == fact.get("contextRef")]
        if len(fiscal_years) != 1 or not re.fullmatch(r"20\d{2}", fiscal_years[0] or ""):
            continue
        starts = [e.text for e in nodes if _local(e.tag) == "startDate"]
        ends = [e.text for e in nodes if _local(e.tag) == "endDate"]
        # FY only when a full-year duration is explicit; no quarter guesses,
        # instants, YTD-as-quarter or fiscal-year inference from document title.
        try:
            if len(starts) != 1 or len(ends) != 1:
                continue
            if not 350 <= (date.fromisoformat(ends[0]) - date.fromisoformat(starts[0])).days <= 380:
                continue
            scale = int(fact.get("scale", "0"))
            raw = "".join(fact.itertext()).strip()
            value = Decimal(raw)
            if scale not in SCALES or not value.is_finite():
                continue
        except (ValueError, InvalidOperation):
            continue
        currency = str(units.get(fact.get("unitRef"), "")).removeprefix("iso4217:")
        if currency not in {"USD", "EUR", "GBP"} or active[key].canonical_unit != currency:
            continue
        if fact.get("sign") == "-":
            raw = str(-value)
        result.append(_observation(key, name, raw, f"{currency} {SCALES[scale]}".strip(),
            f"FY{fiscal_years[0]}", chunk, chunk.text, parser="inline-xbrl",
            concept=name, context_id=fact.get("contextRef"), start=starts[0], end=ends[0], scale=scale))
    return result


# Reporting-period anchor is an explicit filing declaration, not a page
# timestamp or a guessed calendar quarter. Context quote is preserved too.
_IR_QUARTER = re.compile(
    r"(?:financial results|financial statements).{0,160}?for the quarter ended "
    r"[A-Za-z]+\s+\d{1,2},\s+20\d{2}\s*\([\"“]?(Q[1-4])\s+(20\d{2})[\"”]?\)",
    re.IGNORECASE | re.DOTALL,
)
_IR_MARGIN = re.compile(
    r"\bgross (?:profit )?margin\s+(?:was|of|stood at)\s+"
    r"(?P<value>\d{1,2}(?:[.,]\d+)?|100(?:[.,]0+)?)\s*%",
    re.IGNORECASE,
)


def _ir_narrative(chunks, active, *, adjacent_context=True):
    if "gross_margin" not in active or active["gross_margin"].canonical_unit != "decimal":
        return []
    anchors = [(index, chunk, match) for index, chunk in enumerate(chunks)
               for match in _IR_QUARTER.finditer(chunk.text)]
    periods = {(m.group(1).upper(), m.group(2)) for _, _, m in anchors}
    if len(periods) != 1:
        return []
    result = []
    for index, source_chunk in enumerate(chunks):
        # A current-quarter result can refer to the declaration in its own
        # chunk or the immediately preceding chunk, never a distant footer.
        contexts = [(c, m) for n, c, m in anchors
                    if n == index or (adjacent_context and n == index - 1)]
        if not contexts:
            continue
        context_chunk, anchor = contexts[-1]
        for paragraph in source_chunk.text.split("\n\n"):
            # Skip scripts/schema/nav. Require prose about a realized result,
            # not headline snippets, search JSON or projected margins.
            if any(token in paragraph for token in ("{", "}", "<script", "https://", "PrevPrevious", "NextKraken")):
                continue
            if not re.search(r"\b(?:in the quarter|for the quarter|current quarter)\b", paragraph, re.I):
                continue
            for match in _IR_MARGIN.finditer(paragraph):
                if re.search(r"(?:prior|previous|comparable)\s+(?:year|quarter)\s+", paragraph[:match.start()][-60:], re.I):
                    continue
                sentence_start = max((m.end() for m in re.finditer(r"[.!?]\s+(?=[A-Z])", paragraph[:match.start()])), default=0)
                sentence_end = re.search(r"[.!?](?:\s+(?=[A-Z])|$)", paragraph[match.end():])
                end = match.end() + sentence_end.start() + 1 if sentence_end else len(paragraph)
                quote = paragraph[sentence_start:end].strip()
                if re.search(r"\b(?:expect|guidance|forecast|project|target)\w*\b", quote, re.I):
                    continue
                observation = _observation("gross_margin", "Gross margin", match.group("value"),
                    "percent", anchor.group(1).upper() + anchor.group(2), source_chunk, quote,
                    parser="ir-current-quarter-margin", context={"chunk_id": context_chunk.id,
                    "quote": anchor.group(), "role": "reporting_period"})
                result.append(observation)
    return result


_MONEY_SENTENCE = re.compile(
    rf"(?P<label>[A-Za-z][A-Za-z _]{{1,60}}?)\s+(?:in|for)\s+"
    rf"(?P<period>FY|Q[1-4])\s*(?P<year>20\d{{2}})\s+"
    rf"(?:was|were|totaled|amounted to)\s+(?P<currency>USD|EUR|GBP)\s+"
    rf"(?P<value>{NUMBER})(?:\s+(?P<scale>thousand|million|billion))?\.?", re.I,
)


def _explicit_money(chunks, active):
    aliases = {}
    for key, row in active.items():
        for name in [key.replace("_", " "), *(row.aliases or [])]:
            aliases.setdefault(name.casefold(), set()).add(key)
    result = []
    for chunk in chunks:
        for line in chunk.text.splitlines():
            # Full-match only. A decimal point can NEVER terminate a partial
            # amount, and trailing prose (including forecast qualifiers) is
            # unsupported rather than silently removed from the citation.
            quote = line.strip()
            match = _MONEY_SENTENCE.fullmatch(quote)
            if match is None:
                continue
            keys = aliases.get(match.group("label").strip().casefold(), set())
            if len(keys) != 1:
                continue
            key = next(iter(keys))
            currency = match.group("currency").upper()
            if active[key].canonical_unit != currency:
                continue
            # Never match inside HTML/JSON or a projected sentence.
            prefix = quote
            if any(token in prefix for token in ("{", "<", '"')) or re.search(
                r"\b(?:forecast|guidance|expect|project|target)\w*\b", prefix, re.I
            ):
                continue
            result.append(_observation(key, match.group("label"), match.group("value"),
                f"{currency} {match.group('scale') or ''}".strip(),
                match.group("period").upper() + match.group("year"), chunk, quote,
                parser="explicit-period-currency-sentence"))
    return result
