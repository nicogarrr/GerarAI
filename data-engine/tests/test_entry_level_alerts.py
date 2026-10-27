from datetime import date

import pytest

from app.services import entry_level_alerts as ela

D = date(2026, 10, 26)


def r(t, lvl, d=D, close=66.13, status="confirmed", model="m-test-1"):
    return ela.LevelReading(t, lvl, d, close, "regla-de-prueba", model, "fuente-de-prueba", d, status)


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
    # Bajar (4 -> 2) no avisa, pero deja el estado al dia.
    ev3, st3 = ela.plan_events(1, [r("UBER", 2)], st2)
    assert ev3 == [] and st3 == {"UBER": 2}


def test_missing_reading_invents_no_state_and_input_state_is_not_mutated():
    before = {"UBER": 3}
    ev, st = ela.plan_events(1, [None], before)
    assert ev == [] and st == before and before == {"UBER": 3}


def test_duplicate_tickers_in_one_batch_alert_once_case_insensitive():
    ev, _ = ela.plan_events(1, [r("uber", 3), r("UBER", 4)], {})
    assert len(ev) == 1 and ev[0].reading.ticker == "UBER" and ev[0].reading.level == 3


def test_fingerprint_depends_on_tenant_ticker_level_and_signal_month_only():
    a = ela.fingerprint(1, r("UBER", 4))
    assert a == ela.fingerprint(1, r("uber", 4, close=1.0))
    assert a != ela.fingerprint(2, r("UBER", 4))
    assert a != ela.fingerprint(1, r("UBER", 3))
    # Mismo mes, otro dia (lectura provisional): misma huella.
    assert a == ela.fingerprint(1, r("UBER", 4, date(2026, 10, 27)))
    assert a != ela.fingerprint(1, r("UBER", 4, date(2026, 11, 2)))


def test_email_is_informative_with_source_and_no_trade_instruction():
    ev, _ = ela.plan_events(1, [r("UBER", 4)], {})
    subject, body = ela.render_email(ev[0])
    assert subject == "UBER entra en nivel 4"
    assert "2026-10-26" in body and "66.13" in body and "regla-de-prueba" in body
    assert "no una recomendacion ni una orden" in body
    ev_none, _ = ela.plan_events(1, [r("X", 2, close=None)], {})
    assert "Cierre: sin dato" in ela.render_email(ev_none[0])[1]


def test_status_must_be_provisional_or_confirmed_and_is_shown():
    with pytest.raises(ValueError):
        ela.plan_events(1, [r("UBER", 3, status="maybe")], {})
    ev, _ = ela.plan_events(1, [r("UBER", 3, status="provisional")], {})
    body = ela.render_email(ev[0])[1]
    assert (
        "Estado: provisional" in body
        and "modelo m-test-1" in body
        and "fuente-de-prueba, hasta 2026-10-26" in body
    )


def test_fingerprint_changes_with_model_version_and_status():
    a = ela.fingerprint(1, r("UBER", 4))
    assert a != ela.fingerprint(1, r("UBER", 4, model="m-test-2"))
    assert a != ela.fingerprint(1, r("UBER", 4, status="provisional"))


def test_leaving_the_zone_and_coming_back_alerts_again():
    _, st = ela.plan_events(1, [r("UBER", 3)], {})
    ev_out, st = ela.plan_events(1, [r("UBER", 1)], st)  # sale de la zona
    assert ev_out == [] and st == {"UBER": 1}
    ev_back, st = ela.plan_events(1, [r("UBER", 3)], st)  # vuelve al MISMO nivel
    assert [(e.reading.level, e.previous_level) for e in ev_back] == [(3, 1)]


def test_only_escalations_at_or_above_min_level_alert():
    assert ela.plan_events(1, [r("UBER", 1)], {})[0] == []  # 1 nunca avisa por defecto
    ev, st = ela.plan_events(1, [r("UBER", 2)], {}, min_level=3)
    assert ev == [] and st == {"UBER": 2}
    ev, st = ela.plan_events(1, [r("UBER", 3)], st, min_level=3)
    assert [(e.reading.level, e.previous_level) for e in ev] == [(3, 2)]
    ev, _ = ela.plan_events(1, [r("UBER", 4)], st, min_level=3)
    assert [(e.reading.level, e.previous_level) for e in ev] == [(4, 3)]
    with pytest.raises(ValueError):
        ela.plan_events(1, [r("UBER", 3)], {}, min_level=0)


def test_flip_flop_inside_a_month_keeps_one_fingerprint_per_level():
    _, st = ela.plan_events(1, [r("UBER", 3)], {})
    _, st = ela.plan_events(1, [r("UBER", 2, date(2026, 10, 27))], st)
    ev, _ = ela.plan_events(1, [r("UBER", 3, date(2026, 10, 28))], st)
    # Vuelve a avisar (subida), pero con la misma huella del mes: la capa de envio deduplica.
    assert ev[0].fingerprint == ela.fingerprint(1, r("UBER", 3))
