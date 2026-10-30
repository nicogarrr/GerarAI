"""Relative-multiples engine: the screen, and the reasons not to trust it.

Formula tests check hand-computed values, and one of them proves the pure
primitives are the SAME arithmetic as
``app/services/historical_valuation_service.py`` (both run over the same
inputs and must agree), because a second implementation of "the P/E" is a
second opinion nobody asked for.

Statistical honesty covered here: a negative denominator is N/D with a reason
(not a cheap-looking negative number), a peer set below five is declared in
the trace and blocked from publication, an undeclared multiple source is
marked ``source="N/D"``, and the engine publishes its own disagreement with the
FCFF DCF instead of quietly picking a winner.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Company, FinancialFact, MarketPrice
from app.models.entities import Base
from app.services.historical_valuation_service import HistoricalValuationService
from app.valuation.engines.relative_multiples import (
    MULTIPLE_PREFERENCE,
    PROVIDER_MULTIPLE_TEMPLATE,
    UNDECLARED_SOURCE,
    RelativeMultiplesEngine,
)
from app.valuation.relative_multiples import (
    MULTIPLE_KINDS,
    PeerMultiple,
    RelativeMultipleError,
    derive_multiple,
    describe_peer_sample,
    divergence_report,
    enterprise_value,
    implied_value,
    median,
    peer_percentile_of,
    percentile,
)

PERIOD = "FY2025"
FY = 2025
PRICE_DAY = date(2025, 12, 31)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _company(db, ticker, *, company_type="standard", valuation_model="standard_dcf"):
    row = Company(
        ticker=ticker,
        name=f"{ticker} test",
        exchange="TEST",
        currency="USD",
        sector="Technology",
        industry="Software",
        company_type=company_type,
        valuation_model=valuation_model,
        special_sources=[],
        special_risks=[],
        factor_tags=["software"],
    )
    db.add(row)
    db.flush()
    return row


def _facts(db, company, values, *, period=PERIOD, fiscal_year=FY, source_type="relative_test"):
    for metric, value in values.items():
        db.add(
            FinancialFact(
                company_id=company.id,
                metric=metric,
                value=Decimal(str(value)),
                unit="USD",
                period=period,
                fiscal_year=fiscal_year,
                fiscal_quarter="FY",
                source_type=source_type,
                is_reported=True,
                confidence=Decimal("0.90"),
            )
        )
    db.commit()


def _price(db, company, price, *, day=PRICE_DAY):
    db.add(
        MarketPrice(
            company_id=company.id,
            date=day,
            close=Decimal(str(price)),
            adj_close=Decimal(str(price)),
            source="relative_test",
        )
    )
    db.commit()


def _peer(db, ticker, price, eps, *, revenue=1000.0, fcf=100.0, debt=200.0, cash=50.0, shares=100.0):
    peer = _company(db, ticker)
    _facts(
        db,
        peer,
        {
            "eps": eps,
            "revenue": revenue,
            "free_cash_flow": fcf,
            "total_debt": debt,
            "cash_and_equivalents": cash,
            "shares_diluted": shares,
            "book_value": 400.0,
        },
    )
    _price(db, peer, price)
    return peer


# ---------------------------------------------------------------------------
# 1. The formulas
# ---------------------------------------------------------------------------


def test_pe_is_price_over_eps():
    assert derive_multiple("pe", price=20.0, shares=100.0, fundamentals={"eps": 2.0}).value == (
        pytest.approx(10.0)
    )


def test_enterprise_value_is_market_cap_plus_debt_minus_cash():
    """20*100 + 200 - 50 = 2150; EV/FCF = 2150/100 = 21.5x."""
    assert enterprise_value(price=20.0, shares=100.0, total_debt=200.0, cash=50.0) == (
        pytest.approx(2150.0)
    )
    reading = derive_multiple(
        "ev_to_fcf",
        price=20.0,
        shares=100.0,
        fundamentals={"free_cash_flow": 100.0},
        total_debt=200.0,
        cash=50.0,
    )
    assert reading.value == pytest.approx(21.5)


def test_p_to_fcf_and_p_to_book_are_equity_side_and_scale_by_shares():
    """FCF 100 over 100 shares = 1.00/share; 12x ⇒ 12.00. Book 400 ⇒ 4.00/share;
    1.5x ⇒ 6.00."""
    p_fcf = derive_multiple(
        "p_to_fcf", price=20.0, shares=100.0, fundamentals={"free_cash_flow": 100.0}
    )
    assert p_fcf.value == pytest.approx(20.0)
    assert implied_value(
        kind="p_to_fcf",
        peer_multiple=12.0,
        fundamentals={"free_cash_flow": 100.0},
        price=20.0,
        shares=100.0,
    ) == pytest.approx(12.0)
    assert implied_value(
        kind="pb",
        peer_multiple=1.5,
        fundamentals={"book_value": 400.0},
        price=20.0,
        shares=100.0,
    ) == pytest.approx(6.0)


def test_a_negative_denominator_is_not_meaningful_not_cheap():
    """A -20x P/E is the absence of the denominator, not a bargain."""
    reading = derive_multiple("pe", price=20.0, shares=100.0, fundamentals={"eps": -1.0})
    assert reading.value is None
    assert reading.status == "not_meaningful"
    assert "N/D" in reading.reason
    assert "cheap" in reading.reason
    ebitda = derive_multiple(
        "ev_to_ebitda",
        price=20.0,
        shares=100.0,
        fundamentals={"ebitda": -50.0},
        total_debt=200.0,
        cash=50.0,
    )
    assert ebitda.value is None
    assert ebitda.status == "not_meaningful"


def test_a_missing_debt_fact_is_unknown_leverage_not_zero_leverage():
    reading = derive_multiple(
        "ev_to_sales", price=20.0, shares=100.0, fundamentals={"revenue": 1000.0}
    )
    assert reading.value is None
    assert reading.status == "missing_denominator"
    assert "debt" in reading.reason


def test_enterprise_implied_value_subtracts_the_debt(db):
    """The leverage term is where this method usually loses the money.

    EV/EBITDA of 8x on EBITDA 100 gives an enterprise value of 800; the equity
    is 800 - 200 + 50 = 650, i.e. 6.50 per share on 100 shares. Applying the
    8x straight to the equity would say 8.00.
    """
    value = implied_value(
        kind="ev_to_ebitda",
        peer_multiple=8.0,
        fundamentals={"ebitda": 100.0},
        price=20.0,
        shares=100.0,
        total_debt=200.0,
        cash=50.0,
    )
    assert value == pytest.approx(6.50)


def test_enterprise_implied_value_refuses_without_the_debt_term():
    with pytest.raises(RelativeMultipleError) as excinfo:
        implied_value(
            kind="ev_to_sales",
            peer_multiple=2.0,
            fundamentals={"revenue": 1000.0},
            price=20.0,
            shares=100.0,
        )
    assert excinfo.value.missing_input == "net_debt"


def test_the_pure_multiple_is_the_same_arithmetic_as_the_historical_chart(db):
    """Both must produce the same number for the same inputs.

    ``HistoricalValuationService`` computes ``pe = price / eps`` and
    ``EV = price*shares + debt - cash`` per year. The pure primitives used by
    the engine are the same expressions, so a percentile read here and a
    percentile read from the chart are comparable.
    """
    company = _company(db, "SHAREFORM")
    _facts(
        db,
        company,
        {
            "eps": 2.0,
            "free_cash_flow": 100.0,
            "revenue": 1000.0,
            "shares_diluted": 100.0,
            "total_debt": 200.0,
            "cash_and_equivalents": 50.0,
        },
    )
    _price(db, company, 20.0)

    series = HistoricalValuationService().build(
        db, company, years=2, as_of=date(2026, 6, 30)
    )["series"]
    point = next(row for row in series if row["price"] is not None)
    fundamentals = {
        "eps": 2.0,
        "free_cash_flow": 100.0,
        "revenue": 1000.0,
    }
    assert derive_multiple(
        "pe", price=20.0, shares=100.0, fundamentals=fundamentals
    ).value == pytest.approx(float(point["pe"]))
    assert derive_multiple(
        "ev_to_fcf",
        price=20.0,
        shares=100.0,
        fundamentals=fundamentals,
        total_debt=200.0,
        cash=50.0,
    ).value == pytest.approx(float(point["ev_to_fcf"]))
    assert derive_multiple(
        "ev_to_sales",
        price=20.0,
        shares=100.0,
        fundamentals=fundamentals,
        total_debt=200.0,
        cash=50.0,
    ).value == pytest.approx(float(point["ev_to_revenue"]))


# ---------------------------------------------------------------------------
# 2. The statistics
# ---------------------------------------------------------------------------


def test_median_and_percentile_match_hand_computation():
    values = [8.0, 10.0, 12.0, 14.0, 16.0, 18.0]
    assert median(values) == pytest.approx(13.0)
    # p25: position 0.25*5 = 1.25 → 10 + 0.25*(12-10) = 10.5
    assert percentile(values, 0.25) == pytest.approx(10.5)
    # p75: position 0.75*5 = 3.75 → 14 + 0.75*(16-14) = 15.5
    assert percentile(values, 0.75) == pytest.approx(15.5)


def test_empty_samples_are_refused_rather_than_returned_as_zero():
    for call in (
        lambda: median([]),
        lambda: percentile([], 0.5),
        lambda: peer_percentile_of(1.0, []),
    ):
        with pytest.raises(RelativeMultipleError):
            call()


def test_peer_percentile_counts_the_peers_trading_below():
    peers = [
        PeerMultiple(ticker=f"P{index}", kind="pe", value=value, source="s", as_of="d", method="m")
        for index, value in enumerate([8.0, 10.0, 12.0, 14.0])
    ]
    assert peer_percentile_of(9.0, peers) == pytest.approx(0.25)
    assert peer_percentile_of(7.0, peers) == pytest.approx(0.0)
    assert peer_percentile_of(15.0, peers) == pytest.approx(1.0)


def test_a_peer_set_below_five_is_declared_in_the_sample_stats():
    peers = [
        PeerMultiple(ticker=f"P{index}", kind="pe", value=float(value), source="s", as_of="d", method="m")
        for index, value in enumerate((8.0, 10.0, 12.0))
    ]
    stats = describe_peer_sample(peers)
    assert stats["peer_set_size"] == 3
    assert stats["is_small_sample"] is True
    assert stats["is_statistically_meaningful"] is True
    assert stats["median"] == pytest.approx(10.0)
    assert "below the 5" in stats["sample_note"]
    big = describe_peer_sample(
        peers
        + [
            PeerMultiple(
                ticker=f"P{index}", kind="pe", value=14.0 + index, source="s", as_of="d", method="m"
            )
            for index in (0, 1)
        ]
    )
    assert big["peer_set_size"] == 5
    assert big["is_small_sample"] is False
    assert "usable central estimate" in big["sample_note"]


# ---------------------------------------------------------------------------
# 3. The divergence report
# ---------------------------------------------------------------------------


def test_divergence_agrees_below_the_threshold():
    report = divergence_report(intrinsic_value=25.0, relative_value=26.0, current_price=20.0)
    assert report["warning"] is False
    assert report["gap_pct"] == pytest.approx(0.04)
    assert "agree within" in report["text"]


def test_divergence_names_the_contradiction_above_the_threshold():
    report = divergence_report(intrinsic_value=10.0, relative_value=30.0, current_price=20.0)
    assert report["warning"] is True
    assert report["gap_pct"] == pytest.approx(2.0)
    assert "ABOVE" in report["text"]
    assert "cannot both be right" in report["text"] or "Either" in report["text"]
    assert report["price_sided"] == "below_relative"


def test_divergence_declines_to_compare_with_nothing():
    assert divergence_report(intrinsic_value=None, relative_value=30.0)["status"] == (
        "unavailable"
    )
    assert divergence_report(intrinsic_value=0.0, relative_value=30.0)["status"] == (
        "unavailable"
    )


# ---------------------------------------------------------------------------
# 4. Engine end to end
# ---------------------------------------------------------------------------

SUBJECT_FACTS = {
    "eps": 2.0,
    "revenue": 1000.0,
    "free_cash_flow": 100.0,
    "book_value": 400.0,
    "total_debt": 200.0,
    "cash_and_equivalents": 50.0,
    "shares_diluted": 100.0,
}

#: Six peers with P/Es of 8, 10, 12, 14, 16, 18: median 13, p25 10.5, p75 15.5.
PEER_PE = (8.0, 10.0, 12.0, 14.0, 16.0, 18.0)


def _subject(db, ticker="RELSUBJ", **overrides):
    company = _company(db, ticker)
    facts = {**SUBJECT_FACTS, **overrides}
    _facts(db, company, facts)
    _price(db, company, 20.0)
    return company


def _peers(db, count=6):
    for index in range(count):
        pe = PEER_PE[index]
        _peer(db, f"RELP{index}", price=pe * 2.0, eps=2.0)


def _value(db, company, price=20.0):
    engine = RelativeMultiplesEngine()
    return engine.value(engine.build_context(db, company, price))


def test_relative_engine_applies_the_peer_median_to_the_own_eps(db):
    """peers 8/10/12/14/16/18 → median 13, p25 10.5, p75 15.5; own EPS 2.00.

      base = 13   * 2.00 = 26.00
      bear = 10.5 * 2.00 = 21.00
      bull = 15.5 * 2.00 = 31.00
    """
    company = _subject(db)
    _peers(db)
    result = _value(db, company)

    assert result["status"] == "ok"
    assert result["trace"]["headline_multiple"] == "pe"
    assert result["bear_value"] == pytest.approx(21.0)
    assert result["base_value"] == pytest.approx(26.0)
    assert result["bull_value"] == pytest.approx(31.0)
    assert result["bear_value"] <= result["expected_value"] <= result["bull_value"]
    assert result["margin_of_safety"] == pytest.approx((result["expected_value"] - 20.0) / result["expected_value"])
    assert result["trace"]["peer_set_size"] == 6
    assert result["trace"]["peer_set"]["method"] == "PEER_SELECTION_V2"
    assert "peer_set_below_five" not in result["publication_blockers"]
    assert result["trace"]["own_fundamentals"]["eps"] == 2.0
    assert result["relative"]["own_multiple"]["value"] == pytest.approx(10.0)
    assert result["relative"]["own_multiple"]["status"] == "ok"


def test_relative_engine_publishes_every_peer_with_its_source_and_date(db):
    company = _subject(db)
    _peers(db)
    result = _value(db, company)

    block = next(
        entry for entry in result["trace"]["peer_multiples"] if entry["multiple"] == "pe"
    )
    assert block["peer_set_size"] == 6
    assert len(block["peers"]) == 6
    for peer in block["peers"]:
        assert peer["source"] == "financial_facts"
        assert peer["method"] == "derived_from_facts"
        assert peer["as_of"] == PRICE_DAY.isoformat()
    assert "sample_note" in block


def test_relative_engine_uses_a_stored_provider_multiple_with_its_source(db):
    company = _subject(db)
    _peers(db, count=2)
    metric = PROVIDER_MULTIPLE_TEMPLATE.format(kind="pe", ticker="RELP0")
    db.add(
        FinancialFact(
            company_id=company.id,
            metric=metric,
            value=Decimal("21.0"),
            unit="decimal",
            period="2026-01-31",
            fiscal_year=2026,
            fiscal_quarter="FY",
            source_type="FMP",
            is_reported=True,
            confidence=Decimal("0.80"),
        )
    )
    db.commit()
    result = _value(db, company)

    block = next(
        entry for entry in result["trace"]["peer_multiples"] if entry["multiple"] == "pe"
    )
    stored = next(peer for peer in block["peers"] if peer["ticker"] == "RELP0")
    assert stored["value"] == pytest.approx(21.0)
    assert stored["source"] == "FMP"
    assert stored["as_of"] == "2026-01-31"
    assert stored["method"] == "provider_reported"


def test_relative_engine_marks_an_undeclared_source_as_nd(db):
    company = _subject(db)
    _peers(db, count=2)
    metric = PROVIDER_MULTIPLE_TEMPLATE.format(kind="pe", ticker="RELP0")
    db.add(
        FinancialFact(
            company_id=company.id,
            metric=metric,
            value=Decimal("21.0"),
            unit="decimal",
            period="2026-01-31",
            fiscal_year=2026,
            fiscal_quarter="FY",
            source_type="",
            is_reported=False,
            confidence=Decimal("0.50"),
        )
    )
    db.commit()
    result = _value(db, company)

    assert "RELP0" in result["trace"]["peers_without_declared_source"]
    assert "peer_multiple_source_undeclared" in result["publication_blockers"]
    assert result["publishable"] is False


def test_relative_engine_blocks_a_peer_set_below_five(db):
    """Three peers is a sample of convenience; the median is one company's luck
    wearing a statistic's clothes, and the valuation says so."""
    company = _subject(db)
    _peers(db, count=3)
    result = _value(db, company)

    assert result["trace"]["peer_set_size"] == 3
    assert "peer_set_below_five" in result["publication_blockers"]
    assert result["publishable"] is False
    assert result["status"] == "partial"
    assert result["trace"]["peer_set_minimum"] == 5
    assert "pe" in result["trace"]["small_peer_sets"]
    assert result["trace"]["notice"]


def test_relative_engine_refuses_without_a_peer_set(db):
    company = _subject(db)
    result = _value(db, company)

    assert result["status"] == "insufficient_data"
    assert result["missing_inputs"] == ["peer_multiples"]
    assert result["base_value"] is None
    assert result["trace"]["peer_input_contract"]["provider_multiple"] == (
        PROVIDER_MULTIPLE_TEMPLATE.format(kind="<kind>", ticker="<peer ticker>")
    )
    assert "never estimated" in result["trace"]["reason"]


def test_relative_engine_reports_nd_for_its_own_loss_making_p_e(db):
    company = _subject(db, eps=-1.0)
    _peers(db)
    result = _value(db, company)

    # P/E is unusable for the subject, so the headline falls through to the
    # next multiple that has both an own reading and peers.
    assert result["trace"]["headline_multiple"] != "pe"
    pe_screen = result["trace"]["screens"]["pe"]
    assert pe_screen["own"]["value"] is None
    assert pe_screen["own"]["status"] == "not_meaningful"
    assert any("N/D" in caveat for caveat in pe_screen["caveats"])
    assert result["base_value"] is not None


def test_relative_engine_needs_a_real_price(db):
    company = _company(db, "RELNOPRICE")
    _facts(db, company, SUBJECT_FACTS)
    _peers(db)
    result = _value(db, company, price=None)

    assert result["status"] == "insufficient_data"
    assert result["missing_inputs"] == ["current_price"]


def test_relative_engine_needs_shares(db):
    company = _company(db, "RELNOSHARES")
    _facts(db, company, {k: v for k, v in SUBJECT_FACTS.items() if k != "shares_diluted"})
    _peers(db)
    result = _value(db, company)

    assert result["status"] == "insufficient_data"
    assert result["missing_inputs"] == ["shares_diluted"]


def test_relative_engine_refuses_an_adr_without_a_ratio(db):
    company = _subject(db, ticker="RELADR")
    company.factor_tags = ["software", "adr"]
    db.commit()
    _peers(db)
    result = _value(db, company)

    assert result["status"] == "insufficient_data"
    assert result["missing_inputs"] == ["adr_ratio"]


def test_relative_engine_reports_the_divergence_with_the_fcff_dcf(db):
    """A coherent snapshot lets the DCF run on the same context; the gap
    between the two methods is the number a reader most needs."""
    company = _subject(db)
    _facts(db, company, {"revenue_growth": 0.07, "net_debt": 150.0})
    _peers(db)
    result = _value(db, company)

    divergence = result["trace"]["dcf_vs_relative_divergence"]
    assert divergence["status"] == "ok"
    assert divergence["intrinsic_value"] is not None
    assert divergence["gap"] == pytest.approx(
        result["base_value"] - divergence["intrinsic_value"]
    )
    assert divergence["gap_pct"] is not None
    assert divergence["threshold"] == pytest.approx(0.40)
    assert divergence["text"]
    if divergence["warning"]:
        assert "dcf_relative_divergence" in result["publication_blockers"]


def test_relative_engine_declines_to_divergence_without_a_dcf(db):
    """No coherent FCFF snapshot: there is nothing to disagree with, and the
    engine says that instead of implying agreement.

    Since main derives ``net_debt = total_debt - cash`` when both are
    reported, the subject must report neither for the DCF to stay without a
    coherent snapshot."""
    company = _company(db, "RELSUBJ")
    _facts(
        db,
        company,
        {k: v for k, v in SUBJECT_FACTS.items() if k not in ("total_debt", "cash_and_equivalents")},
    )
    _price(db, company, 20.0)
    _peers(db)
    result = _value(db, company)

    divergence = result["trace"]["dcf_vs_relative_divergence"]
    assert divergence["status"] == "unavailable"
    assert divergence["warning"] is None
    assert divergence["reason"]


def test_relative_engine_names_the_peers_it_could_not_use(db):
    company = _subject(db)
    _peers(db, count=2)
    # A peer with no stored price at all.
    orphan = _company(db, "RELORPH")
    _facts(db, orphan, {"eps": 3.0, "shares_diluted": 100.0})
    db.commit()
    result = _value(db, company)

    rejected = result["trace"]["screens"]["pe"]["rejected_peers"]
    reasons = {entry["ticker"]: entry["reason"] for entry in rejected}
    assert "RELORPH" in reasons
    assert "market price" in reasons["RELORPH"]


def test_relative_engine_sensitivity_brackets_the_base_value(db):
    company = _subject(db)
    _peers(db)
    result = _value(db, company)

    values = [row["value_per_share"] for row in result["sensitivity"]["rows"]]
    assert values == [21.0, 26.0, 31.0]
    assert min(values) <= result["base_value"] <= max(values)
    assert all(row["multiple"] == "pe" for row in result["sensitivity"]["rows"])


def test_relative_engine_value_rises_with_the_peer_median(db):
    """The monotonicity property: a richer peer set implies a richer price,
    linearly, through the own EPS."""
    values = []
    for index, pe in enumerate((8.0, 12.0, 16.0, 20.0)):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            company = _subject(session, ticker=f"RELMON{index}")
            for peer_index in range(5):
                _peer(
                    session,
                    f"MONP{index}{peer_index}",
                    price=(pe + peer_index) * 2.0,
                    eps=2.0,
                )
            values.append(_value(session, company)["base_value"])
    assert values == sorted(values)
    # Peers priced at pe, pe+1, ... pe+4 with EPS 2.00: the median is pe+2.
    assert values[0] == pytest.approx((8.0 + 2.0) * 2.0)
    assert values[-1] == pytest.approx((20.0 + 2.0) * 2.0)


def test_relative_engine_declares_every_multiple_kind_it_claims_to_run(db):
    """The contract is six multiples; the trace has to name all six and the
    formulas it used for each, so the screen is auditable kind by kind."""
    company = _subject(db)
    _peers(db)
    result = _value(db, company)

    assert set(result["trace"]["multiple_kinds"]) == set(MULTIPLE_KINDS)
    assert set(result["trace"]["screens"]) == set(MULTIPLE_PREFERENCE)
    for kind, spec in result["trace"]["formulas"].items():
        assert spec["denominator" if "denominator" in spec else "own"]
        assert spec["own"]
        assert spec["implied"]
        assert "historical_valuation_service" in spec["source_of_formula"]
        assert MULTIPLE_KINDS[kind]["denominator"] in spec["implied"]
    assert UNDECLARED_SOURCE == "N/D"


def test_relative_engine_own_multiple_of_an_adr_uses_price_per_ordinary(db):
    """ADR 2:1 (adr:2) a 40 por ADR = 20 por ordinaria; EPS por ordinaria 2.

    PER propio = 20 / 2 = 10 (en main 40 / 2 = 20, el más caro del grupo);
    base = mediana 13 x 2 = 26 por ordinaria, 52 por ADR; margen con 20.
    """
    company = _subject(db, ticker="RELADR2")
    company.factor_tags = ["software", "adr:2"]
    db.commit()
    _peers(db)
    result = _value(db, company, price=40.0)

    assert result["status"] == "ok"
    assert result["relative"]["own_multiple"]["value"] == pytest.approx(10.0)
    assert result["base_value"] == pytest.approx(26.0)
    assert result["listed_share_values"]["base"] == pytest.approx(52.0)
    assert result["margin_of_safety"] == pytest.approx((result["expected_value"] - 20.0) / result["expected_value"])


def test_relative_engine_measures_an_adr_peer_per_ordinary_share(db):
    """Par ADR 2:1 a 36 por ADR con EPS 2 por ordinaria: PER 18 / 2 = 9, no 18.

    Un par marcado «adr» sin ratio no tiene precio comparable: rechazado.
    """
    company = _subject(db)
    _peers(db)
    adr_peer = _peer(db, "RELPADR", price=36.0, eps=2.0)
    adr_peer.factor_tags = ["software", "adr:2"]
    bare_adr = _peer(db, "RELPBARE", price=36.0, eps=2.0)
    bare_adr.factor_tags = ["software", "adr"]
    db.commit()
    result = _value(db, company)

    block = next(entry for entry in result["trace"]["peer_multiples"] if entry["multiple"] == "pe")
    values = {peer["ticker"]: peer["value"] for peer in block["peers"]}
    assert values["RELPADR"] == pytest.approx(9.0)
    assert "RELPBARE" not in values
    rejected = {entry["ticker"] for entry in result["trace"]["screens"]["pe"]["rejected_peers"]}
    assert "RELPBARE" in rejected
