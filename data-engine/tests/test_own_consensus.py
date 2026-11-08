"""Consenso propio por celda: orden fijo de fuentes, puertas de cordura y fórmula visible."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

from app.services.own_consensus import (
    SOURCE_ORDER,
    Actual,
    BaseRate,
    GuidanceRow,
    actuals_from_facts,
    build_cells,
    guidance_beat,
    period_end,
    quarter_of,
    seasonal_shares,
    trend_growth,
)

RATE = BaseRate(p25=0.0, p50=0.04, p75=0.09, n=120, group="prueba", source="SEC companyfacts (prueba)")


def _facts(year_values: Mapping[int, Sequence[float]]) -> list[tuple[str, float, date | None, str | None]]:
    rows: list[tuple[str, float, date | None, str | None]] = []
    ends = ("03-31", "06-30", "09-30", "12-31")
    for year, quarters in year_values.items():
        for i, v in enumerate(quarters[:3]):
            rows.append((f"{year}-{ends[i]}:Q{i + 1}", v, date(year, 3 * i + 4 if i < 3 else 12, 28), f"u{year}q{i}"))
        if len(quarters) == 4:
            rows.append((f"{year}-12-31:FY", sum(quarters), date(year + 1, 2, 20), f"u{year}fy"))
    return rows


# Estacional (T2 fuerte) y creciendo ~5 % al año, como una distribuidora.
SEASONAL = {2022: [100, 160, 130, 90], 2023: [105, 168, 136, 95], 2024: [110, 176, 143, 99],
            2025: [115, 185, 150, 104], 2026: [121, 194, 158]}


def test_periods_follow_the_fiscal_year_end() -> None:
    assert quarter_of(date(2026, 9, 30), 12) == (3, 2026)
    assert quarter_of(date(2026, 9, 30), 6) == (1, 2027)  # ejercicio que cierra en junio
    assert period_end("q4_2026", 12) == date(2026, 12, 31)
    assert period_end("q1_2027", 6) == date(2026, 9, 30)
    assert period_end("fy2027", 6) == date(2027, 6, 30)


def test_q4_is_derived_as_year_minus_nine_months_and_flagged() -> None:
    rows = [r for r in _facts({2025: [115, 185, 150, 104]}) if not r[0].startswith("2025-12-31:Q")]
    acts = actuals_from_facts(rows, metric="revenue")
    assert acts["q4_2025"].derived is True
    assert acts["q4_2025"].value == 104
    assert "año" in acts["q4_2025"].formula and "9M" in acts["q4_2025"].formula
    assert acts["fy2025"].derived is False
    eps = actuals_from_facts([("2025-12-31:FY", 4.0, None, None), ("2025-03-31:Q1", 1.0, None, None),
                              ("2025-06-30:Q2", 1.0, None, None), ("2025-09-30:Q3", 1.0, None, None)], metric="eps")
    assert "q4_2025" not in eps  # el BPA no se suma


def test_guidance_wins_and_the_rest_stay_as_contrast() -> None:
    acts = actuals_from_facts(_facts(SEASONAL), metric="revenue")
    g = GuidanceRow("revenue", "fy2026", 590.0, 600.0, 610.0, date(2026, 10, 28), "https://sec/8k", "we expect")
    cells = build_cells("revenue", acts, today=date(2026, 11, 8), guidance=[g], base_rate=RATE)
    fy = cells["fy2026"]
    assert fy.status == "estimado" and fy.published is not None
    assert fy.published.source == "guia" and fy.published.mid == 600.0
    assert {c.source for c in fy.alternatives} >= {"modelo", "tasa_base"}
    # el 4T sale de la guía anual menos lo ya presentado (único trimestre que falta)
    q4 = cells["q4_2026"]
    assert q4.published is not None and q4.published.source == "guia_trimestre_calculado"
    assert q4.published.mid == 600.0 - (121 + 194 + 158)
    assert "presentado" in q4.published.formula
    assert list(SOURCE_ORDER)[:2] == ["guia", "guia_trimestre_calculado"]


def test_year_below_already_reported_is_rejected() -> None:
    """La guía de un año por debajo de lo ya presentado en sus trimestres no se publica."""
    acts = actuals_from_facts(_facts(SEASONAL), metric="revenue")
    bad = GuidanceRow("revenue", "fy2026", None, 185.0, None, date(2026, 10, 22), "https://sec/8k", "185")
    cells = build_cells("revenue", acts, today=date(2026, 11, 8), guidance=[bad], base_rate=RATE)
    fy = cells["fy2026"]
    assert fy.published is not None and fy.published.source != "guia"
    rejected = [c for c in fy.alternatives if c.source == "guia"]
    assert rejected and rejected[0].rejected and rejected[0].rejected.startswith("año_bajo_lo_contabilizado")
    # ni reparte el 4T: saldría negativo
    q4 = cells["q4_2026"]
    assert q4.published is not None and q4.published.source != "guia_trimestre_calculado" and q4.published.mid > 0


def test_model_trend_is_shrunk_to_base_rate_and_sums_to_year() -> None:
    acts = actuals_from_facts(_facts(SEASONAL), metric="revenue")
    g, n, index = trend_growth([a for a in sorted(acts.values(), key=lambda a: a.end) if a.period.startswith("q")])
    assert n == 12 and g is not None and 0.03 < g < 0.07
    assert index[2] > index[4]  # T2 es el fuerte
    cells = build_cells("revenue", acts, today=date(2026, 11, 8), base_rate=RATE)
    fy, q4 = cells["fy2026"], cells["q4_2026"]
    assert fy.published is not None and fy.published.source == "modelo"
    assert q4.published is not None and q4.published.source == "modelo"
    assert abs(fy.published.mid - (121 + 194 + 158 + q4.published.mid)) < 1e-6
    assert not [f for f in fy.flags if f.startswith("suma_trimestres")]
    low, high = fy.published.low, fy.published.high
    assert low is not None and high is not None
    assert "tasa base" in fy.published.formula and low < fy.published.mid < high
    assert fy.confidence["level"] == "bajo" and "muestra pequeña" in fy.confidence["reason"]


def test_base_rate_against_a_streak_is_rejected() -> None:
    """Cuatro trimestres cayendo: una tasa base que sube no se publica (signo_contra_racha)."""
    falling = {2024: [104, 102, 100, 98], 2025: [100, 98, 96, 94], 2026: [90, 88, 86]}
    acts = actuals_from_facts(_facts(falling), metric="revenue")
    cells = build_cells("revenue", acts, today=date(2026, 11, 8), base_rate=RATE)
    q4 = cells["q4_2026"]
    base = [c for c in q4.alternatives + ([q4.published] if q4.published else []) if c.source == "tasa_base"]
    assert base and base[0].rejected and base[0].rejected.startswith("signo_contra_racha")


def test_stale_period_publishes_nothing() -> None:
    acts = actuals_from_facts(_facts({2024: [110, 176, 143, 99], 2025: [115, 185, 150]}), metric="revenue")
    cells = build_cells("revenue", acts, today=date(2026, 6, 1), base_rate=RATE)
    q4 = cells["q4_2025"]
    assert q4.status == "vencido" and q4.published is None and "periodo_vencido" in q4.flags


def test_guidance_beat_uses_only_guidance_frozen_before_period_end() -> None:
    acts = {f"fy{y}": Actual(f"fy{y}", date(y, 12, 31), v) for y, v in
            {2021: 103.0, 2022: 104.0, 2023: 102.0, 2024: 105.0, 2025: 101.0}.items()}
    hist = [GuidanceRow("revenue", f"fy{y}", None, 100.0, None, date(y, 2, 1)) for y in range(2021, 2026)]
    hist.append(GuidanceRow("revenue", "fy2025", None, 101.0, None, date(2026, 2, 1)))  # tras el cierre: no cuenta
    beat, cases = guidance_beat(hist, acts, 12)
    assert len(cases) == 5 and beat is not None and abs(beat - 0.03) < 1e-9
    beat3, _ = guidance_beat(hist[:3], acts, 12)
    assert beat3 is None  # menos de 4 guías: no hay corrección


def test_analyst_estimate_used_without_guidance_and_cited() -> None:
    acts = actuals_from_facts(_facts(SEASONAL), metric="revenue")
    analyst = [{"metric": "revenue", "year": 2027, "n_firms": 2, "low": 0.00062, "median": 0.00064, "high": 0.00066,
                "firms": [{"firm": "A", "value_millions": 0.00062, "as_of": "2026-10-01", "url": "https://a"}]}]
    cells = build_cells("revenue", acts, today=date(2026, 11, 8), analyst=analyst, base_rate=RATE)
    fy27 = cells["fy2027"]
    assert fy27.published is not None and fy27.published.source == "analista_citado"
    assert abs(fy27.published.mid - 640.0) < 1e-6
    assert fy27.published.citations[0]["url"] == "https://a"


def test_seasonal_shares_split_the_remaining_year() -> None:
    acts = actuals_from_facts(_facts(SEASONAL), metric="revenue")
    shares = seasonal_shares(acts, 2026, [3, 4])
    assert shares is not None and abs(sum(shares.values()) - 1) < 1e-9 and shares[3] > shares[4]


def test_reported_quarter_survives_52_53_week_calendar_boundary() -> None:
    rows = [("2025-12-28:FY", 400.0, None, None),
            ("2026-04-04:Q1", 110.0, date(2026, 5, 1), "https://example.test/q1")]
    actuals = actuals_from_facts(rows, metric="revenue")
    assert "q1_2026" in actuals and "q2_2026" not in actuals
    assert actuals["q1_2026"].end == date(2026, 4, 4)
    assert actuals["q1_2026"].value == 110.0
    assert actuals["q1_2026"].url == "https://example.test/q1"


def test_reported_quarter_keeps_noncalendar_fiscal_year() -> None:
    rows = [("2026-06-27:FY", 400.0, None, None), ("2026-10-03:Q1", 110.0, None, None)]
    actuals = actuals_from_facts(rows, metric="revenue")
    assert "q1_2027" in actuals and "q2_2027" not in actuals


def test_invalid_reported_quarters_are_not_reassigned_from_month() -> None:
    rows = [(f"2026-04-04:{kind}", 110.0, None, None) for kind in ("Q0", "Q5", "Q12")]
    assert actuals_from_facts(rows, metric="revenue") == {}
