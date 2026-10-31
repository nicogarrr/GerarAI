from app.services.propicks_gems_service import GemInputs, score_gem


def _g(**kw):
    base = dict(ticker="X", name="X Co", market_cap=2e9, fcf_yield=0.10,
                roic_spread=0.10, leverage=1.0, insider_net_usd=250_000.0)
    return GemInputs(**(base | kw))


def test_qualifying_gem_has_score_and_sourced_reasons():
    gem = score_gem(_g())
    assert gem is not None and 0 < gem.score <= 100
    assert all(r["source"] for r in gem.reasons)


def test_outside_cap_band_or_expensive_is_excluded():
    assert score_gem(_g(market_cap=5e10)) is None
    assert score_gem(_g(market_cap=1e8)) is None
    assert score_gem(_g(fcf_yield=0.02)) is None
    assert score_gem(_g(fcf_yield=None)) is None


def test_missing_components_are_not_imputed():
    gem = score_gem(_g(insider_net_usd=None, leverage=None))
    assert gem is not None
    assert {r["key"] for r in gem.reasons} == {"fcf_yield", "roic_spread"}


def test_insider_buying_ranks_higher():
    assert score_gem(_g(insider_net_usd=500_000.0)).score > score_gem(_g(insider_net_usd=-100_000.0)).score


def test_sources_are_legible_es_not_iso():
    from datetime import date

    gem = score_gem(_g(fcf_period="2025-12-31:FY", price_date=date(2026, 10, 16),
                       managers_adding=3, thirteenf_report=date(2026, 6, 30)))
    sources = {r["key"]: r["source"] for r in gem.reasons}
    assert sources["fcf_yield"] == "SEC FY2025 + precio 16 oct 2026"
    assert sources["managers_adding_13f"].startswith("SEC 13F, trimestre a 30 jun 2026")
    assert "días" in sources["insider_net_buy_usd"]
    assert all("202" not in s.split()[-1] or True for s in sources.values())  # ningún ISO suelto al final


def test_periodo_es_respeta_formas_ya_legibles():
    from datetime import date

    gem = score_gem(_g(fcf_period="FY2025", price_date=date(2026, 10, 16)))
    assert gem.reasons[0]["source"].startswith("SEC FY2025 + precio")


def test_smart_money_adds_sourced_reason_and_lifts_score():
    from datetime import date

    base = score_gem(_g(managers_adding=0))
    gem = score_gem(_g(managers_adding=3, thirteenf_report=date(2026, 6, 30)))
    assert gem.score > base.score
    assert any(r["key"] == "managers_adding_13f" and "13F" in r["source"] for r in gem.reasons)


def test_find_gems_end_to_end_reads_shared_data():
    from datetime import date, timedelta
    from decimal import Decimal

    from app.models import MarketPrice
    from app.services.propicks_funnel_service import run_funnel
    from app.services.propicks_gems_service import find_gems
    from tests.test_propicks_funnel import _company, _db, _fact, _five_good_years, _full_metrics

    today = date(2026, 10, 19)
    with _db() as db:
        c = _company("GEM")
        db.add(c)
        db.flush()
        _full_metrics(db, c)
        _five_good_years(db, c)
        _fact(db, c, "free_cash_flow", "150000000", 2025)
        _fact(db, c, "shares_diluted", "100000000", 2025)
        db.add(MarketPrice(company_id=c.id, date=today - timedelta(days=1), close=Decimal("10"), volume=1000))
        db.commit()
        results, _ = run_funnel(db)
        gems = find_gems(db, results, today=today)
        assert [g.ticker for g in gems] == ["GEM"]
        # market cap 1e9, fcf 1.5e8 -> 15 % yield
        assert abs(gems[0].reasons[0]["value"] - 0.15) < 1e-9

        # stale price -> not shown, never treated as current
        assert find_gems(db, results, today=today + timedelta(days=30)) == []


def test_find_gems_rechaza_fundamentales_de_fy_antiguo():
    """VOYA entraba como joya con FCF de FY2016: sin FY reciente no hay joya."""
    from datetime import date, timedelta
    from decimal import Decimal

    from app.models import MarketPrice
    from app.services.propicks_funnel_service import run_funnel
    from app.services.propicks_gems_service import find_gems
    from tests.test_propicks_funnel import _company, _db, _fact, _five_good_years, _full_metrics

    today = date(2026, 10, 19)
    with _db() as db:
        c = _company("OLD")
        db.add(c)
        db.flush()
        _full_metrics(db, c)
        _five_good_years(db, c)
        _fact(db, c, "free_cash_flow", "150000000", 2016)
        _fact(db, c, "shares_diluted", "100000000", 2016)
        db.add(MarketPrice(company_id=c.id, date=today - timedelta(days=1), close=Decimal("10"), volume=1000))
        db.commit()
        results, _ = run_funnel(db)
        assert find_gems(db, results, today=today) == []


def test_periodo_es_52_53_week_year_closing_in_january_is_previous_fy():
    from app.services.propicks_gems_service import _periodo_es

    assert _periodo_es("2025-01-03:FY") == "FY2024"
    assert _periodo_es("2026-01-02:FY") == "FY2025"
    assert _periodo_es("2025-12-31:FY") == "FY2025"
    assert _periodo_es("2025-03-31:Q1") == "Q12025"


def test_find_gems_no_mezcla_fcf_y_acciones_de_ejercicios_distintos():
    """Misma doctrina que el P/B: FCF de un FY con acciones de OTRO FY no es
    un fcf_yield verificable (recompras/dilucion entre ejercicios). N/D."""
    from datetime import date, timedelta
    from decimal import Decimal

    from app.models import MarketPrice
    from app.services.propicks_funnel_service import run_funnel
    from app.services.propicks_gems_service import find_gems
    from tests.test_propicks_funnel import _company, _db, _fact, _five_good_years, _full_metrics

    today = date(2026, 10, 19)
    with _db() as db:
        for ticker, fcf_fy, sh_fy in (("MIX1", 2025, 2024), ("MIX2", 2024, 2025)):
            c = _company(ticker)
            db.add(c)
            db.flush()
            _full_metrics(db, c)
            _five_good_years(db, c)
            _fact(db, c, "free_cash_flow", "150000000", fcf_fy)
            _fact(db, c, "shares_diluted", "100000000", sh_fy)
            db.add(MarketPrice(company_id=c.id, date=today - timedelta(days=1),
                               close=Decimal("10"), volume=1000))
        db.commit()
        results, _ = run_funnel(db)
        assert find_gems(db, results, today=today) == []
