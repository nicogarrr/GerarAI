"""Servicio de senales DCA: watchlist + cartera, upsert de estado y dedup de avisos."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import (
    Base,
    Company,
    DcaAlertOverride,
    DcaSignalState,
    Position,
    ResearchAlert,
    Tenant,
    WatchItem,
)
from app.services import dca_signal_service as svc
from app.services.dca_signal_engine import DcaParams
from app.services.dca_signal_service import (
    FetchedHistory,
    PriceRow,
    alert_direction,
    build_bars,
    evaluate_watchlist,
    should_alert,
)

# Parametros fijos para el test (los umbrales del motor se optimizan aparte).
PARAMS = DcaParams(signal="drawdown", dd_thresholds=(0.15, 0.25, 0.40), min_months=12, version="test-v1")
NOW = datetime(2026, 10, 27, 23, 30, tzinfo=UTC)


def _months(n: int, end_year: int = 2026, end_month: int = 10) -> list[tuple[int, int]]:
    out = []
    y, m = end_year, end_month
    for _ in range(n):
        out.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(out))


def series(last_close: float, *, months: int = 30, base: float = 100.0, end=(2026, 10)) -> list[PriceRow]:
    """30 meses planos en ``base`` y el ultimo mes cerrando en ``last_close``."""
    keys = _months(months, *end)
    rows = [PriceRow(day=date(y, m, 15), close=base, adj_close=None) for y, m in keys[:-1]]
    y, m = keys[-1]
    rows.append(PriceRow(day=date(y, m, 15), close=last_close, adj_close=None))
    return rows


class FakeFetcher:
    def __init__(self):
        self.data: dict[str, FetchedHistory] = {}
        self.calls: list[str] = []

    def set(self, symbol: str, rows: list[PriceRow], currency: str | None = "USD"):
        self.data[symbol] = FetchedHistory(rows=rows, currency=currency)

    def __call__(self, symbol: str) -> FetchedHistory:
        self.calls.append(symbol)
        if symbol not in self.data:
            raise RuntimeError("sin datos")
        return self.data[symbol]


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setenv("DCA_ALERT_MIN_LEVEL", "2")
    monkeypatch.setenv("DCA_ALERT_TRIMS", "false")
    monkeypatch.setenv("DCA_ALERTS_ENABLED", "true")
    monkeypatch.setenv("DCA_ALERT_CHANNELS", "in_app,email")
    get_settings.cache_clear()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Tenant(id=1, external_id="t-dca", name="t"))
        session.commit()
        session.info["tenant_id"] = 1
        session.info["user_id"] = "u-1"
        yield session


def _company(db, ticker, *, currency="USD", exchange="NASDAQ", name=None):
    company = Company(
        ticker=ticker, name=name or f"{ticker} Inc", exchange=exchange, currency=currency,
        sector="x", industry="x", company_type="x", valuation_model="x",
        special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.flush()
    return company


def _watch(db, symbol):
    db.add(WatchItem(tenant_id=1, symbol=symbol))
    db.commit()


def _run(db, fetcher):
    return evaluate_watchlist(db, fetcher=fetcher, now=NOW, today=date(2026, 10, 27), params=PARAMS)


def _alerts(db) -> list[ResearchAlert]:
    return list(db.scalars(select(ResearchAlert).where(ResearchAlert.alert_type == "dca_level").order_by(ResearchAlert.id)))


def _state(db, symbol) -> DcaSignalState:
    row = db.scalar(select(DcaSignalState).where(DcaSignalState.symbol == symbol))
    assert row is not None
    return row


@pytest.mark.parametrize(
    ("level", "previous", "min_level", "trims", "expected"),
    [
        (2, None, 2, False, False),  # primera evaluacion: solo siembra
        (4, None, 2, False, False),
        (-2, None, 2, True, False),
        (1, None, 2, False, False),
        (3, 3, 2, False, False),  # mismo nivel
        (-2, -2, 2, True, False),
        (4, 3, 2, False, True),  # subidas
        (3, 1, 2, False, True),
        (2, 1, 3, False, False),  # subida por debajo del minimo
        (2, 3, 2, False, True),  # bajadas: avisan (informativas)
        (2, 4, 2, False, True),
        (1, 2, 2, False, True),  # sale de zona de compra
        (1, 2, 1, False, True),
        (2, 3, 4, False, False),  # bajada desde un nivel por debajo del minimo
        (3, 4, 4, False, True),
        (4, 1, 0, False, False),  # ajuste 0 = sin avisos, en las dos direcciones
        (1, 3, 0, False, False),
        (-1, 1, 2, False, False),  # compra -> recorte solo con recortes
        (-1, 1, 2, True, True),
        (-2, -1, 2, True, True),  # ligero -> fuerte
        (-1, -2, 2, True, True),  # fuerte -> ligero: bajada
        (-1, -2, 2, False, False),
        (1, -1, 2, True, True),  # recorte -> 1X: bajada
        (1, -2, 2, True, True),
        (1, -1, 2, False, False),
        (2, -1, 2, False, True),  # recorte -> 2X: entra en zona de compra
        (2, -1, 3, False, False),
        (2, -1, 3, True, True),
        (-2, 1, 0, True, False),
    ],
)
def test_should_alert_rules(level, previous, min_level, trims, expected):
    assert should_alert(level=level, previous_level=previous, min_level=min_level, trims_enabled=trims) is expected


@pytest.mark.parametrize(
    ("level", "previous", "expected"),
    [
        (2, None, None),
        (3, 3, None),
        (3, 2, "up"),
        (2, 3, "down"),
        (1, 2, "down"),
        (-1, 1, "up"),
        (-2, -1, "up"),
        (-1, -2, "down"),
        (1, -1, "down"),
        (2, -1, "up"),
    ],
)
def test_alert_direction(level, previous, expected):
    assert alert_direction(level, previous) == expected


def test_first_evaluation_seeds_state_without_alert(db):
    _watch(db, "UBER")
    _watch(db, "AAPL")
    fetcher = FakeFetcher()
    fetcher.set("UBER", series(70.0))  # caida 30 % -> 3X, pero es la primera vez
    fetcher.set("AAPL", series(100.0))  # 1X
    summary = _run(db, fetcher)
    assert summary["evaluated"] == 2
    assert summary["alerted"] == []
    assert _alerts(db) == []
    uber = _state(db, "UBER")
    assert (uber.level, uber.last_alerted_level) == (3, None)
    assert uber.sources == ["watchlist"]
    assert _state(db, "AAPL").last_alerted_level is None


def test_escalation_after_seed_alerts_with_details(db):
    _watch(db, "UBER")
    fetcher = FakeFetcher()
    fetcher.set("UBER", series(80.0))  # 2X: siembra
    _run(db, fetcher)
    fetcher.set("UBER", series(70.0))  # sube a 3X: avisa
    _run(db, fetcher)
    alerts = _alerts(db)
    assert [a.title for a in alerts] == ["UBER entró en 3X DCA"]
    assert alerts[0].severity == "high"
    assert alerts[0].channels == ["in_app", "email"]
    dca = alerts[0].metadata_["dca"]
    assert dca["status"] == "forming" and dca["period"] == "2026-10"
    assert dca["previous_level"] == 2
    assert "Caída desde máximo 36m: 30,0 %" in alerts[0].message
    uber = _state(db, "UBER")
    assert (uber.level, uber.last_alerted_level, uber.last_alerted_period) == (3, 3, "2026-10")


def test_same_level_rerun_and_flicker_do_not_realert(db):
    _watch(db, "UBER")
    fetcher = FakeFetcher()
    fetcher.set("UBER", series(80.0))  # 2X: siembra
    _run(db, fetcher)
    fetcher.set("UBER", series(70.0))  # 3X: avisa
    _run(db, fetcher)
    _run(db, fetcher)  # mismo nivel: nada
    assert len(_alerts(db)) == 1
    fetcher.set("UBER", series(80.0))  # baja a 2X: aviso informativo
    _run(db, fetcher)
    _run(db, fetcher)  # sigue en 2X: nada
    fetcher.set("UBER", series(70.0))  # vuelve a 3X en el mismo mes: huella ya existe
    _run(db, fetcher)
    fetcher.set("UBER", series(80.0))  # y otra vez a 2X: huella de bajada ya existe
    _run(db, fetcher)
    titles = [a.title for a in _alerts(db)]
    assert titles == ["UBER entró en 3X DCA"]
    state = _state(db, "UBER")
    assert state.level == 2 and state.previous_level == 3


def test_drop_alerts_as_informational(db):
    _watch(db, "UBER")
    fetcher = FakeFetcher()
    fetcher.set("UBER", series(70.0))  # 3X: siembra
    _run(db, fetcher)
    fetcher.set("UBER", series(80.0))  # baja a 2X
    summary = _run(db, fetcher)
    assert summary["alerted"] == []
    fetcher.set("UBER", series(100.0))  # baja a 1X: sale de zona de compra
    _run(db, fetcher)
    alerts = _alerts(db)
    assert [a.title for a in alerts] == ["UBER baja a 1X DCA (desde 2X DCA)"]
    assert [a.severity for a in alerts] == ["low"]
    dca = alerts[0].metadata_["dca"]
    assert (dca["direction"], dca["informational"], dca["previous_level"]) == ("down", True, 2)
    assert dca["previous_label"] == "2X DCA"
    assert alerts[0].message.splitlines()[2] == "Aviso informativo: el nivel baja desde 2X DCA a 1X DCA."
    uber = _state(db, "UBER")
    assert (uber.level, uber.last_alerted_level) == (1, 1)


def test_rise_after_drop_to_same_level_still_alerts(db):
    """Con 3X/1X no se avisa de 3->2 ni 1->2, solo de 2->1."""
    _watch(db, "UBER")
    fetcher = FakeFetcher()
    fetcher.set("UBER", series(70.0))  # 3X: siembra
    _run(db, fetcher)
    fetcher.set("UBER", series(80.0))  # baja a 2X
    _run(db, fetcher)
    fetcher.set("UBER", series(100.0))  # baja a 1X
    _run(db, fetcher)
    fetcher.set("UBER", series(80.0))  # sube a 2X
    _run(db, fetcher)
    alerts = _alerts(db)
    assert [a.metadata_["dca"]["direction"] for a in alerts] == ["down"]
    assert alerts[-1].title == "UBER baja a 1X DCA (desde 2X DCA)" and alerts[-1].severity == "low"


def test_drop_email_marks_direction():
    from app.services.dca_alert_copy import email_content

    dca = {
        "symbol": "UBER", "label": "2X DCA", "previous_label": "3X DCA", "direction": "down",
        "zone": "Zona de compra", "status": "confirmed", "color": "#00AA78", "fg": "#FFFFFF",
    }
    content = email_content(dca)
    assert content.subject == "UBER baja a 2X DCA (desde 3X DCA)"
    assert "Aviso informativo: el nivel baja desde 3X DCA a 2X DCA." in content.html
    up = email_content({**dca, "direction": "up"})
    assert up.subject == "UBER entró en 2X DCA" and "Aviso informativo" not in up.html


def test_escalation_alerts_again(db):
    _watch(db, "UBER")
    fetcher = FakeFetcher()
    fetcher.set("UBER", series(100.0))  # 1X: siembra
    _run(db, fetcher)
    fetcher.set("UBER", series(80.0))
    _run(db, fetcher)
    fetcher.set("UBER", series(70.0))
    _run(db, fetcher)
    fetcher.set("UBER", series(55.0))
    _run(db, fetcher)
    alerts = _alerts(db)
    assert [a.title for a in alerts] == ["UBER entró en 3X DCA", "UBER entró en 4X DCA"]
    assert alerts[-1].severity == "critical"


def test_new_month_same_level_does_not_realert(db):
    _watch(db, "UBER")
    fetcher = FakeFetcher()
    sept_now = datetime(2026, 9, 30, 23, 0, tzinfo=UTC)
    fetcher.set("UBER", series(100.0, end=(2026, 9)) + [PriceRow(day=date(2026, 9, 29), close=100.0)])
    evaluate_watchlist(db, fetcher=fetcher, now=sept_now, today=date(2026, 9, 30), params=PARAMS)  # 1X: siembra
    fetcher.set("UBER", series(70.0, end=(2026, 9)) + [PriceRow(day=date(2026, 9, 29), close=70.0)])
    evaluate_watchlist(db, fetcher=fetcher, now=sept_now, today=date(2026, 9, 30), params=PARAMS)  # 3X: avisa
    assert len(_alerts(db)) == 1
    rows = series(70.0, end=(2026, 9)) + [PriceRow(day=date(2026, 10, 15), close=70.0)]
    fetcher.set("UBER", rows)
    _run(db, fetcher)
    assert len(_alerts(db)) == 1
    assert _state(db, "UBER").period == "2026-10"


def test_per_ticker_override_zero_and_none(db):
    _watch(db, "UBER")
    _watch(db, "HIMS")
    db.add(DcaAlertOverride(tenant_id=1, symbol="UBER", min_level=0))
    db.add(DcaAlertOverride(tenant_id=1, symbol="HIMS", min_level=4))
    db.commit()
    fetcher = FakeFetcher()
    fetcher.set("UBER", series(55.0))  # 4X, pero avisos apagados
    fetcher.set("HIMS", series(70.0))  # 3X < minimo 4
    _run(db, fetcher)
    assert _alerts(db) == []
    # Sin ajuste (None) vuelve al global (2): HIMS a 2X ya no avisa porque no cambia a >= 2
    db.query(DcaAlertOverride).filter(DcaAlertOverride.symbol == "HIMS").delete()
    db.commit()
    fetcher.set("HIMS", series(55.0))
    _run(db, fetcher)
    assert [a.title for a in _alerts(db)] == ["HIMS entró en 4X DCA"]


def test_trims_only_with_flag(db, monkeypatch):
    _watch(db, "NVDA")
    fetcher = FakeFetcher()
    rising = [PriceRow(day=date(y, m, 15), close=10.0 * (1.15 ** i)) for i, (y, m) in enumerate(_months(30))]
    fetcher.set("NVDA", rising)
    _run(db, fetcher)
    assert _state(db, "NVDA").level < 0
    assert _alerts(db) == []
    # Con el flag, un cambio a recorte si avisa.
    monkeypatch.setenv("DCA_ALERT_TRIMS", "true")
    get_settings.cache_clear()
    nvda = _state(db, "NVDA")
    nvda.level = 1  # venia de 1X
    db.commit()
    _run(db, fetcher)
    alerts = _alerts(db)
    assert len(alerts) == 1 and "RECORTE" in alerts[0].title
    assert alerts[0].severity == "low"
    # Volver de recorte a 1X tambien avisa (bajada informativa).
    trim_label = alerts[0].metadata_["dca"]["label"]
    fetcher.set("NVDA", series(100.0))  # serie plana: 1X
    _run(db, fetcher)
    assert _state(db, "NVDA").level == 1
    alerts = _alerts(db)
    assert len(alerts) == 2
    assert alerts[-1].title == f"NVDA baja a 1X DCA (desde {trim_label})"
    assert alerts[-1].metadata_["dca"]["direction"] == "down"


def test_portfolio_and_watchlist_union_with_currency(db):
    company = _company(db, "CGEO.L", currency="GBP", exchange="LSE", name="Georgia Capital")
    held = _company(db, "UBER", name="Uber Technologies")
    db.add(Position(tenant_id=1, company_id=held.id, quantity=Decimal("10")))
    db.add(Position(tenant_id=1, company_id=company.id, quantity=Decimal("0")))
    db.commit()
    _watch(db, "CGEO.L")
    _watch(db, "UBER")
    fetcher = FakeFetcher()
    fetcher.set("CGEO.L", series(1300.0, base=1300.0), currency="GBp")
    fetcher.set("UBER", series(100.0))  # 1X: siembra
    _run(db, fetcher)
    fetcher.set("UBER", series(70.0))
    _run(db, fetcher)
    uber = _state(db, "UBER")
    assert uber.sources == ["watchlist", "portfolio"]
    cgeo = _state(db, "CGEO.L")
    assert cgeo.sources == ["watchlist"]
    assert cgeo.currency == "GBp"  # la divisa real del listado (peniques), no GBP
    alert = _alerts(db)[0]
    assert "Uber Technologies" in alert.message
    assert "Origen: watchlist + cartera" in alert.message


def test_insufficient_history_is_skipped_never_invented(db):
    _watch(db, "NEWCO")
    fetcher = FakeFetcher()
    fetcher.set("NEWCO", series(50.0, months=6))
    summary = _run(db, fetcher)
    assert summary["evaluated"] == 0
    assert summary["skipped"] == [{"symbol": "NEWCO", "reason": "historia_insuficiente", "daily_bars": 6}]
    assert db.scalar(select(DcaSignalState)) is None


def test_fetch_error_falls_back_to_market_prices(db):
    from app.models.entities import MarketPrice

    company = _company(db, "KKR")
    for row in series(70.0):
        db.add(MarketPrice(company_id=company.id, date=row.day, close=Decimal(str(row.close)), source="seed"))
    db.commit()
    _watch(db, "KKR")
    summary = _run(db, FakeFetcher())  # Yahoo falla para todos
    assert summary["errors"] == [{"symbol": "KKR", "error": "RuntimeError"}]
    state = _state(db, "KKR")
    assert state.data_source == "market_prices" and state.level == 3


def test_unsettled_today_bar_is_ignored(db):
    _watch(db, "UBER")
    fetcher = FakeFetcher()
    rows = series(100.0, end=(2026, 10)) + [PriceRow(day=date(2026, 10, 27), close=55.0)]
    fetcher.set("UBER", rows)
    # 14:00 NY: la sesion sigue abierta, la barra de hoy no cuenta.
    evaluate_watchlist(db, fetcher=fetcher, now=datetime(2026, 10, 27, 18, 0, tzinfo=UTC),
                       today=date(2026, 10, 27), params=PARAMS)
    assert _state(db, "UBER").level == 1


def test_adjusted_series_reports_real_close(db):
    _watch(db, "MSFT")
    fetcher = FakeFetcher()
    rows = [PriceRow(day=r.day, close=r.close, adj_close=r.close * 0.5) for r in series(70.0)]
    fetcher.set("MSFT", rows)
    _run(db, fetcher)
    state = _state(db, "MSFT")
    assert float(state.close) == 70.0
    assert state.level_prices["2x"] == pytest.approx(85.0)


def test_build_bars_one_row_without_adj_close_keeps_adjusted_series():
    # Split 10:1 a mitad de serie: el ajustado es continuo, el bruto cae un 90 %.
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(6)]
    rows = [
        PriceRow(day=days[0], close=1000.0, adj_close=100.0),
        PriceRow(day=days[1], close=1000.0, adj_close=None),  # fila suelta sin ajuste
        PriceRow(day=days[2], close=1000.0, adj_close=100.0),
        PriceRow(day=days[3], close=100.0, adj_close=100.0),  # tras el split
        PriceRow(day=days[4], close=99.0, adj_close=99.0),
        PriceRow(day=days[5], close=98.0, adj_close=None),  # ultimo cierre aun sin ajuste
    ]
    bars, factor = build_bars(rows)
    closes = [b.close for b in bars]
    assert min(closes) >= 98.0  # ningun desplome del 90 %
    assert [b.day for b in bars] == [days[0], days[2], days[3], days[4], days[5]]
    assert closes[-1] == pytest.approx(98.0)
    assert factor == pytest.approx(1.0)


def test_build_bars_trailing_raw_rows_use_last_adjustment_factor():
    rows = [
        PriceRow(day=date(2026, 1, 1), close=200.0, adj_close=100.0),
        PriceRow(day=date(2026, 1, 2), close=210.0, adj_close=None),
    ]
    bars, factor = build_bars(rows)
    assert [b.close for b in bars] == [pytest.approx(100.0), pytest.approx(105.0)]
    assert factor == pytest.approx(2.0)


def test_build_bars_without_any_adj_close_uses_raw_closes():
    rows = [PriceRow(day=date(2026, 1, 1), close=10.0), PriceRow(day=date(2026, 1, 2), close=11.0)]
    bars, factor = build_bars(rows)
    assert [b.close for b in bars] == [10.0, 11.0]
    assert factor == 1.0


def test_untracked_states_are_removed(db):
    _watch(db, "UBER")
    fetcher = FakeFetcher()
    fetcher.set("UBER", series(100.0))
    _run(db, fetcher)
    db.query(WatchItem).delete()
    db.commit()
    _run(db, fetcher)
    assert db.scalar(select(DcaSignalState)) is None


def test_alerts_disabled_still_updates_state(db, monkeypatch):
    monkeypatch.setenv("DCA_ALERTS_ENABLED", "false")
    get_settings.cache_clear()
    _watch(db, "UBER")
    fetcher = FakeFetcher()
    fetcher.set("UBER", series(55.0))
    summary = _run(db, fetcher)
    assert summary["alerts_enabled"] is False
    assert _state(db, "UBER").level == 4
    assert _alerts(db) == []


def test_actor_with_alerts_disabled_persists_levels_and_sends_no_email(db, monkeypatch):
    """Extremo a extremo por el actor diario con los avisos apagados.

    Es el default de la rama ``corr/dca-defaults-off`` (DCA_ALERTS_ENABLED=false
    y sin correo): la evaluacion tiene que guardar el nivel (UBER cae un 45 %
    -> 4X) y no debe salir ningun aviso ni ningun correo.
    """
    from app.services.notification_service import NotificationService
    from app.workers import dramatiq_app

    monkeypatch.setenv("DCA_ALERTS_ENABLED", "false")
    get_settings.cache_clear()
    _watch(db, "UBER")
    fetcher = FakeFetcher()
    fetcher.set("UBER", series(55.0))
    real_evaluate = svc.evaluate_watchlist
    dispatched: list[int] = []
    monkeypatch.setattr(
        svc, "evaluate_watchlist", lambda session: real_evaluate(
            session, fetcher=fetcher, now=NOW, today=date(2026, 10, 27), params=PARAMS
        )
    )
    monkeypatch.setattr(NotificationService, "dispatch", lambda self, session, alert: dispatched.append(alert.id) or {})
    monkeypatch.setattr(dramatiq_app, "_session", lambda tenant_id, user_id: db)
    monkeypatch.setattr(dramatiq_app, "acquire_job_lease", lambda name, **kw: "tok")
    monkeypatch.setattr(dramatiq_app, "release_job_lease", lambda name, token, **kw: None)

    out = dramatiq_app.evaluate_dca_signals.fn(1, "u-1")

    assert out["status"] == "ok"
    assert out["evaluated"] == 1 and out["alerted"] == [] and out["alerts_enabled"] is False
    state = _state(db, "UBER")
    assert state.level == 4 and state.period == "2026-10"
    assert state.last_alerted_level is None
    assert _alerts(db) == []
    # Ningun canal (in_app, email, Telegram) se despacha: todo pasa por dispatch.
    assert dispatched == []


def test_tracked_symbols_dedups(db):
    company = _company(db, "ASTS")
    db.add(Position(tenant_id=1, company_id=company.id, quantity=Decimal("5")))
    db.add(Position(tenant_id=1, company_id=company.id, quantity=Decimal("3")))
    db.commit()
    _watch(db, "asts")
    tracked = svc.tracked_symbols(db)
    assert list(tracked) == ["ASTS"]
    assert tracked["ASTS"].sources == ["watchlist", "portfolio"]
    assert tracked["ASTS"].company is not None


def test_selected_symbols_only_fetch_selected_without_deleting_others(db):
    _company(db, 'MANUALA'); _watch(db, 'MANUALA')
    _company(db, 'MANUALB'); _watch(db, 'MANUALB')
    fetcher = FakeFetcher()
    fetcher.set('MANUALA', series(55)); fetcher.set('MANUALB', series(55))
    evaluate_watchlist(db, fetcher=fetcher, now=NOW, today=NOW.date(), params=PARAMS, symbols={'MANUALA'})
    assert fetcher.calls == ['MANUALA']
    assert db.scalar(select(DcaSignalState).where(DcaSignalState.symbol == 'MANUALB')) is None
    from app.services.dca_manual import pending_symbols
    from app.services.dca_signal_engine import DEFAULT_PARAMS
    state = _state(db, 'MANUALA'); state.params_version = DEFAULT_PARAMS.version
    db.commit()
    assert pending_symbols(db, now=NOW) == ['MANUALB']
    assert set(pending_symbols(db, now=NOW + timedelta(hours=25))) == {'MANUALA', 'MANUALB'}


def test_tenant_directions_ignore_legacy_override_and_saved_policy_wins(db):
    from app.services.dca_alert_settings_service import save_policy
    _watch(db, "UBER")
    db.add(DcaAlertOverride(tenant_id=1, symbol="UBER", min_level=0))
    db.commit()
    fetcher = FakeFetcher()
    fetcher.set("UBER", series(80.0))  # 2X, first evaluation: no alert
    assert _run(db, fetcher)["alerted"] == []
    fetcher.set("UBER", series(70.0))  # default destination 3X: alert despite old OFF
    assert [a["level"] for a in _run(db, fetcher)["alerted"]] == [3]
    save_policy(db, 4, 2)
    fetcher.set("UBER", series(80.0))  # saved down threshold 2X
    assert [a["level"] for a in _run(db, fetcher)["alerted"]] == [2]
    fetcher.set("UBER", series(70.0))  # saved up threshold 4X: no alert
    assert _run(db, fetcher)["alerted"] == []
    assert db.scalar(select(DcaAlertOverride).where(DcaAlertOverride.symbol == "UBER")).min_level == 0


def test_market_prices_fallback_keeps_the_declared_unit_not_company_currency(db):
    """Cierres de respaldo en peniques: la etiqueta es la unidad de las filas.

    Antes el estado se etiquetaba con company.currency (GBP) y un cierre de
    70 peniques se mostraba como «70,00 GBP» (x100) en UI y correo.
    """
    from app.models.entities import MarketPrice

    company = _company(db, "CGEO.L", currency="GBP", exchange="LSE", name="Georgia Capital")
    for row in series(70.0):
        db.add(
            MarketPrice(
                company_id=company.id,
                date=row.day,
                close=Decimal(str(row.close)),
                source="seed",
                quote_currency="GBp",
            )
        )
    db.commit()
    _watch(db, "CGEO.L")
    _run(db, FakeFetcher())  # Yahoo falla: solo respaldo
    state = _state(db, "CGEO.L")
    assert state.data_source == "market_prices"
    assert state.currency == "GBp"
    assert float(state.close) == 70.0


def test_stored_v1_state_is_refreshed_to_v2_and_pending_only_until_then(db):
    """Reproduce el estado de prod del 31-oct-2026: estados privados nico-v1.

    Tras un cambio de formula: (1) la cola manual marca el estado como
    pendiente AUNQUE tenga <24h y no haya cierre nuevo (la version antigua es
    motivo suficiente: el boton procesa solo lo desactualizado), y (2) la
    siguiente evaluacion re-escribe la MISMA fila con la version vigente, sin
    saltarsela por fresca y sin duplicar filas.
    """
    from app.services.dca_manual import pending_symbols
    from app.services.dca_signal_engine import DEFAULT_PARAMS, NICO_V1_PARAMS

    _company(db, 'VERST')
    _watch(db, 'VERST')
    fetcher = FakeFetcher()
    fetcher.set('VERST', series(80.0))
    # Estado persistido con la formula anterior, como quedo en prod.
    evaluate_watchlist(db, fetcher=fetcher, now=NOW, today=NOW.date(), params=NICO_V1_PARAMS)
    state = _state(db, 'VERST')
    assert state.params_version == 'nico-v1'
    # Fresco (<24h, sin cierre nuevo): pendiente SOLO por version antigua.
    assert pending_symbols(db, now=NOW + timedelta(hours=1)) == ['VERST']
    # La siguiente evaluacion (diaria o manual) re-escribe la misma fila a v2.
    later = NOW + timedelta(hours=2)
    evaluate_watchlist(db, fetcher=fetcher, now=later, today=later.date(), params=DEFAULT_PARAMS)
    rows = list(db.scalars(select(DcaSignalState).where(DcaSignalState.symbol == 'VERST')))
    assert len(rows) == 1
    state = rows[0]
    assert state.params_version == DEFAULT_PARAMS.version == 'nico-v2'
    evaluated = state.evaluated_at
    assert (evaluated if evaluated.tzinfo else evaluated.replace(tzinfo=UTC)) == later
    assert state.hit_rates['params_version'] == 'nico-v2'
    # Ya evaluado con la formula vigente: sale de la cola (solo lo desactualizado).
    assert pending_symbols(db, now=later + timedelta(hours=1)) == []
