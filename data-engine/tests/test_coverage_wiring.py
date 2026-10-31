"""Cobertura hermetica del wiring reciente (mocks, SQLite, sin red).

Cubre los huecos que los PRs recientes no testean:

(a) insider_service: sin compras, solo ventas, cluster exacto de 3.
(b) tearsheet: serie vacia/corta y drawdown conocido.
(c) earnings_calendar: rango invalido y dia unavailable.
(d) valuation trace: incluye free_data si el doc lo tiene, lo omite si no.
(e) lookahead: falla con dato futuro, pasa con pasado.
(f) vendors: finnhub por env, yahoo sin key.
(g) debate bull/bear + hook en chat: degradacion determinista sin LLM.

Si un modulo del wiring no existe en el arbol (PR revertido o pendiente),
el test correspondiente hace skip con mensaje en vez de fallar.
"""

from __future__ import annotations

import asyncio
import importlib
from datetime import date
from types import SimpleNamespace

import httpx
import pytest

from app.services import insider_service, tearsheet_service
from app.services.connectors import earnings_calendar as calendar_connector
from app.services.connectors import form4 as form4_connector
from app.services.connectors.finnhub import FinnhubClient
from app.services.connectors.fmp import FMPClient


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- (a) insider


def _buy(insider, day, value=100.0, ticker="ACME", title="", cik=None):
    return {
        "type": "P",
        "acquired_disposed": "A",
        "ticker": ticker,
        "insider": insider,
        "insider_cik": cik or insider,
        "role": "",
        "officer_title": title,
        "date": day,
        "shares": 10,
        "price": 10.0,
        "value": value,
    }


def _sell(insider, day, ticker="ACME"):
    return {
        "type": "S",
        "acquired_disposed": "D",
        "ticker": ticker,
        "insider": insider,
        "insider_cik": insider,
        "role": "",
        "officer_title": "",
        "date": day,
        "shares": 10,
        "price": 10.0,
        "value": 100.0,
    }


def test_a_sin_compras_sin_senales():
    assert insider_service.detect_signals([]) == []
    assert insider_service.open_market_buys([]) == []


def test_a_solo_ventas_sin_senales():
    txs = [_sell("Alice", "2024-01-05"), _sell("Bob", "2024-01-06")]
    assert insider_service.open_market_buys(txs) == []
    assert insider_service.detect_signals(txs) == []


def test_a_cluster_exactamente_tres_insiders():
    txs = [
        _buy("Alice", "2024-01-05"),
        _buy("Bob", "2024-01-10"),
        _buy("Carol", "2024-01-20"),
    ]
    clusters = [s for s in insider_service.detect_signals(txs) if s["signal"] == "cluster_buy"]
    assert len(clusters) == 1
    assert clusters[0]["insider_count"] == 3
    assert clusters[0]["ticker"] == "ACME"


def test_a_sin_cluster_con_dos_insiders_o_ventana_dispersa():
    two = [_buy("Alice", "2024-01-05"), _buy("Bob", "2024-01-10")]
    assert not [s for s in insider_service.detect_signals(two) if s["signal"] == "cluster_buy"]
    spread = [
        _buy("Alice", "2024-01-01"),
        _buy("Bob", "2024-02-15"),
        _buy("Carol", "2024-04-01"),
    ]
    assert not [s for s in insider_service.detect_signals(spread) if s["signal"] == "cluster_buy"]


def test_a_pipeline_solo_ventas_degrada_a_sin_senales(monkeypatch):
    filing = {"accession_number": "0001", "filing_date": "2024-01-06", "document_url": "https://www.sec.gov/x"}
    monkeypatch.setattr(
        form4_connector, "recent_form4_filings", lambda cik, **kw: [filing]
    )
    monkeypatch.setattr(
        form4_connector,
        "parse_form4_xml",
        lambda xml: {"transactions": [_sell("Alice", "2024-01-05")]},
    )
    result = insider_service.get_signals_for_ticker(
        "ACME", cik="0000000001", fetcher=lambda filing: "<ownershipDocument/>"
    )
    assert result["status"] == "ok"
    assert result["signals"] == []
    assert result["buy_count"] == 0


# --------------------------------------------------------------- (b) tearsheet


def test_b_serie_vacia_insufficient_data():
    metrics = tearsheet_service.compute_metrics([])
    assert metrics["status"] == "insufficient_data"
    assert metrics["n_observations"] == 0
    assert metrics["max_drawdown"] is None
    assert metrics["sharpe"] is None


def test_b_serie_de_un_dato_insufficient_data():
    metrics = tearsheet_service.compute_metrics([0.05])
    assert metrics["status"] == "insufficient_data"
    assert metrics["n_observations"] == 1


def test_b_drawdown_conocido():
    # 100 -> 110 (+10%) -> 88 (-20%): max DD = (88-110)/110 = -0.2
    metrics = tearsheet_service.compute_metrics([0.10, -0.20])
    assert metrics["status"] == "ok"
    assert metrics["max_drawdown"] == pytest.approx(-0.2)
    assert metrics["cumulative_return"] == pytest.approx(1.1 * 0.8 - 1.0)


def test_b_build_sin_portfolio_no_rompe(monkeypatch):
    from app.core.database import SessionLocal, init_db
    from app.services import portfolio_fx_service as fx_module

    monkeypatch.setattr(
        fx_module.PortfolioFXService, "portfolio", lambda self, db: None
    )
    init_db()
    db = SessionLocal()
    try:
        result = tearsheet_service.TearsheetService().build(db)
    finally:
        db.close()
    assert result["status"] == "no_portfolio"
    assert result["metrics"] is None


# ------------------------------------------------------ (c) earnings calendar


def test_c_rango_invalido_falla_en_conector():
    with pytest.raises(ValueError, match="posterior"):
        run(calendar_connector.fetch_earnings_range(date(2024, 2, 1), date(2024, 1, 1)))
    too_long = calendar_connector.MAX_DAYS_PER_REQUEST + 1
    with pytest.raises(ValueError, match="rango máximo"):
        run(
            calendar_connector.fetch_earnings_range(
                date(2024, 1, 1),
                date(2024, 1, 1).fromordinal(date(2024, 1, 1).toordinal() + too_long),
            )
        )


def test_c_rango_invalido_es_400_en_ruta():
    from fastapi import HTTPException

    from app.api.routes.calendar import _resolve_range

    with pytest.raises(HTTPException) as exc:
        _resolve_range(date(2024, 2, 1), date(2024, 1, 1))
    assert exc.value.status_code == 400
    with pytest.raises(HTTPException) as exc2:
        _resolve_range(date(2024, 1, 1), date(2025, 6, 1))
    assert exc2.value.status_code == 400


def _failing_client():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={}, request=request)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_c_dia_unavailable_y_rango_unavailable():
    async def probe():
        async with _failing_client() as client:
            day = await calendar_connector.fetch_earnings_day(date(2024, 1, 2), client)
            one_day = await calendar_connector.fetch_earnings_range(
                date(2024, 1, 2), date(2024, 1, 2), client
            )
            div_day = await calendar_connector.fetch_dividends_range(
                date(2024, 1, 2), date(2024, 1, 2), client
            )
        return day, one_day, div_day

    day, one_day, div_day = run(probe())
    assert day is None
    assert one_day["status"] == "unavailable"
    assert one_day["events"] == []
    assert div_day["status"] == "unavailable"


# ------------------------------------------------- (d) valuation free_data


def _valuation_service():
    from app.services import valuation_service

    helper = getattr(valuation_service, "_free_data_trace", None)
    if helper is None:
        pytest.skip("valuation_service._free_data_trace no existe en el arbol")
    return valuation_service, helper


def _wiring_company(db, ticker):
    from app.models import Company

    company = db.scalar(__import__("sqlalchemy").select(Company).where(Company.ticker == ticker))
    if company is None:
        company = Company(
            ticker=ticker,
            name=f"Wiring {ticker}",
            exchange="NASDAQ",
            currency="USD",
            sector="Technology",
            industry="Software",
            company_type="operating_company",
            valuation_model="dcf",
            special_sources=[],
            special_risks=[],
            factor_tags=[],
        )
        db.add(company)
        db.flush()
    return company


def test_d_trace_incluye_free_data_cuando_el_doc_lo_tiene():
    valuation_service, helper = _valuation_service()
    from sqlalchemy import select

    from app.core.database import SessionLocal, init_db
    from app.models import Company, Document

    init_db()
    db = SessionLocal()
    ticker = "WIRING_FD1"
    try:
        company = _wiring_company(db, ticker)
        db.add(
            Document(
                company_id=company.id,
                title="10-K wiring",
                source_type="sec_edgar",
                metadata_={"free_data": {"recent_filings": [{"form": "10-K"}]}},
            )
        )
        db.flush()
        assert helper(db, company) == {"recent_filings": [{"form": "10-K"}]}
        result = valuation_service.ValuationService().value_company(db, company)
        assert result["trace"]["free_data"] == {"recent_filings": [{"form": "10-K"}]}
    finally:
        db.rollback()
        for doc in db.scalars(select(Document).where(Document.company_id == company.id)).all():
            db.delete(doc)
        for comp in db.scalars(select(Company).where(Company.ticker == ticker)).all():
            db.delete(comp)
        db.commit()
        db.close()


def test_d_trace_omite_free_data_si_no_hay_doc_con_datos():
    valuation_service, helper = _valuation_service()
    from sqlalchemy import select

    from app.core.database import SessionLocal, init_db
    from app.models import Company

    init_db()
    db = SessionLocal()
    ticker = "WIRING_FD2"
    try:
        company = _wiring_company(db, ticker)
        assert helper(db, company) is None
        result = valuation_service.ValuationService().value_company(db, company)
        assert "free_data" not in result["trace"]
    finally:
        db.rollback()
        for comp in db.scalars(select(Company).where(Company.ticker == ticker)).all():
            db.delete(comp)
        db.commit()
        db.close()


# ---------------------------------------------------------- (e) lookahead


def _lookahead_module():
    for name in (
        "app.valuation.point_in_time",
        "app.valuation.no_lookahead",
        "app.services.no_lookahead",
    ):
        try:
            return importlib.import_module(name)
        except ImportError:
            continue
    pytest.skip("modulo lookahead (point_in_time/no_lookahead) no existe en el arbol")


def test_e_falla_con_dato_futuro_y_pasa_con_pasado():
    mod = _lookahead_module()
    with pytest.raises(mod.LookaheadError):
        mod.assert_no_lookahead(as_of=date(2024, 1, 31), data_date=date(2024, 2, 1))
    assert mod.assert_no_lookahead(as_of=date(2024, 1, 31), data_date=date(2024, 1, 15)) is None
    assert mod.assert_no_lookahead(as_of=date(2024, 1, 31), data_date=date(2024, 1, 31)) is None
    assert mod.assert_no_lookahead(as_of=date(2024, 1, 31), data_date=None) is None


def test_e_ano_fiscal_futuro_falla():
    mod = _lookahead_module()
    if not hasattr(mod, "assert_fiscal_year_no_lookahead"):
        pytest.skip("assert_fiscal_year_no_lookahead no existe en el modulo")
    with pytest.raises(mod.LookaheadError):
        mod.assert_fiscal_year_no_lookahead(as_of=date(2024, 6, 1), fiscal_year=2025)
    assert (
        mod.assert_fiscal_year_no_lookahead(as_of=date(2024, 6, 1), fiscal_year=2023) is None
    )


def test_e_guard_de_value_company_nunca_rompe_el_flujo():
    from app.services import valuation_service

    guard = getattr(valuation_service, "_assert_no_lookahead_guard", None)
    if guard is None:
        pytest.skip("_assert_no_lookahead_guard no existe en valuation_service")
    assert guard({"trace": {"price_date": "2999-01-01"}}) is None


# ------------------------------------------------------------ (f) vendors


def _scrub_provider_keys(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    settings = get_settings()
    monkeypatch.setattr(settings, "finnhub_api_key", None)
    monkeypatch.setattr(settings, "fmp_api_key", None)
    return settings


def test_f_finnhub_resuelve_por_env(monkeypatch):
    from app.core.config import get_settings

    settings = _scrub_provider_keys(monkeypatch)
    assert FinnhubClient().configured() is False
    with pytest.raises(RuntimeError, match="FINNHUB_API_KEY"):
        run(FinnhubClient().quote("AAPL"))
    monkeypatch.setattr(settings, "finnhub_api_key", "test-key")
    assert FinnhubClient().configured() is True
    get_settings.cache_clear()


def test_f_fmp_resuelve_por_env(monkeypatch):
    from app.core.config import get_settings

    settings = _scrub_provider_keys(monkeypatch)
    assert FMPClient().configured() is False
    monkeypatch.setattr(settings, "fmp_api_key", "test-key")
    assert FMPClient().configured() is True
    get_settings.cache_clear()


def test_f_sin_claves_no_hay_vendor_yahoo_sigue_disponible(monkeypatch):
    from app.services.market_refresh_service import PublicPriceProvider

    _scrub_provider_keys(monkeypatch)
    provider = PublicPriceProvider()

    async def probe():
        company = SimpleNamespace(ticker="ACME")
        return await provider.fetch([company], as_of=date(2024, 1, 2))

    observations, errors = run(probe())
    assert observations == {}
    assert errors and errors[0]["reason"] == "no_price_provider_configured"

    from app.api.routes import market as market_route

    def handler(request: httpx.Request) -> httpx.Response:
        payload = {
            "chart": {
                "result": [
                    {"indicators": {"quote": [{"close": [100.0, 102.0]}]}}
                ]
            }
        }
        return httpx.Response(200, json=payload, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        quote = market_route._fetch_index(client, "^GSPC")
    finally:
        client.close()
    assert quote and quote["price"] == pytest.approx(102.0)

    def failing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={}, request=request)

    client = httpx.Client(transport=httpx.MockTransport(failing))
    try:
        assert market_route._fetch_index(client, "^GSPC") is None
    finally:
        client.close()


# ------------------------------------------------------------- (g) debate


class _FailingLLM:
    name = "failing-stub"

    def __init__(self):
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        raise RuntimeError("LLM down")


def _debate_module():
    try:
        return importlib.import_module("app.services.thesis_debate_service")
    except ImportError:
        pytest.skip("app.services.thesis_debate_service no existe en el arbol")


def test_g_debate_degrada_sin_llm_sin_excepcion():
    debate = _debate_module()
    result = run(
        debate.debate_thesis(
            "ACME",
            "Tesis con crecimiento y moat, pero con riesgo de deuda.",
            provider=_FailingLLM(),
        )
    )
    assert result["degraded"] is True
    assert result["llm_calls"] == 0
    assert result["verdict"] in {"bullish", "bearish", "neutral"}
    assert result["model"] == "deterministic"
    assert result["bull_case"] and result["bear_case"]


def test_g_veredicto_determinista_bearish_ante_riesgo():
    debate = _debate_module()
    result = run(
        debate.debate_thesis(
            "ACME",
            "riesgo deuda perdida litigio fraude demanda debil",
            provider=_FailingLLM(),
        )
    )
    assert result["verdict"] == "bearish"


def _chat_service_and_baseline(provider):
    try:
        from app.services.chat_synthesis_service import ChatSynthesisService
    except ImportError:
        pytest.skip("chat_synthesis_service no existe en el arbol")
    if not hasattr(ChatSynthesisService, "_maybe_attach_debate"):
        pytest.skip("hook _maybe_attach_debate no existe en chat_synthesis_service")
    svc = ChatSynthesisService.__new__(ChatSynthesisService)
    svc.provider = provider
    baseline = SimpleNamespace(sources=[], answer="tesis de prueba", llm_trace={})
    return svc, baseline


def test_g_hook_chat_apagado_no_adjunta_ni_llama_llm():
    provider = _FailingLLM()
    svc, baseline = _chat_service_and_baseline(provider)
    run(svc._maybe_attach_debate(baseline, "ACME", False))
    assert "thesis_debate" not in baseline.llm_trace
    assert provider.calls == 0


def test_g_hook_chat_encendido_adjunta_debate_degradado():
    provider = _FailingLLM()
    svc, baseline = _chat_service_and_baseline(provider)
    run(svc._maybe_attach_debate(baseline, "ACME", True))
    assert baseline.llm_trace["thesis_debate"]["degraded"] is True
    run(svc._maybe_attach_debate(baseline, None, True))
    assert provider.calls == 3  # sin ticker no hay cuarta llamada
