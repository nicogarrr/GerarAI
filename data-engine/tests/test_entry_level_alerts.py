from datetime import date

import pytest

from app.services import entry_level_alerts as ela

D = date(2026, 10, 26)


def r(t, lvl, d=D, close=66.13):
    return ela.LevelReading(t, lvl, d, close, "regla-de-prueba")


def test_no_provider_means_no_alerts_never_a_default_rule():
    with pytest.raises(ela.LevelRuleNotConfigured):
        ela.collect_readings(None, ["UBER"])


@pytest.mark.parametrize("bad", [0, 5, -1, 2.0, True, "3", None])
def test_levels_outside_1_to_4_are_rejected_not_clamped(bad):
    with pytest.raises(ValueError):
        ela.validate_level(bad)
    with pytest.raises(ValueError):
        ela.plan_events(1, [r("UBER", bad)], {})  # type: ignore[arg-type]


def test_first_reading_and_change_notify_and_same_level_is_idempotent():
    ev, st = ela.plan_events(1, [r("UBER", 4)], {})
    assert [(e.reading.ticker, e.reading.level, e.previous_level) for e in ev] == [("UBER", 4, None)]
    assert st == {"UBER": 4}
    ev2, st2 = ela.plan_events(1, [r("UBER", 4, date(2026, 10, 27))], st)
    assert ev2 == [] and st2 == st
    ev3, st3 = ela.plan_events(1, [r("UBER", 2)], st2)
    assert ev3[0].previous_level == 4 and st3 == {"UBER": 2}


def test_missing_reading_invents_no_state_and_input_state_is_not_mutated():
    before = {"UBER": 3}
    ev, st = ela.plan_events(1, [None], before)
    assert ev == [] and st == before and before == {"UBER": 3}


def test_duplicate_tickers_in_one_batch_alert_once_case_insensitive():
    ev, _ = ela.plan_events(1, [r("uber", 3), r("UBER", 4)], {})
    assert len(ev) == 1 and ev[0].reading.ticker == "UBER" and ev[0].reading.level == 3


def test_fingerprint_depends_on_tenant_ticker_level_and_signal_date_only():
    a = ela.fingerprint(1, r("UBER", 4))
    assert a == ela.fingerprint(1, r("uber", 4, close=1.0))
    assert a != ela.fingerprint(2, r("UBER", 4))
    assert a != ela.fingerprint(1, r("UBER", 3))
    assert a != ela.fingerprint(1, r("UBER", 4, date(2026, 10, 27)))


def test_email_is_informative_with_source_and_no_trade_instruction():
    ev, _ = ela.plan_events(1, [r("UBER", 4)], {})
    subject, body = ela.render_email(ev[0])
    assert subject == "UBER entra en nivel 4"
    assert "2026-10-26" in body and "66.13" in body and "regla-de-prueba" in body
    assert "no una recomendacion ni una orden" in body
    ev_none, _ = ela.plan_events(1, [ela.LevelReading("X", 1, D, None, "s")], {})
    assert "Cierre: sin dato" in ela.render_email(ev_none[0])[1]
