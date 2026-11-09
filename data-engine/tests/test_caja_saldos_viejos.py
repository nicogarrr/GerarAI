"""caja-deuda-v1: saldos de reserva (deuda a largo, minoritarios) con la fecha del balance de la caja."""
from app.valuation import balance_bridge as bb


def c(metric, value_m, period, source="SEC"):
    return {"metric": metric, "value": value_m * 1e6, "period": period, "source_type": source}


def test_deuda_a_largo_de_otro_cierre_no_vale():
    point = {"cash_and_equivalents": c("cash_and_equivalents", 17853, "2026-09-30:Q3"),
             "long_term_debt": c("long_term_debt", 598, "2014-09-30:Q3")}
    assert not bb.same_close(point, "long_term_debt")
    point["long_term_debt"] = c("long_term_debt", 598, "2026-09-30:Q3")
    assert bb.same_close(point, "long_term_debt")


def test_same_close_sin_dato():
    assert not bb.same_close({"cash_and_equivalents": c("cash_and_equivalents", 1, "2026-09-30:Q3")}, "long_term_debt")


def test_minoritarios_viejos_avisan_con_fechas():
    point = {"cash_and_equivalents": c("cash_and_equivalents", 16242, "2025-12-31:FY"),
             "minority_interest": c("minority_interest", 51628, "2017-12-31:FY")}
    note = bb.stale_note(point, "minority_interest", "minoritarios")
    assert note and "2017-12-31" in note and "2025-12-31" in note
    point["minority_interest"] = c("minority_interest", 51628, "2025-12-31:FY")
    assert bb.stale_note(point, "minority_interest", "minoritarios") is None
