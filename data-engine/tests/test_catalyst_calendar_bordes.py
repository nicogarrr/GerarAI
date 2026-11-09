"""Bordes de ``app.services.catalyst_calendar_service``.

Lo que demuestra:
- ``_next_period_end`` sin informe posterior al de referencia (emisores de
  52/53 semanas sin siguiente): devuelve None, no inventa (145).
- ``filing_deadline_event`` salta ``reportDate`` no parseables (rama
  175->171) y sigue con los validos.
- ``fetch_filing_deadlines`` con conjunto de tickers vacio devuelve ok sin
  eventos ni errores y sin tocar red (250).
- ``_parse_us_date`` devuelve None ante fechas imposibles en ambos
  formatos (432-433).
- ``build_catalysts``: ex-dividendo NASDAQ fuera de rango o sin fecha se
  omite (496); sin ``payment_date`` el detalle queda solo con el importe
  (rama 500->503); registro ingerido de empresa no seguida se omite (521);
  accion corporativa fuera de cartera/rango o sin fecha se omite (561).

Funciones puras; sin red; sin BD.
"""

import asyncio
from datetime import date

from app.services import catalyst_calendar_service as svc


def test_next_period_end_sin_siguiente_devuelve_none():
    # 52/53 semanas: el cierre de referencia es el ultimo presentado;
    # no hay informe posterior al que sumar 364 dias.
    periods = [date(2024, 1, 26), date(2024, 2, 10), date(2025, 2, 7)]
    assert svc._next_period_end(periods) is None


def test_filing_deadline_salta_report_dates_imposibles():
    submissions = {
        "fiscalYearEnd": "1231",
        "filings": {
            "recent": {
                "form": ["10-Q", "10-Q", "10-Q"],
                "reportDate": ["no-fecha", "2025-06-30", "2025-03-31"],
            }
        },
    }
    result = svc.filing_deadline_event(submissions, "abc")
    assert result is not None
    assert result["ticker"] == "ABC"
    assert result["type"] == "filing_deadline"
    assert result["title"] == "Plazo para presentar el 10-Q"


def test_fetch_filing_deadlines_sin_tickers(monkeypatch):
    def _no_fetchers():
        raise AssertionError("no debe construir fetchers sin tickers")

    monkeypatch.setattr(svc, "_default_sec_fetchers", _no_fetchers)
    result = asyncio.run(svc.fetch_filing_deadlines(set(), date(2025, 1, 1), date(2025, 12, 31)))
    assert result == {"status": "ok", "events": [], "errors": []}


def test_parse_us_date_imposible_devuelve_none():
    assert svc._parse_us_date("2025-13-45") is None
    assert svc._parse_us_date("13/45/2025") is None
    assert svc._parse_us_date("29/02/2025") is None


def test_dividendo_nasdaq_fuera_de_rango_o_sin_fecha_se_omite():
    events = svc.build_catalysts(
        held={"AAPL"},
        held_us={"AAPL"},
        desde=date(2025, 1, 1),
        hasta=date(2025, 12, 31),
        earnings=[],
        dividends=[
            {"symbol": "AAPL", "ex_date": "2026-06-01", "amount": 0.25},
            {"symbol": "AAPL", "ex_date": "no-fecha", "amount": 0.25},
        ],
        actions=[],
    )
    assert events == []


def test_dividendo_nasdaq_sin_fecha_de_pago():
    events = svc.build_catalysts(
        held={"AAPL"},
        held_us={"AAPL"},
        desde=date(2025, 1, 1),
        hasta=date(2025, 12, 31),
        earnings=[],
        dividends=[{"symbol": "AAPL", "ex_date": "2025-06-02", "amount": 0.25}],
        actions=[],
    )
    assert events == [
        {
            "date": "2025-06-02",
            "ticker": "AAPL",
            "type": "dividend_ex",
            "title": "Fecha ex-dividendo",
            "detail": "0,2500 por acción",
            "source": svc.SOURCE_NASDAQ,
            "origin": "cartera",
        }
    ]


def test_registro_ingerido_de_empresa_no_seguida_se_omite():
    events = svc.build_catalysts(
        held={"AAPL"},
        held_us=set(),
        desde=date(2025, 1, 1),
        hasta=date(2025, 12, 31),
        earnings=[],
        dividends=[],
        actions=[],
        records=[
            {
                "ticker": "OTRO",
                "amount": 1.0,
                "currency": "EUR",
                "ex_date": "2025-06-02",
                "pay_date": "2025-06-20",
                "source": "x",
            }
        ],
    )
    assert events == []


def test_accion_corporativa_omitida():
    events = svc.build_catalysts(
        held={"AAPL"},
        held_us=set(),
        desde=date(2025, 1, 1),
        hasta=date(2025, 12, 31),
        earnings=[],
        dividends=[],
        actions=[
            {"ticker": "OTRO", "effective_date": "2025-06-02", "action_type": "split"},
            {"ticker": "AAPL", "effective_date": "no-fecha", "action_type": "split"},
            {"ticker": "AAPL", "effective_date": "2026-06-02", "action_type": "split"},
        ],
    )
    assert events == []
