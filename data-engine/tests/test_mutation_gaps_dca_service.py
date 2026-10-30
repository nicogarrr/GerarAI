"""Supervivientes de mutmut en ``dca_signal_service`` (ronda 2).

Fija lo que un mutante podia cambiar sin que ningun test fallase: el historico
de respaldo desde MarketPrice (orden, cierres 0, adj_close, divisa), la forma
del payload ``dca`` que leen el email y la UI, la deduplicacion por huella
(con la huella propia de las bajadas), las filas de entrega por canal externo
y el resumen de ``_dispatch_alert``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models.entities import AlertDelivery, MarketPrice, ResearchAlert
from app.services import dca_signal_service as svc
from app.services.dca_signal_engine import MonthlyVerdict
from tests.test_dca_signal_service import (  # noqa: F401  (fixture db)
    PARAMS,
    FakeFetcher,
    _alerts,
    _company,
    _run,
    _watch,
    db,
    series,
)


def _price(db, company, day, close, adj=None, quote=None):
    value = None if close is None else Decimal(str(close))
    db.add(MarketPrice(
        company_id=company.id, date=day, open=value, high=value, low=value,
        close=value, adj_close=None if adj is None else Decimal(str(adj)),
        volume=10, source="test", quote_currency=quote,
    ))


def test_db_history_ordenado_sin_cierres_no_positivos_y_con_divisa(db):
    company = _company(db, "CGEO.L", currency="GBp", exchange="LSE")
    _price(db, company, date(2026, 10, 3), 0.5, adj=0.25)
    _price(db, company, date(2026, 10, 1), 2.0)
    _price(db, company, date(2026, 10, 2), 0)  # cierre 0: dato roto, fuera
    db.flush()
    hist = svc._db_history(db, company)
    assert hist.currency == "GBp"
    assert [(r.day, r.close, r.adj_close) for r in hist.rows] == [
        (date(2026, 10, 1), 2.0, None),
        (date(2026, 10, 3), 0.5, 0.25),  # un cierre < 1 (peniques) sigue valiendo
    ]
    assert svc._db_history(db, None).rows == []


def test_db_history_no_mezcla_peniques_y_libras(db):
    """250 GBp seguidos de 2,52 GBP no son una caida del 99 % (que daria 4X)."""
    company = _company(db, "TSCO.L", currency="GBp", exchange="LSE")
    _price(db, company, date(2026, 9, 30), 250.0, adj=240.0, quote="GBp")
    _price(db, company, date(2026, 10, 1), 2.52, quote="GBP")
    _price(db, company, date(2026, 10, 2), 2.55)  # heredada sin unidad: divisa de la empresa (GBp)
    db.flush()
    hist = svc._db_history(db, company)
    assert hist.currency == "GBP"
    assert [(r.day, round(r.close, 6), r.adj_close) for r in hist.rows] == [
        (date(2026, 9, 30), 2.5, 2.4),
        (date(2026, 10, 1), 2.52, None),
        (date(2026, 10, 2), 0.0255, None),
    ]


def test_db_history_descarta_cierres_en_otra_moneda(db):
    company = _company(db, "SHEL.L", currency="USD", exchange="LSE")
    _price(db, company, date(2026, 10, 1), 30.0)  # heredada: USD de la empresa
    _price(db, company, date(2026, 10, 2), 2500.0, quote="GBp")
    db.flush()
    hist = svc._db_history(db, company)
    assert hist.currency == "GBp"
    assert [(r.day, r.close) for r in hist.rows] == [(date(2026, 10, 2), 2500.0)]


def _verdict(level=3, touched=3):
    return MonthlyVerdict(
        period="2026-10", level=level, status="forming", signal_date=date(2026, 10, 27),
        close=70.0, metrics={"drawdown": 0.3}, level_prices={"2x": 85.0, "3x": 75.0},
        touched_level=touched,
    )


def _payload(level=3, previous=2):
    item = svc.TrackedSymbol(symbol="UBER", sources=["watchlist"])
    return svc._dca_payload(
        item, _verdict(level), close=70.0, level_prices={"2x": 85.0, "3x": 75.0},
        currency="USD", previous_level=previous, params=PARAMS,
    )


def test_payload_dca_tiene_la_forma_que_leen_email_y_ui():
    dca = _payload()
    assert dca["key"] == "3x"
    assert dca["label"] == "3X DCA"
    assert dca["zone"] == "Zona de compra fuerte"
    assert dca["color"] == "#68F60F" and dca["fg"] == "#000000"
    assert dca["previous_label"] == "2X DCA"
    assert dca["direction"] == "up" and dca["informational"] is False
    assert dca["signal_date"] == "2026-10-27"
    assert dca["close"] == 70.0
    assert dca["currency"] == "USD"
    assert dca["level_prices"] == {"2x": 85.0, "3x": 75.0}
    assert dca["touched_level"] == 3
    assert dca["sources"] == ["watchlist"]
    assert dca["params_version"] == "test-v1"
    assert dca["sma_months"] == getattr(PARAMS, "sma_months", None)
    assert dca["high_lookback_months"] == getattr(PARAMS, "high_lookback_months", None)
    first = _payload(previous=None)
    assert first["previous_level"] is None and first["previous_label"] is None
    assert first["direction"] is None


def test_payload_sin_parametros_opcionales_los_deja_en_none():
    item = svc.TrackedSymbol(symbol="UBER")
    params = SimpleNamespace(version="v-min")
    dca = svc._dca_payload(
        item, _verdict(), close=70.0, level_prices={}, currency=None,
        previous_level=None, params=params,
    )
    assert dca["sma_months"] is None and dca["high_lookback_months"] is None
    assert dca["params_version"] == "v-min"


def _settings(channels):
    return SimpleNamespace(dca_alert_channels=channels)


def test_emit_alert_row_deduplica_y_crea_entregas_externas(db):
    dca = _payload()
    status, alert = svc._emit_alert_row(db, dca, company_id=None, settings=_settings("in_app,email,push"))
    assert status == "alerted"
    assert alert.channels == ["in_app", "email", "push"]
    deliveries = list(db.scalars(select(AlertDelivery).where(AlertDelivery.alert_id == alert.id)))
    # Una fila por canal, sin duplicar la de in_app que ya crea emit_alert.
    assert sorted(d.channel for d in deliveries) == ["email", "in_app", "push"]
    assert {d.tenant_id for d in deliveries} == {1}
    again, existing = svc._emit_alert_row(db, dca, company_id=None, settings=_settings("in_app,email,push"))
    assert again == "duplicate"
    assert existing == alert.id
    assert db.scalar(select(AlertDelivery.id).where(AlertDelivery.alert_id != alert.id)) is None
    assert len(list(db.scalars(select(ResearchAlert)))) == 1


def test_emit_alert_row_guarda_la_empresa(db):
    company = _company(db, "UBER")
    _status, alert = svc._emit_alert_row(db, _payload(), company_id=company.id, settings=_settings("in_app"))
    assert alert.company_id == company.id
    assert [d.channel for d in db.scalars(select(AlertDelivery))] == ["in_app"]


def test_bajada_y_subida_del_mismo_mes_y_nivel_no_se_tapan(db):
    up = _payload(level=2, previous=1)
    down = _payload(level=2, previous=3)
    assert down["direction"] == "down"
    s1, a1 = svc._emit_alert_row(db, up, company_id=None, settings=_settings("in_app"))
    s2, a2 = svc._emit_alert_row(db, down, company_id=None, settings=_settings("in_app"))
    assert (s1, s2) == ("alerted", "alerted")
    assert a1.id != a2.id
    assert a2.severity == "low"
    # La huella de la bajada es la suya ("baja"): repetirla es duplicado.
    s3, existing = svc._emit_alert_row(db, down, company_id=None, settings=_settings("in_app"))
    assert (s3, existing) == ("duplicate", a2.id)


def test_dispatch_alert_resume_estados_y_no_pierde_la_alerta(db, monkeypatch):
    _status, alert = svc._emit_alert_row(db, _payload(), company_id=None, settings=_settings("in_app"))
    db.commit()
    calls = []

    def fake_dispatch(self, session, sent):
        calls.append((session, sent))
        return {"email": {"status": "sent", "id": 9}, "in_app": "stored"}

    from app.services import notification_service

    monkeypatch.setattr(notification_service.NotificationService, "dispatch", fake_dispatch)
    out = svc._dispatch_alert(db, alert)
    assert calls == [(db, alert)]
    assert out == {"status": "alerted", "alert_id": alert.id,
                   "deliveries": {"email": "sent", "in_app": "stored"}}

    def boom(self, session, sent):
        raise RuntimeError("smtp caido")

    monkeypatch.setattr(notification_service.NotificationService, "dispatch", boom)
    out = svc._dispatch_alert(db, alert)
    assert out == {"status": "alerted", "alert_id": alert.id, "deliveries": {"error": "dispatch_error"}}
    assert db.get(ResearchAlert, alert.id) is not None


def test_alerta_real_lleva_cierre_precios_de_nivel_y_divisa(db):
    _watch(db, "UBER")
    fetcher = FakeFetcher()
    fetcher.set("UBER", series(80.0))
    _run(db, fetcher)
    fetcher.set("UBER", series(70.0), currency="USD")
    _run(db, fetcher)
    dca = _alerts(db)[0].metadata_["dca"]
    assert dca["close"] == pytest.approx(70.0)
    assert dca["currency"] == "USD"
    assert isinstance(dca["level_prices"], dict) and dca["level_prices"]
