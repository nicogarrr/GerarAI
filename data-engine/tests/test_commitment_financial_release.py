"""Comunicado financiero oficial: extraccion de la fila con cabecera verificada. HTML SINTETICO
con la estructura del comunicado SEC de UBER Q2-26 (leido 2026-10-22: fila Gross Bookings
$46,756 | $58,022 | 24% | 22% moneda constante). No es evidencia de cartera real."""
from dataclasses import replace
from datetime import date
from decimal import Decimal

from app.services.commitment_financial_release import (
    FINANCIAL_ASSETS,
    ISSUER_REPORTED,
    extract_gross_bookings,
    get_financial_asset,
)

ASSET = FINANCIAL_ASSETS[0]
TODAY = date(2026, 10, 22)
HEADER_ROW = ("<tr><td>(In millions, except percentages and per share amounts)</td><td>2025</td>"
              "<td>2026</td><td>% Change</td><td>% Change(Constant Currency (1))</td></tr>")
ROW = ("<tr><td>Gross Bookings</td><td>$</td><td>46,756&#160;</td><td>$</td><td>58,022&#160;</td>"
       "<td>24</td><td>%</td><td>22</td><td>%</td></tr>")


def _html(rows=HEADER_ROW + ROW, title=ASSET.title_marker):
    return f"<html><body><h1>{title}</h1><table>{rows}</table></body></html>".encode()


def test_separate_labeled_facts_reported_vs_constant_currency():
    facts, why = extract_gross_bookings(asset=ASSET, html=_html(), today=TODAY)
    assert why == "ok"
    by = {f.metric: f for f in facts}
    assert by["gross_bookings_usd_m"].value == Decimal("58022") and not by["gross_bookings_usd_m"].is_adjusted
    assert by["gross_bookings_growth_yoy_reported"].value == Decimal("24")
    cc = by["gross_bookings_growth_yoy_constant_currency"]
    assert cc.value == Decimal("22") and cc.is_adjusted is True
    assert all(f.provenance == ISSUER_REPORTED and f.source_url == ASSET.url for f in facts)
    assert "Gross Bookings" in facts[0].row_text and len(facts[0].html_sha256) == 64


def test_abstains_without_verified_header_or_unique_row_or_title():
    for html in (_html(rows=ROW), _html(rows=HEADER_ROW + ROW + ROW), _html(title="Otro"),
                 _html(rows=HEADER_ROW + ROW.replace("<td>22</td>", ""))):
        facts, why = extract_gross_bookings(asset=ASSET, html=html, today=TODAY)
        assert facts == [] and why != "ok"


def test_swapped_year_columns_or_future_asset_abstain():
    swapped = HEADER_ROW.replace("<td>2025</td>", "<td>2027</td>")
    assert extract_gross_bookings(asset=ASSET, html=_html(rows=swapped + ROW), today=TODAY)[0] == []
    future = replace(ASSET, published_on=date(2027, 1, 1))
    assert extract_gross_bookings(asset=future, html=_html(), today=TODAY)[0] == []


def test_registry_is_exact_url_and_not_a_transcript():
    assert get_financial_asset("UBER", ASSET.url) is ASSET
    assert get_financial_asset("UBER", ASSET.url + "?x=1") is None
    assert get_financial_asset("RKLB", ASSET.url) is None
    assert ASSET.kind == "press_release"
