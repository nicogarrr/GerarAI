"""Conservative HTML financial-statement reader for earnings exhibits.

No network, persistence, issuer-specific columns, OCR or non-GAAP fallback.
Only recognized GAAP statement tables, explicit dated headers and thousand/million
scales qualify. Currency must be supplied from verified filing metadata; a
dollar sign by itself does not prove USD. A table must pass internal arithmetic before any facts leave
it. Unknown/ambiguous formats yield diagnostics and no facts. This is a
bounded parser, not a promise to read every EX-99.1 or authenticate a filing.
The caller verifies issuer, 8-K Item 2.02 provenance, publication and cutoff.
"""
import calendar
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from lxml import html

MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
DATE = re.compile(r"(" + "|".join(MONTHS) + r")\s+(\d{1,2}),?\s*(20\d{2})?", re.I)
DURATION = re.compile(r"(three|six|nine|twelve|year)\s*(?:months?\s*)?ended", re.I)
MONTH_COUNT = {"three": 3, "six": 6, "nine": 9, "twelve": 12, "year": 12}


def _text(node):
    return " ".join(node.text_content().replace("\xa0", " ").split())


def _number(text):
    text = text.strip().replace("$", "").replace(",", "").replace(" ", "")
    if text in {"—", "–", "-"}:
        return Decimal(0)
    if re.fullmatch(r"\(?-?\d+(?:\.\d+)?\)?", text) is None:
        return None
    try:
        return Decimal(text[1:-1])*-1 if text.startswith("(") and text.endswith(")") else Decimal(text)
    except InvalidOperation:
        return None


def _grid(table):
    rows, occupied = [], {}
    for ri, tr in enumerate(table.xpath("./tr|./thead/tr|./tbody/tr|./tfoot/tr")):
        row, col = [], 0
        for cell in tr.xpath("./td|./th"):
            while (ri, col) in occupied:
                col += 1
            width, height = int(cell.get("colspan", 1)), int(cell.get("rowspan", 1))
            if not 1 <= width <= 200 or not 1 <= height <= 100:
                raise ValueError("excessive_span")
            item = (col, col+width, _text(cell))
            row.append(item)
            for r in range(ri, ri+height):
                for c in range(col, col+width):
                    occupied[r, c] = item
            col += width
        # Propagate rowspans into header rows as well.
        for item in {v for (r, _), v in occupied.items() if r == ri}:
            if item not in row:
                row.append(item)
        row = sorted(row)
        # SEC exports sometimes put a closing parenthesis in its own cell.
        for j, (left, right, text) in enumerate(row[:-1]):
            if text.startswith("(") and not text.endswith(")") and row[j+1][2] == ")":
                row[j] = (left, right, text+")")
        rows.append(row)
    return rows


def _header(rows, ri, pos, instant):
    # Header fragments are attached by their spanned column, never issuer index.
    fragments = [text for row in rows[:ri] for left, right, text in row
                 if left <= pos < right and text]
    year = next((int(t) for t in reversed(fragments) if re.fullmatch(r"20\d{2}", t)), None)
    match = next((m for t in reversed(fragments) if (m := DATE.search(t))), None)
    if match is None:
        return None
    y = int(match[3]) if match[3] else year
    if y is None:
        return None
    end = date(y, MONTHS[match[1].lower()], int(match[2]))
    if instant:
        return (None, end)
    duration = next((m for t in reversed(fragments) if (m := DURATION.search(t))), None)
    if duration is None:
        return None
    months = MONTH_COUNT[duration[1].lower()]
    # Durations are accepted only at a calendar quarter end, no 52/53 week guess.
    if end.month % 3 or end.day != calendar.monthrange(y, end.month)[1]:
        return None
    start_month = end.month-months+1
    start_year = y
    if start_month <= 0:
        start_month += 12
        start_year -= 1
    return (date(start_year, start_month, 1), end)


def _find(data, pattern):
    hits = [(label, val) for label, val in data if re.fullmatch(pattern, label, re.I)]
    return hits[0][1] if len(hits) == 1 else None


def _checks(kind, data):
    checks = []

    def equation(name, lhs, rhs):
        if lhs is not None and rhs is not None:
            checks.append({"name": name, "residual": str(lhs-rhs), "ok": abs(lhs-rhs) <= 1})

    if kind == "balance":
        assets = _find(data, r"total assets")
        total = _find(data, r"total liabilities.*(?:equity|deficit)")
        equation("balance_total", assets, total)
        liabilities = _find(data, r"total liabilities")
        equity = _find(data, r"total (?:stockholders['’]? |shareholders['’]? )?equity")
        redeemable = _find(data, r"redeemable non-controlling interests")
        if liabilities is None:
            # A conventional current subtotal followed by noncurrent components.
            # Do not count the underlying current rows twice.
            first = next((i for i, (label, _) in enumerate(data)
                          if re.fullmatch(r"total current liabilities", label, re.I)), None)
            last = next((i for i, (label, _) in enumerate(data)
                         if re.fullmatch(r"(?:controlling interest|common stock.*)", label, re.I)), None)
            if first is not None and last is not None and first < last:
                components = data[first:last]
                if not any("total" in label.lower() for label, _ in components[1:]):
                    liabilities = sum(v for _, v in components)
        if liabilities is not None and equity is not None:
            if redeemable is None:
                equation("balance_bridge", total, liabilities+equity)
            else:
                equation("balance_bridge", total, liabilities+equity+redeemable)
    elif kind == "income":
        rev = _find(data, r"(?:total )?revenues?")
        cost = _find(data, r"total costs and expenses")
        op = _find(data, r"(?:income from operations|operating income|operating profit)")
        if cost is None:
            cost = _find(data, r"__total_costs_and_expenses")
        if rev is not None and cost is not None:
            equation("revenue_to_operating_income", op, rev-cost)
            revenue_index = next(i for i, (label, _) in enumerate(data) if re.fullmatch(r"(?:total )?revenues?", label, re.I))
            cost_index = next(i for i, (label, _) in enumerate(data) if re.fullmatch(r"(?:total costs and expenses|__total_costs_and_expenses)", label, re.I))
            equation("operating_cost_components", cost,
                     sum((v for _, v in data[revenue_index+1:cost_index]), Decimal(0)))
        else:
            cost = _find(data, r"(?:total )?cost of revenues?(?: \(\d+\))?")
            gross = _find(data, r"gross (?:margin|profit)")
            if rev is not None and cost is not None:
                equation("revenue_to_gross_margin", gross, rev-cost)
        pretax = _find(data, r"(?:income before (?:income taxes(?: and income/loss from equity method investments)?|provision for income taxes)|loss before income tax expense)")
        tax = _find(data, r"(?:provision for \(benefit from\) income taxes|provision for income taxes|income tax expense)")
        net = _find(data, r"(?:consolidated )?net (?:income(?: including non-controlling interests)?|loss before allocation to noncontrolling interest)")
        equity_loss = _find(data, r"loss from equity method investments")
        if rev is not None and pretax is not None and not any(c["name"].startswith("revenue_") for c in checks):
            expenses = _find(data, r"total operating expenses")
            other = _find(data, r"total other \(expense\) income, net")
            if expenses is not None and other is not None:
                equation("revenue_to_pretax", pretax, rev-expenses+other)
        if pretax is not None and tax is not None:
            # Income-tax expense may be presented as a parenthesized
            # deduction (Charter). Provision/benefit is algebraic (Uber).
            if _find(data, r"income tax expense") is not None:
                tax = abs(tax)
            includes_equity = any("and income/loss from equity method investments" in label.lower()
                                  for label, _ in data)
            if includes_equity:
                if equity_loss is not None:
                    equation("pretax_to_net_income", net, pretax-tax+equity_loss)
            else:
                equation("pretax_to_net_income", net, pretax-tax)
        attributable = _find(data, METRICS["net_income_attributable"])
        minority = _find(data, r"(?:less: )?net (?:income|loss) attributable to non-?controlling interests?")
        if attributable is not None and net is not None and minority is not None:
            # A parenthesized 'Less' line is already signed in some releases.
            signed = next((v for label, v in data if label.lower().startswith("less:")), None)
            equation("net_income_attribution", attributable,
                     net+signed if signed is not None and signed < 0 else net-minority)
    elif kind == "cashflow":
        index = next((i for i, (label, _) in enumerate(data)
                      if re.fullmatch(r"net cash (?:provided by|used in|flows from) operating activities|net cash from operations", label, re.I)), None)
        if index is not None:
            # Every numeric adjustment before the CFO total is required. This
            # avoids accepting a picked subset that happens to fit a headline.
            equation("cfo_components", data[index][1], sum((v for _, v in data[:index]), Decimal(0)))
        investing = next((i for i, (label, _) in enumerate(data) if re.fullmatch(
            r"net cash (?:provided by \(used in\)|used in|flows (?:used in|from)) investing(?: activities)?", label, re.I)), None)
        if index is not None and investing is not None:
            prior_totals = [i for i, (label, _) in enumerate(data[:investing])
                            if re.match(r"net cash", label, re.I)]
            start = max(prior_totals)+1 if prior_totals else index+1
            equation("investing_components_including_capex", data[investing][1],
                     sum((v for _, v in data[start:investing]), Decimal(0)))
    return checks


METRICS = {
    "revenue": r"(?:total )?revenues?",
    "net_income_consolidated": r"(?:consolidated )?net (?:income(?: including non-controlling interests)?|loss before allocation to noncontrolling interest)",
    "net_income_attributable": r"net (?:income|loss) attributable to (?:.+ shareholders|(?:.+ )?common stockholders|.+, inc\.)",
    "operating_cash_flow": r"net cash (?:provided by|used in|flows from) operating activities|net cash from operations",
    "capital_expenditure": r"purchases? of property(?:,? plant)? and equipment|additions to property and equipment|purchases of property, equipment and capitalized software",
    "total_assets": r"total assets", "total_liabilities": r"total liabilities",
    "cash_and_equivalents": r"cash and cash equivalents",
    "depreciation_amortization": r"depreciation and amortization",
    "cash_interest_paid": r"cash paid for interest",
}


def parse_ex991_tables(markup: str, *, source_url: str, published: date, reporting_currency: str | None = None) -> dict:
    result = {"status": "unrecognized", "facts": [], "tables": [], "source_url": source_url}
    if len(markup) > 10_000_000 or not source_url.startswith("https://") or reporting_currency not in {"USD", "CAD", "AUD", "NZD", "HKD", "SGD"}:
        return result
    try:
        root = html.fromstring(markup)
        tables = root.xpath("//table[not(ancestor::table)]")
        for ti, table in enumerate(tables):
            context = " ".join(_text(n) for n in table.xpath("preceding::*[not(ancestor::table)]")[-8:])[-1600:]
            text = _text(table)
            title = (context+" "+text[:250]).lower()
            if "non-gaap" in text[:300].lower() or "alternative presentation" in text[:300].lower():
                continue
            kind = ("cashflow" if re.search(r"(?:statements? of cash flows|cash flows statements)", title) else
                    "balance" if "balance sheets" in title else
                    "income" if re.search(r"(?:statements? of operations|income statements)", title) else None)
            scale_match = re.search(r"\((?:dollars )?in (millions|thousands)\b", title)
            if kind is None or scale_match is None or "$" not in text:
                continue
            scale = 1000000 if scale_match[1] == "millions" else 1000
            rows = _grid(table)
            if len(rows) > 2000:
                continue
            columns = {}
            section = ""
            header_end = None
            for ri, row in enumerate(rows):
                label = next((t for _, _, t in row if t and _number(t) is None and t != "$"), "")
                if label.upper() == "COSTS AND EXPENSES:":
                    section = "costs_and_expenses"
                if not label and section == "costs_and_expenses" and any(_number(v) is not None for _, _, v in row):
                    label = "__total_costs_and_expenses"
                    section = ""
                if not label or re.fullmatch(r"20\d{2}", label):
                    continue
                if header_end is None and any(_number(v) is not None for _, _, v in row) and not DATE.search(label) and not DURATION.search(label):
                    header_end = ri
                if header_end is None:
                    continue
                for left, right, value in row:
                    number = _number(value)
                    if number is None or value == label:
                        continue
                    period = _header(rows[:header_end], header_end, (left+right)/2, kind == "balance")
                    if period is not None and period[1] <= published:
                        columns.setdefault(period, []).append((label, number))
            for (start, end), data in columns.items():
                checks = _checks(kind, data)
                required = {"balance": {"balance_total", "balance_bridge"},
                            "income": {"pretax_to_net_income"},
                            "cashflow": {"cfo_components", "investing_components_including_capex"}}[kind]
                names = {c["name"] for c in checks}
                if kind == "income" and not names & {"revenue_to_operating_income", "revenue_to_gross_margin", "revenue_to_pretax"}:
                    checks.append({"name": "revenue_check_missing", "ok": False})
                valid = required <= names and all(c["ok"] for c in checks)
                result["tables"].append({"table": ti, "kind": kind, "start": start, "end": end,
                                          "status": "ok" if valid else "rejected", "checks": checks})
                if not valid:
                    continue
                for metric, pattern in METRICS.items():
                    value = _find(data, pattern)
                    allowed = {
                        "income": {"revenue", "net_income_consolidated", "net_income_attributable"},
                        "balance": {"total_assets", "total_liabilities", "cash_and_equivalents"},
                        "cashflow": {"operating_cash_flow", "capital_expenditure", "depreciation_amortization", "cash_interest_paid"},
                    }
                    if metric == "net_income_attributable" and "net_income_attribution" not in names:
                        continue
                    if value is not None and metric in allowed[kind]:
                        result["facts"].append({"metric": metric, "value": value, "unit": reporting_currency,
                            "source_label": next(label for label, v in data if re.fullmatch(pattern, label, re.I)),
                            "scale": scale, "period_start": start, "period_end": end,
                            "period_kind": "instant" if start is None else "duration",
                            "source_url": source_url, "published": published, "table": ti,
                            "statement": kind, "provisional": True})
        # One fact per metric and period. Independent statements must agree.
        unique = {}
        conflicts = set()
        for fact in result["facts"]:
            key = (fact["metric"], fact["period_start"], fact["period_end"])
            if key in unique and unique[key]["value"]*unique[key]["scale"] != fact["value"]*fact["scale"]:
                conflicts.add(key)
            else:
                unique[key] = fact
        if conflicts:
            return {**result, "status": "conflicting_statements", "facts": [],
                    "conflicts": [str(k) for k in sorted(conflicts)]}
        result["facts"] = list(unique.values())
        result["status"] = "partial" if result["facts"] else "unrecognized_or_failed_reconciliation"
        return result
    except (ValueError, TypeError, OverflowError):
        return {**result, "status": "invalid", "facts": []}


def select_ex991_fact(result: dict, metric: str, *, period_start: date | None,
                      period_end: date) -> dict:
    """Exact period only. No Q2->Q3, YTD->quarter, annualizing or zero fill."""
    matches = [f for f in result.get("facts", []) if f["metric"] == metric
               and f["period_start"] == period_start and f["period_end"] == period_end]
    if len(matches) == 1:
        return {"status": "ok", "fact": matches[0]}
    ends = [f["period_end"] for f in result.get("facts", []) if f["metric"] == metric]
    return {"status": "not_available", "fact": None,
            "latest_available_period_end": max(ends) if ends else None}
