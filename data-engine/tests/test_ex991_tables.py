"""Original downloaded HTML fixtures, not issuer-specific column recipes."""
import gzip
import hashlib
import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from lxml import html

from app.valuation.ex991_tables import parse_ex991_tables, select_ex991_fact

FIXTURES = Path(__file__).parent / "fixtures/ex991"
SOURCES = json.loads((FIXTURES / "sources.json").read_text())


def markup(name):
    data = gzip.decompress((FIXTURES / f"{name}.html.gz").read_bytes())
    assert hashlib.sha256(data).hexdigest() == SOURCES[name]["sha256"]
    return data.decode()


def parse(name, text=None, **kwargs):
    return parse_ex991_tables(text if text is not None else markup(name), source_url=SOURCES[name]["url"],
                              published=date(2026, 11, 4), reporting_currency="USD", **kwargs)


def fact(result, metric, start, end):
    values = [r for r in result["facts"] if r["metric"] == metric and
              r["period_start"] == start and r["period_end"] == end]
    assert len(values) == 1
    return values[0]


@pytest.mark.parametrize("name", SOURCES)
def test_original_bytes_are_pinned(name):
    assert markup(name)


def test_uber_colspans_quarter_ytd_balance_and_gaap_not_adjusted():
    result = parse("uber")
    q = date(2026, 7, 1), date(2026, 9, 30)
    ytd = date(2026, 1, 1), date(2026, 9, 30)
    assert fact(result, "revenue", *q)["value"] == 14766
    assert fact(result, "revenue", *ytd)["value"] == 42160
    assert fact(result, "net_income_consolidated", *q)["value"] == 569  # not parent-only512 or adjusted
    assert fact(result, "operating_cash_flow", *q)["value"] == 2639
    assert fact(result, "capital_expenditure", *q)["value"] == -104
    assert fact(result, "total_assets", None, q[1])["value"] == 71067
    assert fact(result, "depreciation_amortization", *q)["value"] == 218  # CF, not IS212
    assert all(r["scale"] == 1000000 and r["unit"] == "USD" for r in result["facts"])


def test_charter_blank_columns_and_signed_tax_expense():
    result = parse("chtr")
    q = date(2026, 4, 1), date(2026, 6, 30)
    assert fact(result, "revenue", *q)["value"] == 13526
    assert fact(result, "net_income_consolidated", *q)["value"] == 1524
    assert fact(result, "operating_cash_flow", *q)["value"] == 3925
    assert fact(result, "capital_expenditure", *q)["value"] == -2871
    assert fact(result, "total_assets", None, q[1])["value"] == 155618


def test_microsoft_reverse_year_order_and_financing_before_investing():
    result = parse("msft")
    q = date(2026, 7, 1), date(2026, 9, 30)
    assert fact(result, "revenue", *q)["value"] == 92279
    assert fact(result, "net_income_consolidated", *q)["value"] == 36629
    assert fact(result, "operating_cash_flow", *q)["value"] == 58000
    assert fact(result, "capital_expenditure", *q)["value"] == -39367
    assert fact(result, "total_assets", None, q[1])["value"] == 779403
    # "Depreciation, amortization, and other" is NOT plain D&A.
    assert not any(r["metric"] == "depreciation_amortization" for r in result["facts"])


def test_unh_image_pages_and_hidden_text_are_not_tables():
    result = parse("unh")
    assert result["facts"] == []
    assert result["status"] == "unrecognized_or_failed_reconciliation"


def test_broken_cfo_or_capex_rejects_cashflow_period():
    root = html.fromstring(markup("uber"))
    cells = root.xpath('//table')[6].xpath('.//td')
    cell = next(c for c in cells if ' '.join(c.text_content().split()) == '2,639')
    cell.clear()
    cell.text = '2,640.5'  # >1 million stated rounding tolerance
    result = parse("uber", html.tostring(root, encoding="unicode"))
    assert not any(f["metric"] == "operating_cash_flow" and f["period_start"] == date(2026, 7, 1)
                   for f in result["facts"])
    assert any(t["status"] == "rejected" for t in result["tables"])


def test_no_currency_metadata_no_facts_and_no_table_no_facts():
    assert parse_ex991_tables(markup("uber"), source_url=SOURCES["uber"]["url"],
                               published=date(2026, 11, 4))["facts"] == []
    assert parse("uber", "<p>Revenue $14766</p>")["facts"] == []


def test_dates_not_columns_and_unrelated_number_not_confused():
    result = parse("uber")
    assert fact(result, "operating_cash_flow", date(2025, 7, 1), date(2025, 9, 30))["value"] == Decimal(2328)


@pytest.mark.parametrize("table_index,old,new,statement", [
    (4, '71,067', '71,087', 'balance'),
    (5, '855', '875', 'income'),
    (6, '(104)', '(114)', 'cashflow'),
])
def test_mutated_financial_values_cannot_escape_reconciliation(table_index, old, new, statement):
    root = html.fromstring(markup("uber"))
    table = root.xpath('//table')[table_index]
    cell = next(c for c in table.xpath('.//td') if ' '.join(c.text_content().split()) == old)
    cell.clear()
    cell.text = new
    result = parse("uber", html.tostring(root, encoding="unicode"))
    rejected = [t for t in result['tables'] if t['kind'] == statement and t['status'] == 'rejected']
    assert rejected


def test_unknown_scale_is_not_assumed_millions():
    result = parse("uber", re.sub('millions', 'undefined units', markup("uber"), flags=re.I))
    assert result['facts'] == []


@pytest.mark.parametrize("name", ["unh", "tsla", "jpm"])
def test_nonstatement_or_image_exhibits_do_not_create_facts(name):
    assert parse(name)["facts"] == []


def test_asts_thousands_split_negative_parentheses_and_no_q3():
    result = parse("asts")
    q = date(2026, 4, 1), date(2026, 6, 30)
    assert fact(result, "revenue", *q)["value"] == 31520
    assert fact(result, "net_income_attributable", *q)["value"] == -230909
    assert fact(result, "cash_and_equivalents", None, q[1])["value"] == 2288253
    assert all(f["scale"] == 1000 for f in result["facts"])
    absent = select_ex991_fact(result, "revenue", period_start=date(2026, 7, 1), period_end=date(2026, 9, 30))
    assert absent == {"status": "not_available", "fact": None, "latest_available_period_end": q[1]}


def test_pltr_ytd_flows_not_quarter_and_attributable_not_consolidated():
    result = parse("pltr")
    q = date(2026, 7, 1), date(2026, 9, 30)
    assert fact(result, "revenue", *q)["value"] == 2313411
    assert fact(result, "net_income_attributable", *q)["value"] == 1128012
    assert fact(result, "net_income_consolidated", *q)["value"] == 1134441
    assert fact(result, "operating_cash_flow", date(2026, 1, 1), q[1])["value"] == 3319902
    assert select_ex991_fact(result, "operating_cash_flow", period_start=q[0], period_end=q[1])["fact"] is None


def test_publication_cutoff_and_malformed_html_fail_closed():
    assert parse_ex991_tables(markup("uber"), source_url=SOURCES["uber"]["url"],
        published=date(2024, 1, 1), reporting_currency="USD")["facts"] == []
    assert parse("uber", markup("uber").replace('colspan="3"', 'colspan="99999"'))["facts"] == []


def test_2025_is_a_valid_amount_not_automatically_a_header():
    from app.valuation.ex991_tables import _number
    assert _number("2,025") == 2025
    assert _number("2026") == 2026


def test_year_like_amount_does_not_change_later_period_headers():
    root = html.fromstring(markup("uber"))
    table = root.xpath('//table')[5]
    cell = next(c for c in table.xpath('.//td') if ' '.join(c.text_content().split()) == '212')
    cell.clear()
    cell.text = '2026'
    result = parse("uber", html.tostring(root, encoding='unicode'))
    # A year-like amount cannot rewrite headers or evade cost-component checks.
    assert any(t['status'] == 'rejected' for t in result['tables'])
    assert not any(t['end'].year == 212 for t in result['tables'])


def test_valid_result_retains_source_and_publication_on_every_fact():
    for f in parse('uber')['facts']:
        assert f['source_url'] == SOURCES['uber']['url']
        assert f['published'] == date(2026, 11, 4)
        assert f['provisional'] is True
        assert f['source_label']


def test_missing_equity_loss_operand_does_not_mean_zero():
    from app.valuation.ex991_tables import _checks
    data = [("Revenue", Decimal(100)), ("total costs and expenses", Decimal(20)),
            ("Operating income", Decimal(80)),
            ("Income before income taxes and income/loss from equity method investments", Decimal(70)),
            ("Provision for income taxes", Decimal(10)), ("Net income", Decimal(60))]
    assert not any(c["name"] == "pretax_to_net_income" for c in _checks("income", data))
    explicit = _checks("income", data + [("Loss from equity method investments", Decimal(0))])
    assert any(c["name"] == "pretax_to_net_income" and c["ok"] for c in explicit)
