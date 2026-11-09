"""Bordes de app/services/chat_company_en.py (zona levantada por Nico 9-nov-2026 18:43).

La suite existente (test_chat_english_sections) cubre secciones concretas; aquí se cubren los
helpers de formato y las ramas de _lead_en/natural_company_answer_en/thesis_section_text_en, todo
puro (sin BD): los "modelos" son SimpleNamespace de solo lectura de atributos, sin tenant_id ni
company_id (regla gerarai-orm-fake-simplenamespace).
"""

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from app.services import chat_company_en as ce

CO = SimpleNamespace(ticker="ASTS", exchange="NASDAQ")


def _fact(metric, value, unit="USD", period="2025-12-31:FY", fy=2025, fq="FY", source="sec"):
    return SimpleNamespace(
        metric=metric,
        value=value,
        unit=unit,
        period=period,
        fiscal_year=fy,
        fiscal_quarter=fq,
        source_type=source,
    )


# --- formato -----------------------------------------------------------------


def test_to_float_y_number():
    assert ce._to_float(None) is None
    assert ce._to_float(Decimal("1.5")) == 1.5 and ce._to_float(3) == 3.0
    assert ce._number(1234567.89) == "1,234,567.89"
    assert ce._number(4.40) == "4.4" and ce._number(300.0) == "300"


def test_fmt_value_en_ramas():
    assert ce.fmt_value_en(None, "USD") == "no data"
    assert ce.fmt_value_en(-71.5e6, "USD") == "-71.5 million USD"
    assert ce.fmt_value_en(1.14e9, "USD") == "1.14 billion USD"
    assert ce.fmt_value_en(2500.0, "USD") == "2.5 thousand USD"
    assert ce.fmt_value_en(300.0, "shares") == "300 shares"
    assert ce.fmt_value_en(42.0, None) == "42"
    assert ce.fmt_value_en(42.0, "decimal") == "42"


def test_fmt_period_en_ramas():
    assert ce.fmt_period_en("2025-12-31:FY") == "FY 2025"
    assert ce.fmt_period_en("2025-09-30:Q3") == "Q3 2025"
    assert ce.fmt_period_en("raro", 2025, "Q2") == "Q2 2025"
    assert ce.fmt_period_en("raro", 2025, "FY") == "FY 2025"
    assert ce.fmt_period_en("raro", 2025, None) == "FY 2025"
    assert ce.fmt_period_en("2025:FY") == "2025:FY"  # no casa el patrón: se devuelve tal cual
    assert ce.fmt_period_en(None) == "undated period"


def test_fmt_date_en_ramas():
    assert ce.fmt_date_en("2026-10-16") == "Oct 16, 2026"
    assert ce.fmt_date_en("2026-01-02T10:00:00") == "Jan 2, 2026"
    assert ce.fmt_date_en("2026-13-01") == "2026-13-01"  # mes inválido: literal
    assert ce.fmt_date_en("no-fecha") == "no-fecha"
    assert ce.fmt_date_en(None) == "undated"
    assert ce.fmt_date_en("") == "undated"


def test_price_display_en_ramas():
    assert ce.price_display_en(Decimal("150.00"), "USD") == "$150.00"
    assert ce.price_display_en(Decimal("0.0123"), "USD") == "$0.01230"  # dígitos adaptados < 1
    assert ce.price_display_en(Decimal("10"), "EUR") == "10.00 €"
    assert ce.price_display_en(Decimal("10"), "JPY") == "10.00 JPY"
    assert ce.price_display_en(Decimal("10"), None) == "10.00 (currency not declared)"
    assert ce.price_display_en(Decimal("10"), "  ") == "10.00 (currency not declared)"


def test_price_line_en_y_primary_sources_hint():
    line = ce.price_line_en("ASTS", Decimal("5.5"), "USD", adjusted=True, day="2026-10-16", source="tiingo")
    assert line == "ASTS trades at $5.50 (adjusted close on Oct 16, 2026, source tiingo)."
    spot = ce.price_line_en("ASTS", Decimal("5.5"), "USD", adjusted=False, day="2026-10-16", source="tiingo")
    assert "(spot on Oct 16, 2026" in spot
    assert ce.primary_sources_hint_en(CO, sec=True) == "ingest its primary sources (SEC/FMP)"
    assert "NASDAQ" in ce.primary_sources_hint_en(CO, sec=False)
    assert "its market" in ce.primary_sources_hint_en(SimpleNamespace(ticker="X", exchange=" "), sec=False)


def test_question_metrics_en_keywords():
    assert ce.question_metrics_en("What is the revenue?") == {"revenue"}
    assert ce.question_metrics_en("net income and earnings") == {"net_income"}
    assert ce.question_metrics_en("free cash flow?") == {"free_cash_flow", "operating_cash_flow"}
    assert ce.question_metrics_en("how much debt") == {"net_debt", "total_debt"}
    assert ce.question_metrics_en("cash position") == {"cash_and_equivalents"}
    assert ce.question_metrics_en("cash flow") != {"cash_and_equivalents"}  # \bcash\b(?! flow)
    assert ce.question_metrics_en("shares outstanding") == {"shares_diluted"}
    assert ce.question_metrics_en("market cap?") == {"market_cap"}
    assert ce.question_metrics_en("hola") == set()
    assert ce.question_metrics_en("") == set()


def test_fact_text_y_short():
    f = _fact("revenue", Decimal("1.5e6"))
    assert ce._fact_text(f) == "1.5 million USD (FY 2025, sec)"
    assert ce._fact_text(_fact("revenue", Decimal("1"), source=None)).endswith("stored source)")
    assert ce._short("uno dos tres", 50) == "uno dos tres"
    recortado = ce._short("palabra " * 50, 40)
    assert recortado.endswith("…") and "palabra" in recortado


def test_news_headline_line_en_ramas():
    n1 = SimpleNamespace(title="  Deal   signed  ", date=datetime(2026, 10, 16))
    n2 = SimpleNamespace(title="Deal signed", date=datetime(2026, 10, 15))  # duplicado tras compactar
    n3 = SimpleNamespace(title="Other headline", date=None)  # sin fecha: fuera si hay fechadas
    n4 = SimpleNamespace(title="", date=datetime(2026, 10, 14))  # sin título: fuera
    line = ce.news_headline_line_en([n1, n2, n3, n4])
    assert line == "Latest saved news: 'Deal signed' (Oct 16, 2026)."
    # Sin ninguna fechada, entran las que haya (sin coletilla de fecha):
    assert ce.news_headline_line_en([n3]) == "Latest saved news: 'Other headline'."
    assert ce.news_headline_line_en([SimpleNamespace(title=" ", date=None)]) is None
    # Máximo 2 titulares (break):
    tres = [SimpleNamespace(title=f"T{i}", date=datetime(2026, 10, 16 - i)) for i in range(3)]
    assert ce.news_headline_line_en(tres) == "Latest saved news: 'T0' (Oct 16, 2026); 'T1' (Oct 15, 2026)."


# --- _lead_en ------------------------------------------------------------------


def _thesis(**kw):
    base = dict(
        status="published",
        rating="buy",
        version=3,
        executive_summary="Tesis larga. " * 40,
        created_at=datetime(2026, 11, 1),
        valuation_risk_score=35,
        id=9,
        expected_value=10.0,
        current_price=5.0,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _lead(question, **kw):
    args = dict(
        ticker="ASTS",
        facts=[],
        thesis=None,
        thesis_line=None,
        news=[],
        claims=[],
        contradiction_claims=[],
        price_line=None,
        focus_metrics=set(),
        thesis_withheld=None,
    )
    args.update(kw)
    return ce._lead_en(question, **args)


def test_lead_vacia_y_riesgos():
    assert _lead("   ") is None
    claims = [SimpleNamespace(status="unverified"), SimpleNamespace(status="verified")]
    out = _lead(
        "what are the risks?",
        claims=claims,
        contradiction_claims=[claims[0]],
        thesis=_thesis(),
        thesis_line="t",
    )
    assert "1 contradicted or outdated claims" in out and "1 claims pending verification" in out
    assert "valuation risk 35/100 in thesis v3" in out
    assert _lead("risks?", claims=[], contradiction_claims=[]) == "I have no documented risks saved for ASTS."
    # tesis retenida no muestra el score:
    out = _lead("risks", thesis=_thesis(), thesis_withheld="archived")
    assert "valuation risk" not in out


def test_lead_tesis_ramas():
    assert _lead("tell me the thesis", thesis=None) == "I don't have any saved thesis for ASTS."
    assert _lead("valuation?", thesis=_thesis(), thesis_line="L", thesis_withheld="arch") == "L"
    out = _lead("fair value?", thesis=_thesis(status="draft"), thesis_line="L")
    assert out.startswith("L") and "It's a draft" in out and "Summary:" in out
    out = _lead("rating?", thesis=_thesis(executive_summary=""), thesis_line="L")
    assert "It's a draft" not in out and "Summary:" not in out  # publicada y sin resumen


def test_lead_focus_metrics():
    f = _fact("revenue", Decimal("1.5e6"))
    out = _lead("revenue?", facts=[f], focus_metrics={"revenue"})
    assert out == "ASTS revenue: 1.5 million USD (FY 2025, sec)."
    out = _lead("revenue?", facts=[], focus_metrics={"revenue", "net_income"})
    assert out == "I don't have that figure saved for ASTS (net income, revenue)."


def test_lead_precio_noticias_y_none():
    assert _lead("price?", price_line="P") == "P"
    assert _lead("price?") is None  # sin price_line no hay respuesta de precio
    assert _lead("any news?", news=[]) == "I have no saved news for ASTS."
    n = SimpleNamespace(title="Deal", date=datetime(2026, 10, 16))
    assert _lead("latest headlines", news=[n]) == "Latest saved news: 'Deal' (Oct 16, 2026)."
    # Hay noticias pero ninguna con título usable: no hay línea y se devuelve None:
    assert _lead("news?", news=[SimpleNamespace(title=" ", date=None)]) is None
    assert _lead("hola") is None


# --- natural_company_answer_en --------------------------------------------------


def _answer(question="", **kw):
    args = dict(
        company=CO,
        facts=[],
        thesis=None,
        news=[],
        missing_metrics=[],
        claims=[],
        contradiction_claims=[],
        price_line=None,
        memory_notes=None,
        market_cap_fact=None,
        question=question,
        thesis_withheld=None,
        sec=True,
    )
    args.update(kw)
    return ce.natural_company_answer_en(**args)


def test_answer_precio_market_cap_y_hechos():
    facts = [_fact("revenue", Decimal("1e6")), _fact("net_income", Decimal("2e5"))]
    out = _answer(
        "revenue?", price_line="P", market_cap_fact=_fact("market_cap", Decimal("9e8")), facts=facts
    )
    assert out.startswith("ASTS revenue:")  # lead primero
    assert "P" in out and "Market cap: 900 million USD (FY 2025, sec)." in out
    assert "Stored data: revenue" in out
    # con foco, la métrica preguntada va primero en Stored data:
    assert out.index("revenue 1 million USD") < out.index("net income")


def test_answer_sin_hechos_hint_sec_y_no_sec():
    out = _answer("hola", sec=True)
    assert "ingest its primary sources (SEC/FMP)" in out
    out = _answer("hola", sec=False)
    assert "FMP and the company's own annual reports" in out


def test_answer_tesis_retenida_publicada_y_notas():
    t = _thesis(created_at=datetime(2026, 11, 1))
    out = _answer("hola", thesis=t, thesis_withheld="failed audit")
    assert "Archived thesis v3 (2026-11-01):" in out
    out = _answer("hola", thesis=_thesis(status="draft", rating="hold"))
    assert "I have thesis v3 saved (status draft, rating hold)." in out
    out = _answer("hola", thesis=_thesis(status="weird", rating="weird"))
    assert "I have thesis v3 saved." in out  # status/rating desconocidos: sin detalles
    notas = ["Nota   uno", "Nota uno", "Nota dos"]  # la 2ª es duplicada tras compactar
    out = _answer("hola", memory_notes=notas)
    assert out.count("From your saved notes:") == 2


def test_answer_claims_missing_y_comparativa():
    out = _answer("hola", contradiction_claims=[SimpleNamespace(status="contradicted")])
    assert "1 contradicted or outdated claims worth reviewing" in out
    out = _answer("hola", claims=[SimpleNamespace(status="unverified")])
    assert "claims pending verification" in out
    out = _answer("hola", missing_metrics=["revenue", "unknown_metric"])
    assert "Still missing stored data for: revenue, unknown_metric." in out
    out = _answer("price?", price_line="P", margin_line="M")
    assert out.startswith("M")  # margin_line va primero
    out = _answer("compare ASTS vs RKLB", price_line="P", margin_line="M")
    assert out.startswith(
        "I can't compare two companies in one answer"
    )  # sin lead, la comparativa va primera
    out_sin_lead = _answer("compare ASTS vs RKLB")
    assert out_sin_lead.split("\n\n")[0].startswith("I can't compare")  # sin lead va el primero


def test_answer_lead_no_duplica_partes():
    n = SimpleNamespace(title="Deal", date=datetime(2026, 10, 16))
    out = _answer("any news?", news=[n])
    assert out.count("Latest saved news:") == 1  # el lead sustituye, no duplica


# --- thesis_section_text_en -----------------------------------------------------


def test_thesis_section_text_en_ramas():
    assert ce.thesis_section_text_en("ASTS", None, None) == "No thesis stored yet for ASTS."
    t = _thesis()
    out = ce.thesis_section_text_en("ASTS", t, "stale")
    assert out.startswith("Archived thesis v3 (2026-11-01):") and "[thesis_version:9]" in out
    out = ce.thesis_section_text_en("ASTS", t, None)
    assert "Thesis ASTS v3: `published` with rating `buy`" in out
    assert "Expected value=10.0 vs current price=5.0" in out and "[thesis_version:9]" in out
    sin_fecha = _thesis(created_at=None)
    assert "unverified date" in ce.thesis_section_text_en("ASTS", sin_fecha, "stale")
