"""Prensa como complemento del panel de precios objetivo (press=1).

Caso real: Cantor Fitzgerald reiteró Overweight y 90 $ sobre ASTS el
2026-11-09; Yahoo seguía mostrando la nota de Cantor del 11 de agosto. La
pasada de prensa (RSS de Bing News + lectura del artículo respetando
robots.txt, o el fragmento literal del RSS si el medio bloquea) aporta la
fila del día con medio, enlace y fecha real de publicación.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, date, datetime, timedelta

from app.services import analyst_targets_press as press
from app.services import analyst_targets_service as svc

TODAY = date(2026, 11, 9)

CANTOR_SNIPPET = (
    "Cantor Fitzgerald Reiterates Overweight Rating on AST Spacemobile (ASTS). "
    "Cantor Fitzgerald analyst Colin Canfield reiterated an Overweight rating and "
    "$90.00 price target on AST Spacemobile (NASDAQ: ASTS) on Monday."
)

PIPER_SNIPPET = (
    "AST Spacemobile (ASTS) PT Lowered to $54 at Piper Sandler. "
    "Piper Sandler lowered its price target on AST Spacemobile (NASDAQ: ASTS) "
    "to $54.00 from $98.00 while maintaining a Neutral rating."
)


def _rss(*entries: tuple[str, str, str, str]) -> str:
    items = "".join(
        f"<item><title>{title}</title><link>https://www.bing.com/news/click?url={url}</link>"
        f"<description>{desc}</description><pubDate>{pub}</pubDate></item>"
        for url, title, desc, pub in entries
    )
    return f"<rss><channel>{items}</channel></rss>"


def _fetch_map(pages: dict[str, str], rss: str):
    async def fetch(url: str):
        if "bing.com/news" in url:
            return rss.encode(), None, url
        if url in pages:
            return pages[url].encode(), None, url
        raise ConnectionError("medio bloqueado")

    return fetch


# -- rss_items ----------------------------------------------------------------


def test_rss_items_extrae_enlace_titulo_fragmento_y_fecha() -> None:
    xml = _rss(("https://www.streetinsider.com/x", "Título", "Descripción <b>con html</b>",
                "Mon, 09 Nov 2026 11:39:00 GMT"))
    [item] = press.rss_items(xml)
    assert item.url == "https://www.streetinsider.com/x"
    assert item.title == "Título"
    assert item.description == "Descripción con html"
    assert item.published == date(2026, 11, 9)


def test_rss_items_descarta_enlaces_no_https() -> None:
    xml = _rss(("http://www.streetinsider.com/x", "T", "D", "Mon, 09 Nov 2026 11:39:00 GMT"))
    assert press.rss_items(xml) == []


# -- extract_targets ----------------------------------------------------------


def test_extrae_reiteracion_de_cantor_con_firma_objetivo_recomendacion_y_accion() -> None:
    rows = press.extract_targets(
        CANTOR_SNIPPET, symbol="ASTS", published=TODAY,
        url="https://www.streetinsider.com/x", full_text=False)
    assert len(rows) == 1
    row = rows[0]
    assert row.firm == "Cantor Fitzgerald"
    assert row.price_target == 90.0
    assert row.rating == "Overweight"
    assert row.action == "reiterate"
    assert row.outlet == "StreetInsider"
    assert row.url == "https://www.streetinsider.com/x"
    assert row.date == TODAY


def test_extrae_recorte_con_objetivo_anterior() -> None:
    rows = press.extract_targets(
        PIPER_SNIPPET, symbol="ASTS", published=TODAY,
        url="https://au.investing.com/news/x", full_text=False)
    assert len(rows) == 1
    row = rows[0]
    assert row.firm == "Piper Sandler"
    assert row.price_target == 54.0
    assert row.prior_target == 98.0
    assert row.outlet == "Investing.com"


def test_sin_ticker_en_el_texto_no_hay_fila() -> None:
    rows = press.extract_targets(
        "Cantor Fitzgerald reiterated an Overweight rating and $90.00 price target on the stock.",
        symbol="ASTS", published=TODAY, url="https://www.streetinsider.com/x", full_text=False)
    assert rows == []


def test_contraejemplo_del_auditor_objetivo_de_otra_empresa_en_articulo_que_menciona_al_ticker() -> None:
    # El artículo menciona ASTS de pasada; el objetivo es de AAPL. Antes de la
    # guardia esto producía una fila Cantor 250 para ASTS: contaminación cruzada.
    rows = press.extract_targets(
        "ASTS is in the news. Cantor Fitzgerald reiterated a $250 price target on AAPL.",
        symbol="ASTS", published=TODAY, url="https://www.streetinsider.com/x", full_text=True)
    assert rows == []


def test_ticker_en_otra_frase_no_vincula_el_objetivo() -> None:
    rows = press.extract_targets(
        "AST SpaceMobile (ASTS) fell on Monday. Cantor Fitzgerald reiterated a $90.00 price target.",
        symbol="ASTS", published=TODAY, url="https://www.streetinsider.com/x", full_text=True)
    assert rows == []


def test_otro_ticker_en_la_misma_frase_descarta_la_fila() -> None:
    rows = press.extract_targets(
        "Roth Capital kept its $108.00 price target on ASTS while cutting AAPL to $190.00.",
        symbol="ASTS", published=TODAY, url="https://www.streetinsider.com/x", full_text=True)
    assert rows == []


def test_siglas_del_nombre_de_la_firma_no_son_tickers_ajenos() -> None:
    rows = press.extract_targets(
        "UBS raised its price target on ASTS to $50.00 from $45.00.",
        symbol="ASTS", published=TODAY, url="https://www.benzinga.com/x", full_text=False)
    assert len(rows) == 1 and rows[0].firm == "UBS" and rows[0].price_target == 50.0


def test_roth_a_secas_se_normaliza_a_roth_capital_en_el_panel() -> None:
    rows = press.extract_targets(
        "Roth reiterates $108 price target on AST SpaceMobile (ASTS) and maintains Buy rating.",
        symbol="ASTS", published=TODAY, url="https://www.benzinga.com/x", full_text=False)
    assert len(rows) == 1
    assert rows[0].firm == "Roth Capital" and rows[0].price_target == 108.0
    assert rows[0].rating == "Buy"


def test_sin_firma_atribuible_no_hay_fila() -> None:
    rows = press.extract_targets(
        "An analyst reiterated a Buy rating and $90.00 price target on ASTS.",
        symbol="ASTS", published=TODAY, url="https://www.streetinsider.com/x", full_text=False)
    assert rows == []


def test_varias_firmas_en_un_articulo() -> None:
    text = (
        "AST Spacemobile (ASTS) saw mixed calls on Monday. "
        "Cantor Fitzgerald reiterated an Overweight rating and $90.00 price target on ASTS. "
        "Deutsche Bank raised its price target on ASTS to $93.00 from $81.00 with a Buy rating."
    )
    rows = press.extract_targets(text, symbol="ASTS", published=TODAY,
                                 url="https://www.benzinga.com/x", full_text=True)
    by_firm = {row.firm: row for row in rows}
    assert by_firm["Cantor Fitzgerald"].price_target == 90.0
    assert by_firm["Deutsche Bank"].price_target == 93.0
    assert by_firm["Deutsche Bank"].prior_target == 81.0
    assert by_firm["Deutsche Bank"].action == "reiterate" or by_firm["Deutsche Bank"].action is None


# -- divisa fail-closed (auditor) ---------------------------------------------


def test_marca_de_divisa_no_reconocida_descarta_la_fila() -> None:
    rows = press.extract_targets(
        "Cantor Fitzgerald reiterated a XYZ$90.00 price target on ASTS.",
        symbol="ASTS", published=TODAY, url="https://www.streetinsider.com/x", full_text=False,
        today=TODAY)
    assert rows == []


def test_divisa_mencionada_distinta_de_la_declarada_descarta_al_fusionar() -> None:
    rows = press.extract_targets(
        "Cantor Fitzgerald reiterated a $90.00 price target on ASTS (CAD).",
        symbol="ASTS", published=TODAY, url="https://www.streetinsider.com/x", full_text=False,
        today=TODAY)
    assert len(rows) == 1 and rows[0].currency_mentions == ("CAD",)
    assert not press.currency_matches(rows[0].currency_mark, "USD", rows[0].currency_mentions)
    assert press.currency_matches(rows[0].currency_mark, "CAD", rows[0].currency_mentions)
    # Y al fusionar, la fila no entra en un listado declarado en USD.
    merged = svc.merge_press_rows([_yahoo_row("TD Cowen", date(2026, 10, 1), 80.0)], rows,
                                  reference_price=50.0, currency="USD")
    assert len(merged) == 1 and merged[0].source == svc.SOURCE


# -- fecha de la nota respaldada por el texto (auditor) -----------------------


def test_pubdate_futura_descarta_el_item() -> None:
    rss = _rss(("https://www.streetinsider.com/x", "Cantor keeps PT on ASTS",
                "Cantor Fitzgerald keeps $90.00 price target on ASTS", "Tue, 10 Nov 2026 11:39:00 GMT"))
    assert asyncio.run(press.fetch_press_targets("ASTS", today=TODAY, fetch=_fetch_map({}, rss))) == []


def test_retrospectiva_usa_la_fecha_que_respalda_el_texto() -> None:
    rows = press.extract_targets(
        "On November 3, Cantor Fitzgerald raised its price target on ASTS to $90.00 from $80.00.",
        symbol="ASTS", published=TODAY, url="https://www.benzinga.com/x", full_text=True, today=TODAY)
    assert len(rows) == 1 and rows[0].date == date(2026, 11, 3)


def test_dia_de_semana_ancla_a_la_semana_de_publicacion() -> None:
    rows = press.extract_targets(
        "Cantor Fitzgerald reiterated a $90.00 price target on ASTS on Monday.",
        symbol="ASTS", published=date(2026, 11, 11), url="https://www.benzinga.com/x",
        full_text=True, today=date(2026, 11, 11))
    assert len(rows) == 1 and rows[0].date == date(2026, 11, 9)


def test_ancla_en_futuro_descarta_la_fila() -> None:
    rows = press.extract_targets(
        "Cantor Fitzgerald reiterated a $90.00 price target on ASTS on Friday.",
        symbol="ASTS", published=TODAY, url="https://www.benzinga.com/x",
        full_text=True, today=TODAY)
    # Lunes 9 nov: «on Friday» apunta al 6 nov (pasado), válido; al futuro no.
    assert len(rows) == 1 and rows[0].date == date(2026, 11, 6)
    rows = press.extract_targets(
        "On November 13, Cantor Fitzgerald will review its $90.00 price target on ASTS.",
        symbol="ASTS", published=TODAY, url="https://www.benzinga.com/x",
        full_text=True, today=TODAY)
    assert rows == []


# -- whitelist de medios (auditor) --------------------------------------------


def test_medio_fuera_de_la_whitelist_no_produce_fila() -> None:
    rss = _rss(("https://blog-financiero.example.com/x", "Cantor keeps PT on ASTS",
                "Cantor Fitzgerald keeps $90.00 price target on ASTS", "Mon, 09 Nov 2026 11:39:00 GMT"))
    assert asyncio.run(press.fetch_press_targets("ASTS", today=TODAY, fetch=_fetch_map({}, rss))) == []


def test_subdominios_de_medios_confiados_entran() -> None:
    assert press._trusted("https://au.investing.com/news/x")
    assert press._trusted("https://www.streetinsider.com/x")
    assert press._trusted("https://finance.yahoo.com/news/x")
    assert not press._trusted("https://stocktwits.com/x")
    assert not press._trusted("https://investing.com.evil.example/x")


# -- currency_matches ---------------------------------------------------------


def test_divisa_dolar_solo_cuadra_con_listado_en_usd() -> None:
    assert press.currency_matches(None, "USD")
    assert not press.currency_matches(None, "CAD")
    assert not press.currency_matches(None, None)
    assert press.currency_matches("USD", "USD")
    assert not press.currency_matches("CAD", "USD")


# -- fetch_press_targets ------------------------------------------------------


def test_fragmento_del_rss_cuando_el_medio_bloquea_la_lectura() -> None:
    rss = _rss(("https://www.streetinsider.com/x", CANTOR_SNIPPET.split(". ")[0],
                CANTOR_SNIPPET.split(". ", 1)[1], "Mon, 09 Nov 2026 11:39:00 GMT"))
    rows = asyncio.run(press.fetch_press_targets(
        "ASTS", today=TODAY, fetch=_fetch_map({}, rss)))
    assert len(rows) == 1
    row = rows[0]
    assert row.firm == "Cantor Fitzgerald" and row.price_target == 90.0
    assert row.full_text is False


def test_articulo_leido_gana_al_fragmento_a_igual_fecha() -> None:
    article = "<html><body><article><p>" + CANTOR_SNIPPET + "</p>" + (
        "<p>Relleno del artículo con suficiente texto para superar el mínimo de "
        "caracteres legibles que exige la puerta de muro de pago del panel.</p>" * 4
    ) + "</article></body></html>"
    rss = _rss(("https://www.streetinsider.com/x", "Cantor keeps PT on ASTS",
                "Cantor Fitzgerald keeps $90.00 price target on ASTS", "Mon, 09 Nov 2026 11:39:00 GMT"))
    rows = asyncio.run(press.fetch_press_targets(
        "ASTS", today=TODAY, fetch=_fetch_map({"https://www.streetinsider.com/x": article}, rss)))
    assert len(rows) == 1
    assert rows[0].full_text is True
    assert rows[0].action == "reiterate"


def test_notas_antiguas_fuera_de_la_ventana() -> None:
    rss = _rss(("https://www.streetinsider.com/x", "Cantor keeps $90.00 price target on ASTS",
                "Cantor Fitzgerald kept a $90.00 price target on ASTS.", "Sun, 01 Mar 2026 11:39:00 GMT"))
    assert asyncio.run(press.fetch_press_targets("ASTS", today=TODAY, fetch=_fetch_map({}, rss))) == []


def test_fallo_del_rss_devuelve_vacio() -> None:
    async def fetch(url: str):
        raise ConnectionError("bing caído")

    assert asyncio.run(press.fetch_press_targets("ASTS", today=TODAY, fetch=fetch)) == []


# -- merge_press_rows ----------------------------------------------------------


def _pt(firm: str, day: date, target: float, mark: str | None = None) -> press.PressTarget:
    return press.PressTarget(
        firm=firm, date=day, price_target=target, prior_target=None, rating=None, action=None,
        outlet="StreetInsider", url="https://www.streetinsider.com/x", currency_mark=mark,
        full_text=False)


def _yahoo_row(firm: str, day: date, target: float) -> svc.AnalystTargetRow:
    return svc.AnalystTargetRow(firm=firm, date=day.isoformat(), price_target=target)


def test_prensa_mas_reciente_reemplaza_la_fila_de_yahoo() -> None:
    rows = [_yahoo_row("Cantor Fitzgerald", date(2026, 8, 11), 61.0)]
    merged = svc.merge_press_rows(rows, [_pt("Cantor Fitzgerald", TODAY, 90.0)],
                                  reference_price=50.0, currency="USD")
    assert len(merged) == 1
    row = merged[0]
    assert row.date == TODAY.isoformat() and row.price_target == 90.0
    assert row.source == "StreetInsider"
    assert row.source_url == "https://www.streetinsider.com/x"
    assert row.upside_percent == 80.0


def test_prensa_mas_antigua_o_de_la_misma_fecha_no_reemplaza_a_yahoo() -> None:
    rows = [_yahoo_row("Cantor Fitzgerald", TODAY, 90.0)]
    older = _pt("Cantor Fitzgerald", date(2026, 8, 11), 61.0)
    same_day = _pt("Cantor Fitzgerald", TODAY, 88.0)
    merged = svc.merge_press_rows(rows, [older, same_day], reference_price=50.0, currency="USD")
    assert len(merged) == 1
    assert merged[0].price_target == 90.0 and merged[0].source == svc.SOURCE


def test_prensa_de_firma_nueva_se_añade_ordenada_por_fecha() -> None:
    rows = [_yahoo_row("TD Cowen", date(2026, 10, 1), 80.0)]
    merged = svc.merge_press_rows(rows, [_pt("Cantor Fitzgerald", TODAY, 90.0)],
                                  reference_price=None, currency="USD")
    assert [row.firm for row in merged] == ["Cantor Fitzgerald", "TD Cowen"]
    assert merged[0].upside_percent is None


def test_divisa_no_verificable_descarta_la_fila_de_prensa() -> None:
    rows = [_yahoo_row("TD Cowen", date(2026, 10, 1), 80.0)]
    merged = svc.merge_press_rows(rows, [_pt("Cantor Fitzgerald", TODAY, 90.0)],
                                  reference_price=50.0, currency="CAD")
    assert len(merged) == 1 and merged[0].source == svc.SOURCE
    merged = svc.merge_press_rows(rows, [_pt("Cantor Fitzgerald", TODAY, 90.0)],
                                  reference_price=50.0, currency=None)
    assert len(merged) == 1 and merged[0].source == svc.SOURCE


# -- servicio: press=1 ---------------------------------------------------------


def _payload() -> dict:
    when = datetime(2026, 8, 11, 12, 0)
    return {
        "records": [{"firm": "Cantor Fitzgerald", "date": when, "rating": "Overweight",
                     "action": "main", "price_target": 61.0, "prior_target": None}],
        "consensus": {"current": 50.0, "mean": 70.0, "low": 40.0, "high": 90.0, "median": 68.0},
        "currency": "USD", "quote_type": "EQUITY", "first_trade_date": None,
    }


def _get(monkeypatch, *, press_rows, press_flag=True, calls: list | None = None):
    monkeypatch.setattr(svc, "_fetch_sync", lambda symbol: _payload())

    async def fake_press(symbol: str, *, today: date, queries: list[str] | None = None):
        if calls is not None:
            calls.append(queries)
        return press_rows

    monkeypatch.setattr(press, "fetch_press_targets", fake_press)
    return asyncio.run(svc.AnalystTargetsService().get("ASTS", press=press_flag))


def test_press_1_añade_la_nota_del_dia_y_declara_la_fuente(monkeypatch) -> None:
    result = _get(monkeypatch, press_rows=[_pt("Cantor Fitzgerald", TODAY, 90.0)])
    assert result.status == "available"
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.firm == "Cantor Fitzgerald" and row.date == TODAY.isoformat()
    assert row.price_target == 90.0 and row.source == "StreetInsider"
    assert result.note_code == "with_press" and result.note
    # El consenso agregado sigue siendo el de Yahoo, nunca recalculado.
    assert result.consensus is not None and result.consensus.mean == 70.0


def test_press_1_con_error_de_prensa_deja_el_panel_como_yahoo(monkeypatch) -> None:
    monkeypatch.setattr(svc, "_fetch_sync", lambda symbol: _payload())

    async def boom(symbol: str, *, today: date, queries: list[str] | None = None):
        raise RuntimeError("bing caído")

    monkeypatch.setattr(press, "fetch_press_targets", boom)
    result = asyncio.run(svc.AnalystTargetsService().get("ASTS", press=True))
    assert result.status == "available"
    assert len(result.rows) == 1 and result.rows[0].source == svc.SOURCE
    assert result.note is None and result.note_code is None


def test_sin_press_no_consulta_prensa_y_cachea_aparte(monkeypatch) -> None:
    monkeypatch.setattr(svc, "_fetch_sync", lambda symbol: _payload())
    calls: list = []

    async def fake_press(symbol: str, *, today: date, queries: list[str] | None = None):
        calls.append(symbol)
        return []

    monkeypatch.setattr(press, "fetch_press_targets", fake_press)
    service = svc.AnalystTargetsService()
    plain = asyncio.run(service.get("ASTS"))
    assert calls == [] and plain.note_code is None
    with_press = asyncio.run(service.get("ASTS", press=True))
    assert calls == ["ASTS", "ASTS"] and with_press.note_code is None
    # Entradas de caché separadas: la variante sin prensa no cambia.
    assert asyncio.run(service.get("ASTS")).rows[0].price_target == 61.0


def test_segunda_pasada_con_consultas_por_firma_envejecida(monkeypatch) -> None:
    calls: list = []
    result = _get(monkeypatch, press_rows=[], calls=calls)
    # La fila de Yahoo es del 11 ago: envejecida, dispara la consulta por firma.
    assert calls == [None, ['"ASTS" "Cantor Fitzgerald"']]
    assert result.status == "available"


def test_sin_presupuesto_no_hay_prensa_ni_espera_minima(monkeypatch) -> None:
    # Presupuesto agotado (auditor, ronda 3): ni fase de prensa ni espera
    # mínima de 0,5 s; la respuesta sale al instante con el fallo declarado.
    monkeypatch.setattr(svc, "TOTAL_BUDGET_SECONDS", 0)
    monkeypatch.setattr(svc, "_fetch_sync", lambda symbol: _payload())
    calls: list = []

    async def fake_press(symbol: str, *, today: date, queries: list[str] | None = None):
        calls.append(queries)
        return []

    monkeypatch.setattr(press, "fetch_press_targets", fake_press)
    started = time.monotonic()
    result = asyncio.run(svc.AnalystTargetsService().get("ASTS", press=True))
    elapsed = time.monotonic() - started
    assert calls == []  # ninguna pasada de prensa
    assert elapsed < 0.5  # sin espera mínima
    assert result.note_code == "fetch_failed"


def test_segunda_pasada_omite_firmas_frescas(monkeypatch) -> None:
    fresh = datetime.now(UTC) - timedelta(days=1)
    payload = _payload()
    payload["records"][0]["date"] = fresh
    monkeypatch.setattr(svc, "_fetch_sync", lambda symbol: payload)
    calls: list = []

    async def fake_press(symbol: str, *, today: date, queries: list[str] | None = None):
        calls.append(queries)
        return []

    monkeypatch.setattr(press, "fetch_press_targets", fake_press)
    asyncio.run(svc.AnalystTargetsService().get("ASTS", press=True))
    assert calls == [None]


def _extract(text, today=TODAY, symbol="ASTS"):
    return press.extract_targets(
        text, symbol=symbol, published=today, url="https://www.example.com/news/1",
        full_text=True, today=today)


# --- Bloqueo A del auditor: anio explicito y fechas vagas ------------------

def test_extract_explicit_year_respected_even_if_past():
    text = "Cantor Fitzgerald reiterated a $90.00 price target on ASTS on November 3, 2024."
    rows = _extract(text)
    assert len(rows) == 1 and rows[0].date == date(2024, 11, 3)


def test_extract_month_day_abbreviation_variants():
    for fmt in ("on Nov. 3", "on November 3rd", "on 3 Nov", "on 3 November"):
        rows = _extract(f"Cantor Fitzgerald kept a $90 price target on ASTS {fmt}.")
        assert len(rows) == 1 and rows[0].date == date(2026, 11, 3), fmt


def test_extract_two_digit_year():
    rows = _extract(
        "Cantor Fitzgerald reiterated a $90.00 price target on ASTS on Nov. 3, '24.")
    assert len(rows) == 1 and rows[0].date == date(2024, 11, 3)


def test_extract_vague_dates_produce_no_row():
    for vague in ("last year", "earlier this month", "last week", "in September"):
        text = f"Cantor Fitzgerald reiterated a $90.00 price target on ASTS {vague}."
        assert _extract(text) == [], vague


def test_extract_explicit_future_year_produces_no_row():
    rows = _extract(
        "Cantor Fitzgerald reiterated a $90.00 price target on ASTS on November 3, 2027.")
    assert rows == []


# --- Bloqueo B del auditor: el objetivo debe ir pegado a la empresa --------

def test_extract_foreign_company_object_produces_no_row():
    text = "Cantor Fitzgerald reiterated a $90.00 price target on Apple while discussing ASTS."
    assert _extract(text) == []


def test_extract_cross_company_news_round1_produces_no_row():
    # Primer contraejemplo del auditor: «ASTS is in the news. Cantor ... $250 on AAPL».
    text = ("ASTS is in the news. Cantor Fitzgerald reiterated a $250.00 price target on "
            "Apple (NASDAQ: AAPL) and keeps an Overweight rating.")
    assert _extract(text) == []


def test_extract_bound_object_variants_pass():
    cases = [
        ("Cantor Fitzgerald reiterated a $90.00 price target on ASTS.", 90.0),
        ("AST Spacemobile (ASTS) PT Raised to $90 at Cantor Fitzgerald.", 90.0),
        ("AST Spacemobile (NASDAQ: ASTS) PT Lowered to $54.00 From $98.00 at Piper Sandler.", 54.0),
        ("Roth Capital lowered its price target on AST SpaceMobile (ASTS) to $50.00.", 50.0),
    ]
    for text, expected in cases:
        rows = _extract(text)
        assert len(rows) == 1, text
        assert rows[0].price_target == expected, text


# --- Bloqueo 1 del auditor (ronda 3): cifra pegada y frase con 2 objetivos --

def test_extract_two_price_targets_in_one_sentence_produces_no_row():
    text = ("Cantor reiterated a $250 price target on Apple while keeping a "
            "$90 price target on ASTS.")
    assert _extract(text) == []


def test_extract_extra_money_figure_produces_no_row():
    text = "Cantor Fitzgerald reiterated a $90 price target on ASTS, above the $80 consensus."
    assert _extract(text) == []


def test_extract_prior_from_figure_still_allowed():
    rows = _extract("Piper Sandler lowered its price target on ASTS to $54.00 from $98.00.")
    assert len(rows) == 1 and rows[0].price_target == 54.0 and rows[0].prior_target == 98.0


# --- Bloqueo 2 del auditor (ronda 3): años sueltos sin fecha completa -------

def test_extract_stray_year_without_full_date_produces_no_row():
    assert _extract("Cantor Fitzgerald reiterated a $90.00 price target on ASTS in 2024.") == []
    assert _extract("Cantor Fitzgerald reiterated a $90.00 price target on ASTS on November 3 in 2024.") == []
    assert _extract("Cantor Fitzgerald reiterated a $90.00 price target on ASTS back in '24.") == []


def test_extract_same_year_mention_keeps_pubdate():
    rows = _extract("Cantor Fitzgerald reiterated a $90.00 price target on ASTS in 2026.")
    assert len(rows) == 1 and rows[0].date == TODAY


# --- Bloqueo 3 del auditor (ronda 3): lock por host en el pacing ------------

def test_paced_fetch_serializes_same_host(monkeypatch):
    monkeypatch.setattr(press, "MIN_INTERVAL_S", 0.08)
    monkeypatch.setattr(press, "_HOST_LAST", {})
    monkeypatch.setattr(press, "_HOST_LOCKS", {})
    order = []

    async def fake_fetch(url):
        order.append(("start", url))
        await asyncio.sleep(0.03)
        order.append(("end", url))

    async def run():
        await asyncio.gather(
            press._paced_fetch(fake_fetch, "https://m.example.com/a"),
            press._paced_fetch(fake_fetch, "https://m.example.com/b"),
        )

    asyncio.run(run())
    # Con lock, la segunda petición no empieza hasta que acaba la primera.
    assert order == [("start", "https://m.example.com/a"),
                     ("end", "https://m.example.com/a"),
                     ("start", "https://m.example.com/b"),
                     ("end", "https://m.example.com/b")] or \
           order == [("start", "https://m.example.com/b"),
                     ("end", "https://m.example.com/b"),
                     ("start", "https://m.example.com/a"),
                     ("end", "https://m.example.com/a")]
