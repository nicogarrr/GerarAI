"""Carril de noticias por ticker sin GDELT: URLs, fuente real y filtro de evidencia."""

import asyncio
from types import SimpleNamespace

from app.services.connectors.base import ConnectorItem, ConnectorResult
from app.services.connectors.rss import RSSConnector
from app.services.news_service import _ticker_evidence_level
from app.services.ticker_news_lane import (
    PRIORITY_TICKERS,
    Deadline,
    finalize_status,
    google_feed_url,
    ingest_in_chunks,
    is_us_listed,
    label_google,
    label_yahoo,
    sweep,
    yahoo_feed_url,
)

SPCX = SimpleNamespace(ticker="SPCX", name="Space Exploration Technologies Corp", exchange="NASDAQ")
ASTS = SimpleNamespace(ticker="ASTS", name="AST SpaceMobile Inc", exchange="NASDAQ NMS - GLOBAL MARKET")
AENA = SimpleNamespace(ticker="AENA", name="AENA S.M.E. SA", exchange="BME")

YAHOO_XML = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Yahoo! Finance: SPCX News</title>
<item><title>SpaceX Buys Wireless Spectrum For Starlink</title><link>https://example.com/a</link>
<guid>a-1</guid><pubDate>Thu, 08 Oct 2026 21:00:00 +0000</pubDate><description>SPCX news</description></item>
</channel></rss>"""


def _item(title: str, summary: str = "") -> ConnectorItem:
    return ConnectorItem(source="Google News", title=title, summary=summary, ticker="SPCX")


def test_priority_tickers_include_asts_and_spcx():
    assert {"ASTS", "SPCX"} <= PRIORITY_TICKERS


def test_only_us_listed_get_a_yahoo_symbol():
    assert is_us_listed(SPCX) and is_us_listed(ASTS)
    assert not is_us_listed(AENA)


def test_feed_urls_are_free_rss_endpoints():
    assert yahoo_feed_url("spcx") == (
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=SPCX&region=US&lang=en-US"
    )
    url = google_feed_url(SPCX, lang="es")
    assert url.startswith("https://news.google.com/rss/search?q=")
    assert "hl=es&gl=ES&ceid=ES:es" in url
    assert "Space+Exploration+Technologies" in url


def test_yahoo_items_keep_real_date_and_a_stable_source_label():
    class _Fake(RSSConnector):
        async def _fetch(self, url):
            return YAHOO_XML  # _fetch devuelve bytes (contrato de RSSConnector._fetch)

    result = asyncio.run(_Fake().poll(yahoo_feed_url("SPCX"), ticker="SPCX"))
    result = label_yahoo(result)
    item = result.items[0]
    assert item.source == "Yahoo Finance"
    assert item.published_at is not None and item.published_at.isoformat().startswith("2026-10-08T21:00")


def test_google_keeps_publisher_and_drops_items_without_company_evidence():
    result = ConnectorResult(
        source="rss",
        items=[
            _item("SpaceX adquirira el espectro para Starlink Mobile - TradingView", "SPCX"),
            _item("Receta de tortilla de patatas - Cocina Facil", "nada que ver"),
        ],
    )
    out = label_google(result, SPCX, _ticker_evidence_level)
    assert [i.source for i in out.items] == ["TradingView"]
    assert out.items[0].title == "SpaceX adquirira el espectro para Starlink Mobile"


def test_spacex_headline_without_ticker_is_accepted_for_spcx():
    result = ConnectorResult(source="rss", items=[
        _item("SpaceX Buys Wireless Spectrum For Starlink Mobile - TradingView"),
        _item("SpaceX busca 40.000 millones de dolares de deuda - La Vanguardia"),
    ])
    out = label_google(result, SPCX, _ticker_evidence_level)
    assert [i.source for i in out.items] == ["TradingView", "La Vanguardia"]


def test_ast_spacemobile_name_only_is_accepted_for_asts_but_not_for_spcx():
    headline = "AST SpaceMobile launches BlueBird 7 satellite - Reuters"
    kept = label_google(ConnectorResult(source="rss", items=[_item(headline)]), ASTS, _ticker_evidence_level)
    assert len(kept.items) == 1
    other = label_google(ConnectorResult(source="rss", items=[_item(headline)]), SPCX, _ticker_evidence_level)
    assert other.items == []


def test_competitor_and_generic_terms_are_rejected():
    items = [
        _item("Rocket Lab drops 4% as Planet Labs falls 5% - 247WallSt"),
        _item("Satellite broadband market grows - Telecom Weekly"),
        _item("Apple pie recipe - Cocina"),
    ]
    apple = SimpleNamespace(ticker="AAPL", name="Apple Inc", exchange="NASDAQ")
    assert label_google(ConnectorResult(source="rss", items=list(items)), ASTS, _ticker_evidence_level).items == []
    assert label_google(ConnectorResult(source="rss", items=list(items)), SPCX, _ticker_evidence_level).items == []
    # Una sola palabra generica de nombre no basta ("Apple" sin ticker).
    assert label_google(ConnectorResult(source="rss", items=list(items)), apple, _ticker_evidence_level).items == []


def test_deadline_is_checked_before_and_after_each_unit_and_marks_truncated():
    now = [0.0]
    deadline = Deadline(100, clock=lambda: now[0])
    assert deadline.expired() is False and deadline.truncated is False
    now[0] = 99.0
    assert deadline.expired() is False
    now[0] = 101.0  # la unidad en curso paso el limite
    assert deadline.expired() is True
    now[0] = 0.0  # una vez truncado no se "des-trunca"
    assert deadline.expired() is True and deadline.truncated is True


def test_truncated_sweep_is_never_ok_so_the_coalescer_does_not_mark_it_fresh():
    assert finalize_status("ok", True) == "partial"
    assert finalize_status("ok", False) == "ok"
    assert finalize_status("error", True) == "error"
    assert finalize_status("partial", True) == "partial"


def _fake_run(n_feeds, clock_steps, *, items=0, chunk_clock=None):
    """Ejecuta sweep con reloj simulado: clock_steps[i] = hora tras la unidad i."""
    now = [0.0]
    calls = {"fetch": 0, "ingest": 0}

    def fetch(company, lane, url):
        i = calls["fetch"]
        calls["fetch"] += 1
        now[0] = clock_steps[i]
        return ConnectorResult(source="rss", items=[_item(f"t{k}") for k in range(items)])

    def ingest(company, part):
        calls["ingest"] += 1
        if chunk_clock:
            now[0] = chunk_clock[calls["ingest"] - 1]
        return {"created": len(part.items)}

    deadline = Deadline(6600, clock=lambda: now[0])
    out = sweep(
        [SPCX],
        lambda c: [(f"feed{k}", f"u{k}") for k in range(n_feeds)],
        fetch,
        ingest,
        deadline,
    )
    return out, deadline, calls


def test_single_feed_that_overshoots_the_limit_is_partial_not_ok():
    out, deadline, _ = _fake_run(1, [7000.0])
    assert deadline.truncated is True
    assert finalize_status("ok", deadline.truncated) == "partial"
    assert out["processed"] == 1


def test_three_feeds_stop_after_the_second_overshoots():
    out, deadline, calls = _fake_run(3, [100.0, 7000.0, 7100.0])
    assert calls["fetch"] == 2 and deadline.truncated is True


def test_fast_sweep_stays_complete_and_ok():
    out, deadline, calls = _fake_run(3, [1.0, 2.0, 3.0], items=3)
    assert calls["fetch"] == 3 and deadline.truncated is False
    assert finalize_status("ok", deadline.truncated) == "ok"
    assert out["ingested"] == 9


def test_ingestion_stops_between_item_chunks_when_budget_runs_out():
    # 12 items = 3 tandas de 5/5/2; el limite se cruza tras la primera.
    out, deadline, calls = _fake_run(1, [1.0], items=12, chunk_clock=[7000.0, 7000.0, 7000.0])
    assert calls["ingest"] == 1 and out["ingested"] == 5
    assert deadline.truncated is True


def test_ingest_in_chunks_returns_created_total():
    now = [0.0]
    result = ConnectorResult(source="rss", items=[_item(f"x{i}") for i in range(11)])
    total = ingest_in_chunks(lambda part: {"created": len(part.items)}, result, Deadline(10, clock=lambda: now[0]))
    assert total == 11


def test_yahoo_drops_competitor_only_headlines_but_keeps_company_mentions():
    items = [
        _item("Rocket Lab Has Imploded For 3 Months: 145% Gains Are Coming According to This Pro Analyst", "Rocket Lab has shed a fifth of its value."),
        _item("Rocket Lab vs AST SpaceMobile: which space stock wins?", "ASTS and Rocket Lab compared."),
        _item("Analyst raises price target", "No names here."),
    ]
    out = label_yahoo(ConnectorResult(source="rss", items=items), ASTS, _ticker_evidence_level)
    # Sin citar a la empresa (ni ticker, ni nombre, ni alias) tampoco se liga al ticker del feed.
    assert [i.title for i in out.items] == [
        "Rocket Lab vs AST SpaceMobile: which space stock wins?",
    ]
    # Sin empresa (compatibilidad) no se filtra por competidor.
    assert len(label_yahoo(ConnectorResult(source="rss", items=list(items))).items) == 3


def test_yahoo_drops_headline_whose_only_company_mention_is_a_ticker_prefix():
    class _Co:
        ticker = "NVDA"
        name = "NVIDIA Corporation"

    fastenal = _item(
        "NVDA Data Centers, Aerospace, and Machined Parts: This Company's Earnings Just Made the Bull Case for U.S. Industrials",
        "NVDA Data Centers, Aerospace, and Machined Parts: Fastenal's results signal a strong industrial recovery.",
    )
    real = _item("NVDA Nvidia unveils new data center chip", "NVDA Nvidia unveils a new chip for data centers.")
    plain = _item("Nvidia shares rise after earnings", "Nvidia beat estimates.")
    other_ticker_news = _item("Chipmakers rally on AI demand", "Sector move.")
    out = label_yahoo(
        ConnectorResult(source="rss", items=[fastenal, real, plain, other_ticker_news]), _Co, _ticker_evidence_level
    )
    assert [i.title for i in out.items] == [real.title, plain.title]


def test_law_firm_solicitation_is_detected_but_real_news_is_not():
    from app.services.ticker_news_lane import is_law_firm_solicitation

    assert is_law_firm_solicitation(
        "ASTS Investors: Rosen Law Firm Encourages AST SpaceMobile Investors to Secure Counsel"
    )
    assert is_law_firm_solicitation(
        "Lead Plaintiff Deadline Approaching in AST SpaceMobile Class Action"
    )
    assert is_law_firm_solicitation(
        "Pomerantz Law Firms Investigates Claims On Behalf of Investors of AST SpaceMobile"
    )
    assert is_law_firm_solicitation(
        "UPCOMING DEADLINE: SueWallSt Alerts AST SpaceMobile, Inc. Stockholders of Securities Class Action"
    )
    assert not is_law_firm_solicitation("AST SpaceMobile launches BlueBird 6 satellite")
    assert not is_law_firm_solicitation("AST SpaceMobile signs contract with AT&T")
    assert not is_law_firm_solicitation("AST SpaceMobile faces securities lawsuit, Reuters reports")
    assert not is_law_firm_solicitation("Deadline looms for AST SpaceMobile earnings report")

def test_impact_direction_whole_words_and_valuation_phrases():
    from app.services.materiality_service import MaterialityService

    direction = MaterialityService()._impact_direction
    assert direction("ast spacemobile: priced for perfection?") == "negative"
    assert direction("analysts praise the execution plan") == "neutral"
    assert direction("record revenue but valuation concern grows") == "mixed"
    assert direction("beats estimates, record quarter") == "positive"


def test_yahoo_ticker_feed_only_keeps_items_that_cite_the_company():
    """QA: Novo Nordisk / Ken Griffin bajo NVDA y Verizon bajo GOOGL se ligaban por el ticker del feed."""

    class _Nvda:
        ticker = "NVDA"
        name = "NVIDIA Corporation"

    class _Googl:
        ticker = "GOOGL"
        name = "Alphabet Inc"

    nvda = [
        _item("Novo Trades at Less Than 12 Times Earnings", "Novo Nordisk valuation."),
        _item("Ken Griffin Just Bought a Dividend King", "Citadel's latest 13F."),
        _item("My Top Dividend Growth Stock", "Why I own it."),
        _item("Nvidia unveils new Blackwell chip", "Nvidia said on Monday."),
    ]
    out = label_yahoo(ConnectorResult(source="rss", items=nvda), _Nvda, _ticker_evidence_level)
    assert [i.title for i in out.items] == ["Nvidia unveils new Blackwell chip"]

    googl = [
        _item("Verizon launches generous customer perks", "Verizon says new perks."),
        _item("Alphabet's Google expands cloud region", "Alphabet said."),
        _item("YouTube adds new creator tools", "The video platform."),
    ]
    out = label_yahoo(ConnectorResult(source="rss", items=googl), _Googl, _ticker_evidence_level)
    assert [i.title for i in out.items] == [
        "Alphabet's Google expands cloud region",
        "YouTube adds new creator tools",
    ]


def test_yahoo_body_only_mention_is_not_attributed_tieto_msft():
    """QA 19 oct 2026: «The Bet Behind Tieto's Rally» entró al carril de MSFT con
    materialidad 10 porque el cuerpo decía «AI partnership with Microsoft»."""

    class _Msft:
        ticker = "MSFT"
        name = "Microsoft Corporation"

    items = [
        _item(
            "The Bet Behind Tieto's Rally",
            "One concrete shift for Tieto was its deepening AI partnership with Microsoft, "
            "aimed at integrating new tools into long standing client contracts.",
        ),
        _item("Microsoft expands Azure region in Spain", "Microsoft said on Monday."),
    ]
    out = label_yahoo(ConnectorResult(source="rss", items=items), _Msft, _ticker_evidence_level)
    assert [i.title for i in out.items] == ["Microsoft expands Azure region in Spain"]


def test_google_body_only_mention_is_not_attributed():
    """Mismo criterio en el carril de Google: el cuerpo no atribuye, solo el titular."""

    class _Msft:
        ticker = "MSFT"
        name = "Microsoft Corporation"

    items = [
        _item("The Bet Behind Tieto's Rally", "…deepening AI partnership with Microsoft…"),
        _item("GitHub Copilot adds model picker - The Verge", "The developer tool."),
    ]
    out = label_google(ConnectorResult(source="rss", items=items), _Msft, _ticker_evidence_level)
    assert [i.title for i in out.items] == ["GitHub Copilot adds model picker"]


def test_google_junk_publisher_falls_back_to_aggregator():
    # «Bitcoin Foundation» no es un medio: republica noticias ajenas bajo un
    # nombre de organización (visto en prod con una noticia de JPM). Se muestra
    # el agregador en vez de la etiqueta.
    result = ConnectorResult(source="rss", items=[
        _item("SpaceX firma un acuerdo de lanzamiento con la ESA - Bitcoin Foundation"),
        _item("SpaceX firma otro acuerdo de lanzamiento - CNBC"),
    ])
    out = label_google(result, SPCX, _ticker_evidence_level)
    assert [i.source for i in out.items] == ["Google News", "CNBC"]
