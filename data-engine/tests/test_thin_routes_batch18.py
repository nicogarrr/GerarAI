"""Batch 18: huecos de cobertura de app/api/routes/portfolio.py (parte 1).

Llamadas directas con servicios y db doblados; sin HTTP, auth ni SQL
ejecutada (la SQL construida se declara, no se prueba). Reloj doblado
(local_today a fecha fija). Los modelos Portfolio/Transaction se instancian
reales con kwargs; los validadores pydantic se prueban construyendo el
schema y esperando ValidationError.

EXCLUIDOS del lote por la regla de Nico (dependen de tesis/valoracion/
forecast): _published_thesis_by_company, _publishable_model_by_company,
_validated_probabilities, _scenario_returns, _intrinsic_for_comparison y
todo /forecast (lineas 1765-fin del modulo).

MEDICION propia (este archivo solo, 84 tests, pytest --cov sobre el
modulo): in-scope (lineas < 1765) 708 sentencias cubiertas, 2 sin
ejecutar (412-413) = 99,72%; ramas parciales in-scope
declaradas: 436->438, 462->465, 477->480, 1276->1291, 1323->1325,
1367->1374, 1374->1391, 1394->1391, 1516->1522 (todas en
caminos de colas dobladas o ramas de tenant). Total del modulo con el
bloque excluido: 81,11%.
"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

import app.api.routes.portfolio as p


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


# --- helpers fiscales --------------------------------------------------------


def test_fiscal_info_sin_compras_no_hay_bucket(monkeypatch):
    # Linea 133: sin compra registrada no hay antiguedad ni bucket fiscal.
    monkeypatch.setattr(p, "current_holding_starts", lambda db, ids: {})
    salida = p._fiscal_info(MagicMock(), 1, date(2026, 11, 8))
    assert salida == {
        "first_buy_date": None, "holding_days": None, "fiscal_bucket": None,
    }


def test_fiscal_info_corto_y_largo_plazo(monkeypatch):
    monkeypatch.setattr(
        p, "current_holding_starts",
        lambda db, ids: {1: date(2025, 11, 1)},
    )
    salida = p._fiscal_info(MagicMock(), 1, date(2026, 11, 8))
    assert salida["fiscal_bucket"] == "largo_plazo"  # 372 dias > 365
    assert salida["holding_days"] == 372
    assert salida["first_buy_date"] == "2025-11-01"
    monkeypatch.setattr(
        p, "current_holding_starts",
        lambda db, ids: {1: date(2026, 1, 1)},
    )
    assert p._fiscal_info(MagicMock(), 1, date(2026, 11, 8))[
        "fiscal_bucket"
    ] == "corto_plazo"


def test_fiscal_info_batch_vacio_no_consulta(monkeypatch):
    # Linea 151: sin companias no hay query.
    fallo = MagicMock(side_effect=AssertionError("no deberia consultar"))
    monkeypatch.setattr(p, "current_holding_starts", fallo)
    assert p._fiscal_info_batch(MagicMock(), {}) == {}


def test_fiscal_info_batch_respeta_as_of_por_company(monkeypatch):
    monkeypatch.setattr(
        p, "current_holding_starts",
        lambda db, as_ofs: {1: date(2025, 1, 1), 2: date(2026, 11, 1)},
    )
    salida = p._fiscal_info_batch(
        MagicMock(), {1: date(2026, 11, 8), 2: date(2026, 11, 8), 3: date(2026, 11, 8)},
    )
    assert salida[1]["fiscal_bucket"] == "largo_plazo"
    assert salida[2]["fiscal_bucket"] == "corto_plazo"
    assert salida[3]["fiscal_bucket"] is None


def test_holding_as_of_cerrada_usa_ultima_venta(monkeypatch):
    # Lineas 190-204: posicion cerrada -> antiguedad hasta la ultima venta,
    # o hasta as_of si no hay ventas (SQL construida, no ejecutada).
    abierta = (SimpleNamespace(quantity=Decimal("3"), as_of=date(2024, 1, 1)),
               SimpleNamespace(id=1))
    cerrada_con_venta = (SimpleNamespace(quantity=Decimal("0"), as_of=date(2024, 1, 1)),
                         SimpleNamespace(id=2))
    cerrada_sin_venta = (SimpleNamespace(quantity=None, as_of=date(2023, 5, 5)),
                         SimpleNamespace(id=3))
    monkeypatch.setattr(p, "local_today", lambda: date(2026, 11, 8))
    monkeypatch.setattr(p, "tenant_filters", lambda db, model: [])
    db = MagicMock()
    db.execute.return_value = _Scalars([(2, date(2025, 6, 1))])
    salida = p._holding_as_of(db, [abierta, cerrada_con_venta, cerrada_sin_venta])
    assert salida[1] == date(2026, 11, 8)      # abierta: hasta hoy
    assert salida[2] == date(2025, 6, 1)       # cerrada: ultima venta
    assert salida[3] == date(2023, 5, 5)       # cerrada sin ventas: as_of


# --- validadores --------------------------------------------------------------


def _tx_input(**kw):
    base = dict(ticker="ASTS", action="buy", quantity=Decimal("1"),
                price=Decimal("10"), trade_date=date(2026, 11, 8))
    base.update(kw)
    return p.PortfolioTransactionInput(**base)


def test_tx_quantity_no_redondea_a_cero():
    # Linea 238: 0,0000004 cabe en el campo pero quedaria guardada como 0.
    with pytest.raises(ValidationError):
        _tx_input(quantity=Decimal("0.0000004"))
    with pytest.raises(ValidationError):
        _tx_input(price=Decimal("0.0000004"))
    assert _tx_input(quantity=Decimal("0.000001")).quantity == Decimal("0.000001")


def test_tx_currency_solo_codigos_reales():
    with pytest.raises(ValidationError):
        _tx_input(currency="XYZ")
    with pytest.raises(ValidationError):
        _tx_input(currency="EURO")
    assert _tx_input(currency="GBp").currency == "GBp"


def test_tx_fees_maximo_cuatro_decimales():
    # Linea 260: la columna guarda 4 decimales; mas se redondearian en
    # silencio.
    with pytest.raises(ValidationError):
        _tx_input(fees=Decimal("0.35501"))
    assert _tx_input(fees=Decimal("0.355")).fees == Decimal("0.355")


def test_tx_fecha_no_futura():
    with pytest.raises(ValidationError):
        _tx_input(trade_date=date(2099, 1, 1))


def test_not_in_the_future_helper():
    # Linea 276.
    with pytest.raises(ValueError, match="future"):
        p._not_in_the_future(date(2099, 1, 1))
    assert p._not_in_the_future(None) is None
    assert p._not_in_the_future(date(2020, 1, 1)) == date(2020, 1, 1)


def test_price_input_valida_como_una_operacion():
    with pytest.raises(ValidationError):
        p.PortfolioPriceInput(ticker="ASTS", price=Decimal("0.0000004"))
    with pytest.raises(ValidationError):
        p.PortfolioPriceInput(ticker="ASTS", price=Decimal("0"))
    # El as_of futuro tambien se rechaza:
    with pytest.raises(ValidationError):
        p.PortfolioPriceInput(ticker="ASTS", price=Decimal("10"),
                              as_of=date(2099, 1, 1))
    ok = p.PortfolioPriceInput(ticker="ASTS", price=Decimal("10"),
                               as_of=date(2026, 11, 8))
    assert ok.price == Decimal("10")


def test_base_currency_iso_sin_subunidades():
    # _iso_base_currency: GBp como base multiplicaria la valoracion por 100.
    with pytest.raises(ValidationError):
        p.CreatePortfolioInput(name="Cartera", base_currency="GBp")
    with pytest.raises(ValidationError):
        p.CreatePortfolioInput(name="Cartera", base_currency="XYZ")
    assert p.CreatePortfolioInput(name="Cartera", base_currency="eur").base_currency == "eur"


def test_fx_rate_validaciones():
    # _fx_currency + rate que no se redondea a cero (lineas 306-308, 337-338).
    with pytest.raises(ValidationError):
        p.FXRateInput(base_currency="ABC", quote_currency="EUR",
                      rate=Decimal("1.1"), rate_date=date(2026, 11, 8))
    with pytest.raises(ValidationError):
        p.FXRateInput(base_currency="USD", quote_currency="EUR",
                      rate=Decimal("1e-12"), rate_date=date(2026, 11, 8))
    with pytest.raises(ValidationError):
        p.FXRateInput(base_currency="USD", quote_currency="EUR",
                      rate=Decimal("1.1"), rate_date=date(2099, 1, 1))
    ok = p.FXRateInput(base_currency="USD", quote_currency="EUR",
                       rate=Decimal("0.0000000001"), rate_date=date(2026, 11, 8))
    assert ok.rate == Decimal("0.0000000001")


# --- list / create ------------------------------------------------------------


def test_list_portfolios_por_tenant(monkeypatch):
    # Lineas 434-439: con tenant filtra; mapea los campos de salida (SQL
    # construida, no ejecutada).
    from datetime import datetime
    db = MagicMock()
    db.info = {"tenant_id": 7}
    db.scalars.return_value = _Scalars([
        SimpleNamespace(id=1, name="Principal", base_currency="EUR",
                        is_default=True, created_at=datetime(2026, 1, 1, 12, 0)),
        SimpleNamespace(id=2, name="USA", base_currency="USD",
                        is_default=False, created_at=None),
    ])
    salida = p.list_portfolios(db=db)
    assert salida == [
        {"id": 1, "name": "Principal", "base_currency": "EUR",
         "is_default": True, "created_at": "2026-01-01T12:00:00"},
        {"id": 2, "name": "USA", "base_currency": "USD",
         "is_default": False, "created_at": None},
    ]


def _db_portfolio():
    db = MagicMock()
    db.info = {"tenant_id": 7}
    db.add = MagicMock()
    db.commit = MagicMock()
    db.refresh = MagicMock()
    db.rollback = MagicMock()
    return db


def test_create_portfolio_conflicto_nombre_existente():
    # Lineas 461-470: 409 antes de escribir si el nombre ya existe.
    db = _db_portfolio()
    db.scalars.return_value = _Scalars([SimpleNamespace(name="Principal")])
    with pytest.raises(p.HTTPException) as exc:
        p.create_portfolio(p.CreatePortfolioInput(name="  Principal  "), db=db)
    assert exc.value.status_code == 409
    db.add.assert_not_called()


def test_create_portfolio_feliz_con_auditoria(monkeypatch):
    # Lineas 472-499: crea, refresca y registra el evento de auditoria.
    audit = MagicMock()
    monkeypatch.setattr(p, "record_audit_event", audit)
    db = _db_portfolio()
    db.scalars.return_value = _Scalars([])

    def refresca(obj):
        obj.id = 42
        from datetime import datetime
        obj.created_at = datetime(2026, 11, 8, 10, 0)

    db.refresh.side_effect = refresca
    salida = p.create_portfolio(
        p.CreatePortfolioInput(name="  Nueva  ", base_currency="usd"), db=db,
    )
    creada = db.add.call_args.args[0]
    assert creada.name == "Nueva"
    assert creada.base_currency == "USD"
    assert creada.tenant_id == 7
    assert salida["id"] == 42
    assert salida["created_at"] == "2026-11-08T10:00:00"
    assert audit.call_args.kwargs["action"] == "portfolio_created"
    assert audit.call_args.kwargs["after_state"] == {
        "name": "Nueva", "base_currency": "USD",
    }
    assert db.commit.call_count == 2


def test_create_portfolio_integrity_error_es_409(monkeypatch):
    # Lineas 483-488: carrera con el UNIQUE -> 409, no 500.
    monkeypatch.setattr(p, "record_audit_event", MagicMock())
    db = _db_portfolio()
    db.scalars.return_value = _Scalars([])
    db.commit.side_effect = IntegrityError("stmt", {}, Exception("unique"))
    with pytest.raises(p.HTTPException) as exc:
        p.create_portfolio(p.CreatePortfolioInput(name="Nueva"), db=db)
    assert exc.value.status_code == 409
    db.rollback.assert_called_once()


# --- pdf, summary, intelligence, snapshots -------------------------------------


def test_pdf_export_404_y_feliz(monkeypatch):
    # Lineas 511-520: ValueError del servicio -> 404; feliz devuelve el PDF
    # con su nombre de descarga.
    monkeypatch.setattr(
        p, "export_portfolio_pdf_report",
        MagicMock(side_effect=ValueError("cartera no encontrada")),
    )
    with pytest.raises(p.HTTPException) as exc:
        p.portfolio_pdf_export(9, db=MagicMock())
    assert exc.value.status_code == 404
    monkeypatch.setattr(
        p, "export_portfolio_pdf_report",
        lambda db, pid: (b"%PDF-falso", "cartera-9.pdf"),
    )
    resp = p.portfolio_pdf_export(9, db=MagicMock())
    assert resp.media_type == "application/pdf"
    assert "cartera-9.pdf" in resp.headers["Content-Disposition"]
    assert resp.body == b"%PDF-falso"


def test_portfolio_summary_mapea_el_dashboard(monkeypatch):
    # Lineas 530-550: la respuesta mapea el risk dashboard cacheado, con los
    # opcionales por defecto cuando faltan.
    riesgo = {
        "total_value": 1, "equity_value": 2, "cash_assets_base": 3,
        "margin_debt_base": 4, "cash": 5, "top_1_weight": 0.1,
        "top_5_weight": 0.5, "alerts": [], "status": "ok",
        "base_currency": "EUR", "cash_native": 6, "missing_fx": [],
    }
    monkeypatch.setattr(
        "app.services.cached_portfolio_valuation.risk_dashboard",
        lambda db: riesgo,
    )
    salida = p.portfolio_summary(db=MagicMock())
    assert salida["total_value"] == 1
    assert salida["data_as_of"] is None
    assert salida["fx_rates"] == []
    assert salida["valuation_dates_differ"] is False
    assert salida["valuation_hold"] == []
    assert salida["provenance"] is None


def test_portfolio_intelligence_con_gc_en_pausa(monkeypatch):
    # Lineas 559-560: el calculo corre con el GC ciclico en pausa.
    from contextlib import contextmanager

    pausas = []

    @contextmanager
    def gc_falso():
        pausas.append("pausa")
        yield

    monkeypatch.setattr(p, "gc_paused", gc_falso)
    build = MagicMock(return_value={"intelligence": 1})
    monkeypatch.setattr(p, "PortfolioIntelligenceService",
                        lambda: SimpleNamespace(build=build))
    salida = p.portfolio_intelligence(years=7, db=MagicMock())
    assert salida == {"intelligence": 1}
    assert pausas == ["pausa"]
    assert build.call_args.kwargs["years"] == 7


def test_risk_matrix_y_data_quality_delegan(monkeypatch):
    # Lineas 565-568 y 573-574.
    from contextlib import contextmanager

    @contextmanager
    def gc_falso():
        yield

    monkeypatch.setattr(p, "gc_paused", gc_falso)
    monkeypatch.setattr(
        "app.services.portfolio_risk_matrix_service.PortfolioRiskMatrixService",
        lambda: SimpleNamespace(build=lambda db: {"matrix": 1}),
    )
    assert p.portfolio_risk_matrix(db=MagicMock()) == {"matrix": 1}
    monkeypatch.setattr(
        "app.services.portfolio_quality_service.portfolio_quality",
        lambda db: {"quality": 1},
    )
    assert p.portfolio_data_quality(db=MagicMock()) == {"quality": 1}


def _snapshot(**kw):
    base = dict(id=1, portfolio_id=2, snapshot_date=date(2026, 11, 7),
                base_currency="EUR", positions_value_base=Decimal("10"),
                cash_value_base=Decimal("5"), total_value_base=Decimal("15"),
                net_external_flow_base=Decimal("0"), daily_return=None,
                cumulative_twr=None, pricing_coverage=Decimal("1"),
                source="manual_capture", metadata_={"k": "v"})
    base.update(kw)
    return SimpleNamespace(**base)


def test_snapshot_payload_mapea_metadata(monkeypatch):
    # Lineas 578-592: metadata_ del modelo sale como "metadata".
    salida = p._snapshot_payload(_snapshot())
    assert salida["metadata"] == {"k": "v"}
    assert salida["snapshot_date"] == date(2026, 11, 7)
    assert salida["source"] == "manual_capture"


class _SnapshotService:
    def count_history(self, db, start=None):
        return 100

    def history(self, db, start=None, page=None, page_size=None, offset=None):
        return [_snapshot()]


def test_portfolio_snapshots_modo_pagina_y_modo_exacto(monkeypatch):
    # Lineas 605-633: contrato dual (pagina entera o limit/offset exacto).
    monkeypatch.setattr(p, "PortfolioSnapshotService", _SnapshotService)
    salida = p.portfolio_snapshots(start=None, page=2, page_size=10, db=MagicMock())
    assert salida["page_info"]["page"] == 2
    assert salida["page_info"]["total_items"] == 100
    assert len(salida["items"]) == 1
    salida = p.portfolio_snapshots(
        start=None, limit=30, offset=60, db=MagicMock(),
    )
    info = salida["page_info"]
    assert info["page"] == 3          # 60 // 30 + 1
    assert info["page_size"] == 30
    assert info["has_next"] is True   # 60 + 1 < 100
    assert info["has_prev"] is True   # 60 > 0


def test_portfolio_snapshots_offset_sin_limit_es_422(monkeypatch):
    # Lineas 624-628.
    monkeypatch.setattr(p, "PortfolioSnapshotService", _SnapshotService)
    with pytest.raises(p.HTTPException) as exc:
        p.portfolio_snapshots(start=None, offset=5, db=MagicMock())
    assert exc.value.status_code == 422


def test_capture_snapshot_persiste_y_devuelve(monkeypatch):
    # Lineas 641-656: captura manual, commit, refresh y payload recortado.
    monkeypatch.setattr(
        p, "PortfolioSnapshotService",
        lambda: SimpleNamespace(capture=lambda db, as_of, source: _snapshot()),
    )
    db = MagicMock()
    salida = p.capture_portfolio_snapshot(as_of=date(2026, 11, 7), db=db)
    db.commit.assert_called_once()
    db.refresh.assert_called_once()
    assert salida["id"] == 1
    assert salida["total_value_base"] == Decimal("15")
    assert salida["metadata"] == {"k": "v"}
    assert "portfolio_id" not in salida


# --- pnl, fx, configuracion, fx-rates, dividends -------------------------------


def test_pnl_effects_solo_en_posicion_cerrada_con_coste(monkeypatch):
    # Lineas 661-668: solo una posicion CERRADA con coste descompone la G/P;
    # en cualquier otro caso ambos efectos son None.
    split = MagicMock(return_value=(Decimal("7"), Decimal("3")))
    monkeypatch.setattr(p, "split_unrealized_pnl", split)
    pos = SimpleNamespace(average_cost=Decimal("10"), unrealized_pnl=Decimal("10"),
                          unrealized_pnl_base=Decimal("8"), fx_rate=Decimal("0.9"))
    assert p._pnl_effects(pos, held=True, has_cost=True) == {
        "pnl_price_effect_base": None, "pnl_fx_effect_base": None,
    }
    assert p._pnl_effects(pos, held=False, has_cost=False) == {
        "pnl_price_effect_base": None, "pnl_fx_effect_base": None,
    }
    pos.average_cost = Decimal("0")
    assert p._pnl_effects(pos, held=False, has_cost=True) == {
        "pnl_price_effect_base": None, "pnl_fx_effect_base": None,
    }
    split.assert_not_called()
    pos.average_cost = Decimal("10")
    assert p._pnl_effects(pos, held=False, has_cost=True) == {
        "pnl_price_effect_base": Decimal("7"), "pnl_fx_effect_base": Decimal("3"),
    }
    assert split.call_args.kwargs == {
        "unrealized_native": Decimal("10"),
        "unrealized_base": Decimal("8"),
        "fx_rate_now": Decimal("0.9"),
    }


def test_fx_source_con_y_sin_tipos(monkeypatch):
    # Lineas 682-692: etiqueta de la fuente FX (SQL construida, no ejecutada).
    monkeypatch.setattr(p, "tenant_filters", lambda db, model: [])
    db = MagicMock()
    db.execute.return_value = _Scalars([])
    db.execute.return_value.first = lambda: None
    salida = p._fx_source(db, "EUR")
    assert salida == {"source": None, "latest_rate_date": None,
                      "base_currency": "EUR"}
    fila = SimpleNamespace(source="manual", rate_date=date(2026, 11, 7))
    resultado = MagicMock()
    resultado.first.return_value = fila
    db.execute.return_value = resultado
    salida = p._fx_source(db, "USD")
    assert salida == {"source": "manual", "latest_rate_date": "2026-11-07",
                      "base_currency": "USD"}


def test_portfolio_configuration_con_y_sin_cartera(monkeypatch):
    # Lineas 697-708: sin cartera, defaults EUR/Main; IRPF siempre en euros.
    monkeypatch.setattr(p, "tenant_filters", lambda db, model: [])
    db = MagicMock()
    db.execute.return_value.first = lambda: None
    monkeypatch.setattr(p, "PortfolioFXService",
                        lambda: SimpleNamespace(portfolio=lambda db: None))
    salida = p.portfolio_configuration(db=db)
    assert salida["base_currency"] == "EUR"
    assert salida["name"] == "Main"
    assert salida["is_default"] is True
    assert salida["tax_currency"] == p.TAX_CURRENCY
    cartera = SimpleNamespace(id=1, name="USA", base_currency="USD",
                              is_default=False)
    monkeypatch.setattr(p, "PortfolioFXService",
                        lambda: SimpleNamespace(portfolio=lambda db: cartera))
    salida = p.portfolio_configuration(db=db)
    assert salida["base_currency"] == "USD"
    assert salida["is_default"] is False
    assert salida["fx_source"]["base_currency"] == "USD"


def test_update_configuration_recalcula_posiciones(monkeypatch):
    # Lineas 716-736: cambiar la divisa base recalcula cada posicion y hace
    # commit; ValueError -> rollback + 400.
    monkeypatch.setattr(p, "tenant_filters", lambda db, model: [])
    cartera = SimpleNamespace(id=1, name="Main", base_currency="USD",
                              is_default=True)
    fx = SimpleNamespace(set_base_currency=lambda db, cur: cartera)
    rebuilds = []
    monkeypatch.setattr(p, "PortfolioFXService", lambda: fx)
    monkeypatch.setattr(
        p, "PortfolioLedgerService",
        lambda: SimpleNamespace(
            rebuild_position=lambda db, cid: rebuilds.append(cid),
        ),
    )
    db = MagicMock()
    db.scalars.return_value = _Scalars([1, 2])
    salida = p.update_portfolio_configuration(
        p.PortfolioConfigurationInput(base_currency="USD"), db=db,
    )
    assert rebuilds == [1, 2]
    db.commit.assert_called_once()
    assert salida["base_currency"] == "USD"

    fx_error = SimpleNamespace(
        set_base_currency=MagicMock(side_effect=ValueError("divisa mala")),
    )
    monkeypatch.setattr(p, "PortfolioFXService", lambda: fx_error)
    db2 = MagicMock()
    with pytest.raises(p.HTTPException) as exc:
        p.update_portfolio_configuration(
            p.PortfolioConfigurationInput(base_currency="USD"), db=db2,
        )
    assert exc.value.status_code == 400
    db2.rollback.assert_called_once()


def test_list_fx_rates_modo_ventana_y_error(monkeypatch):
    # Lineas 749-791: contrato dual; offset sin limit -> 422 (SQL construida,
    # no ejecutada).
    monkeypatch.setattr(p, "tenant_filters", lambda db, model: [])
    db = MagicMock()
    db.scalar.return_value = 50
    db.scalars.return_value = _Scalars([
        SimpleNamespace(id=1, base_currency="USD", quote_currency="EUR",
                        rate=Decimal("0.9"), rate_date=date(2026, 11, 7),
                        source="manual"),
    ])
    with pytest.raises(p.HTTPException) as exc:
        p.list_fx_rates(offset=5, db=db)
    assert exc.value.status_code == 422
    salida = p.list_fx_rates(limit=10, offset=40, db=db)
    info = salida["page_info"]
    assert info["page"] == 5
    assert info["has_next"] is True   # 40 + 1 < 50
    assert info["has_prev"] is True
    assert salida["items"][0]["rate"] == 0.9
    salida = p.list_fx_rates(page=2, page_size=20, db=db)
    assert salida["page_info"]["page"] == 2
    assert salida["page_info"]["total_items"] == 50


def test_upsert_fx_rate_recalcula_y_mapea(monkeypatch):
    # Lineas 798-826: upsert + rebuild de posiciones + commit/refresh;
    # ValueError -> rollback + 400.
    monkeypatch.setattr(p, "tenant_filters", lambda db, model: [])
    fila = SimpleNamespace(id=3, base_currency="USD", quote_currency="EUR",
                           rate=Decimal("0.9"), rate_date=date(2026, 11, 7),
                           source="manual")
    fx = SimpleNamespace(upsert_rate=MagicMock(return_value=fila))
    rebuilds = []
    monkeypatch.setattr(p, "PortfolioFXService", lambda: fx)
    monkeypatch.setattr(
        p, "PortfolioLedgerService",
        lambda: SimpleNamespace(
            rebuild_position=lambda db, cid: rebuilds.append(cid),
        ),
    )
    db = MagicMock()
    db.scalars.return_value = _Scalars([4])
    payload = p.FXRateInput(base_currency="USD", quote_currency="EUR",
                            rate=Decimal("0.9"), rate_date=date(2026, 11, 7))
    salida = p.upsert_fx_rate(payload, db=db)
    assert fx.upsert_rate.call_args.kwargs["rate"] == Decimal("0.9")
    assert rebuilds == [4]
    db.commit.assert_called_once()
    db.refresh.assert_called_once_with(fila)
    assert salida["rate"] == 0.9
    assert salida["rate_date"] == "2026-11-07"

    fx.upsert_rate = MagicMock(side_effect=ValueError("tipo imposible"))
    db2 = MagicMock()
    with pytest.raises(p.HTTPException) as exc:
        p.upsert_fx_rate(payload, db=db2)
    assert exc.value.status_code == 400
    db2.rollback.assert_called_once()


def test_sync_dividends_en_hilo_del_pool(monkeypatch):
    # Lineas 839-841: la ingesta corre en el pool, no en el event loop.
    import asyncio

    async def pool_falso(fn):
        return fn()

    monkeypatch.setattr(p, "run_in_threadpool", pool_falso)
    monkeypatch.setattr(p, "run_from_any_context", lambda resultado: resultado)
    sync = MagicMock(return_value={"synced": 2})
    monkeypatch.setattr(p, "DividendIngestionService",
                        lambda: SimpleNamespace(sync_portfolio=sync))
    salida = asyncio.run(p.sync_portfolio_dividends(db=MagicMock()))
    assert salida == {"synced": 2}


def test_portfolio_dividends_delega(monkeypatch):
    # Linea 851: yields por posicion; sin registros, null declarado.
    monkeypatch.setattr(
        p, "DividendIngestionService",
        lambda: SimpleNamespace(portfolio_yields=lambda db: {"yields": []}),
    )
    assert p.portfolio_dividends(db=MagicMock()) == {"yields": []}


# --- projection, tearsheet, positions, transactions ----------------------------


def test_dividend_projection_delega(monkeypatch):
    # Linea 865: replica mecanica declarada; sin datos, cobertura (nunca 0).
    monkeypatch.setattr(
        p, "DividendProjectionService",
        lambda: SimpleNamespace(project=lambda db, months: {"months": months}),
    )
    assert p.portfolio_dividend_projection(months=6, db=MagicMock()) == {"months": 6}


def test_tearsheet_delega(monkeypatch):
    # Linea 876: sin historial, metricas a None (lo decide el servicio).
    monkeypatch.setattr(p, "TearsheetService",
                        lambda: SimpleNamespace(build=lambda db: {"sharpe": None}))
    assert p.portfolio_tearsheet(db=MagicMock()) == {"sharpe": None}


def test_positions_offset_sin_limit_es_422():
    # Linea 901.
    with pytest.raises(p.HTTPException) as exc:
        p.positions(offset=5, db=MagicMock())
    assert exc.value.status_code == 422


def test_transactions_offset_suelto_es_422():
    # Linea 1066: offset no aplica aqui (vive en /transactions/page).
    with pytest.raises(p.HTTPException) as exc:
        p.transactions(offset=5, db=MagicMock())
    assert exc.value.status_code == 422


def test_transactions_y_page_listan(monkeypatch):
    # Lineas 1070-1077 y 1088-1096: paginacion por pagina y por ventana
    # (SQL construida, no ejecutada).
    monkeypatch.setattr(p, "tenant_filters", lambda db, model: [])
    monkeypatch.setattr(p, "_transaction_payload",
                        lambda tx, company: {"tx": tx.id})
    db = MagicMock()
    db.scalar.return_value = 3
    db.scalars.return_value = _Scalars([
        SimpleNamespace(id=1, company=SimpleNamespace(ticker="ASTS")),
    ])
    salida = p.transactions(page=2, page_size=10, ticker=" asts ", db=db)
    assert salida["items"] == [{"tx": 1}]
    assert salida["page_info"]["total_items"] == 3
    assert salida["page_info"]["page"] == 2
    salida = p.transactions_page(limit=5, offset=10, db=db)
    assert salida == {"items": [{"tx": 1}], "total": 3}


def test_add_es_alias_de_create(monkeypatch):
    # Linea 1104.
    monkeypatch.setattr(p, "create_transaction", lambda payload, db: {"alias": True})
    assert p.add_portfolio_transaction(_tx_input(), db=MagicMock()) == {"alias": True}


def _ledger(resultado=None, error=None):
    class _Ledger:
        def create_transaction(self, db, **kw):
            if error is not None:
                raise error
            self.kwargs = kw
            return resultado
    return _Ledger


def _tx_devuelta():
    return SimpleNamespace(id=5, company_id=1)


def _db_create():
    db = MagicMock()
    db.info = {"tenant_id": 7, "user_id": "u"}
    db.commit = MagicMock()
    db.refresh = MagicMock()
    db.rollback = MagicMock()
    db.get = MagicMock(return_value=SimpleNamespace(id=1, ticker="ASTS"))
    return db


def _dobles_auxiliares(monkeypatch):
    monkeypatch.setattr(
        "app.services.journal_trade_link.auto_link_journal_trades_best_effort",
        auto_link := MagicMock(),
    )
    monkeypatch.setattr(p, "enqueue_tracked_analysis", analysis := MagicMock())
    monkeypatch.setattr(
        "app.services.dca_on_add.enqueue_dca_on_add", MagicMock(),
    )
    monkeypatch.setattr(
        "app.services.dca_on_add.enqueue_news_on_add", MagicMock(),
    )
    monkeypatch.setattr(
        "app.services.market_close_sync.enqueue_price_backfills", MagicMock(),
    )
    return auto_link, analysis


def test_create_transaction_compra_enlaza_y_encola(monkeypatch):
    # Lineas 1111-1161: compra feliz: commit, enlaza al diario, encola
    # analisis/DCA/noticias/backfill (todo doblado: NADA de DCA real).
    monkeypatch.setattr(p, "_transaction_payload", lambda tx, comp: {"tx": tx.id})
    monkeypatch.setattr(p, "PortfolioLedgerService", _ledger(resultado=_tx_devuelta()))
    auto_link, analysis = _dobles_auxiliares(monkeypatch)
    db = _db_create()
    salida = p.create_transaction(_tx_input(), db=db)
    assert salida == {"tx": 5}
    db.commit.assert_called_once()
    auto_link.assert_called_once()
    analysis.assert_called_once()


def test_create_transaction_dividendo_no_enlaza_al_diario(monkeypatch):
    # Rama 1130->1134: un movimiento de caja no pasa por el diario ni encola.
    monkeypatch.setattr(p, "_transaction_payload", lambda tx, comp: {"tx": tx.id})
    monkeypatch.setattr(p, "PortfolioLedgerService", _ledger(resultado=_tx_devuelta()))
    auto_link, analysis = _dobles_auxiliares(monkeypatch)
    db = _db_create()
    salida = p.create_transaction(
        _tx_input(action="dividend", quantity=Decimal("1"), price=Decimal("2.5")),
        db=db,
    )
    assert salida == {"tx": 5}
    auto_link.assert_not_called()
    analysis.assert_not_called()


def test_create_transaction_cola_rota_no_rompe_la_compra(monkeypatch):
    # Lineas 1137-1138: si encolar el analisis falla, se hace rollback de lo
    # pendiente pero la compra (ya commiteada) se mantiene y responde 201.
    monkeypatch.setattr(p, "_transaction_payload", lambda tx, comp: {"tx": tx.id})
    monkeypatch.setattr(p, "PortfolioLedgerService", _ledger(resultado=_tx_devuelta()))
    _dobles_auxiliares(monkeypatch)
    monkeypatch.setattr(
        p, "enqueue_tracked_analysis",
        MagicMock(side_effect=RuntimeError("cola caida")),
    )
    db = _db_create()
    salida = p.create_transaction(_tx_input(), db=db)
    assert salida == {"tx": 5}
    db.rollback.assert_called_once()


def test_create_transaction_errores_del_ledger(monkeypatch):
    # Lineas 1162-1174: sobrevendido -> 409; divisa mezclada -> 422;
    # ValueError -> 400. Todos con rollback.
    monkeypatch.setattr(p, "_transaction_payload", lambda tx, comp: {"tx": tx.id})
    _dobles_auxiliares(monkeypatch)
    for error, esperado in (
        (p.PortfolioOversellError("pocas"), 409),
        (p.PortfolioMixedCurrencyError("mixta"), 422),
        (ValueError("mala"), 400),
    ):
        monkeypatch.setattr(p, "PortfolioLedgerService", _ledger(error=error))
        db = _db_create()
        with pytest.raises(p.HTTPException) as exc:
            p.create_transaction(_tx_input(), db=db)
        assert exc.value.status_code == esperado
        db.rollback.assert_called_once()


def test_reject_cash_row_no_canonica():
    # Lineas 1189-1192: una fila de caja con cantidad ambigua -> 400.
    with pytest.raises(p.HTTPException) as exc:
        p._reject_noncanonical_cash_row(
            _tx_input(action="dividend", quantity=Decimal("100"),
                      price=Decimal("0.25")),
        )
    assert exc.value.status_code == 400
    # buy/sell no pasa por aqui:
    p._reject_noncanonical_cash_row(_tx_input())
    # cantidad canonica (0 o 1) aceptada:
    p._reject_noncanonical_cash_row(
        _tx_input(action="dividend", quantity=Decimal("1"), price=Decimal("2.5")),
    )


def test_reject_zero_amount_row():
    # Lineas 1213-1227: 0 acciones o 0 euros -> 400; precio 0 valido en
    # compra/venta.
    with pytest.raises(p.HTTPException) as exc:
        p._reject_zero_amount_row(_tx_input(quantity=Decimal("0")))
    assert exc.value.status_code == 400
    with pytest.raises(p.HTTPException) as exc:
        p._reject_zero_amount_row(
            _tx_input(action="dividend", quantity=Decimal("1"), price=Decimal("0")),
        )
    assert exc.value.status_code == 400
    # venta de acciones sin valor (precio 0) sigue siendo valida:
    p._reject_zero_amount_row(_tx_input(action="sell", price=Decimal("0")))


# --- batch ----------------------------------------------------------------


def _batch_payload(*txs):
    return p.PortfolioTransactionBatchInput(transactions=list(txs))


class _LedgerBatch:
    """Doble del ledger para el lote: fx, ensure_company, held, rebuild."""

    def __init__(self, held=Decimal("100"), snapshot=None):
        self.fx = SimpleNamespace(
            ensure_portfolio=lambda db: SimpleNamespace(id=1),
        )
        self._held = held
        self.rebuilds = []

    def ensure_company(self, db, ticker):
        return SimpleNamespace(id=1, ticker=ticker.strip().upper())

    def _held_quantity(self, db, company_id):
        return self._held

    def rebuild_position(self, db, company_id):
        self.rebuilds.append(company_id)


def _db_batch():
    db = MagicMock()
    db.info = {"tenant_id": 7, "user_id": "u"}
    db.add = MagicMock()
    db.flush = MagicMock()
    db.commit = MagicMock()
    db.rollback = MagicMock()
    db.scalar = MagicMock(return_value=None)  # sin posicion de captura
    db.get = MagicMock(return_value=SimpleNamespace(id=1, ticker="ASTS"))
    ids = iter(range(100, 200))
    db.refresh = MagicMock(side_effect=lambda obj: setattr(obj, "id", next(ids)))
    return db


def _dobles_batch(monkeypatch):
    monkeypatch.setattr(p, "_transaction_payload", lambda tx, comp: {"tx": tx.id})
    monkeypatch.setattr(p, "tenant_filters", lambda db, model: [])
    monkeypatch.setattr(p, "canonical_currency_code", lambda cur: cur.upper())
    monkeypatch.setattr(p, "enqueue_tracked_analysis", MagicMock())
    monkeypatch.setattr(
        "app.services.fundamentals_seed_service.enqueue_fundamentals_seed",
        MagicMock(),
    )
    monkeypatch.setattr(
        "app.services.journal_trade_link.auto_link_journal_trades_best_effort",
        auto_link := MagicMock(),
    )
    monkeypatch.setattr(
        "app.services.market_close_sync.enqueue_price_backfills", MagicMock(),
    )
    monkeypatch.setattr(
        "app.services.dca_on_add.enqueue_dca_on_add", MagicMock(),
    )
    return auto_link


def test_batch_valida_todo_antes_de_insertar(monkeypatch):
    # Lineas 1249-1258: una fila invalida aborta el lote ANTES de insertar
    # nada (rollback, 400 con el indice de la fila).
    _dobles_batch(monkeypatch)
    monkeypatch.setattr(p, "PortfolioLedgerService", _LedgerBatch)
    db = _db_batch()
    with pytest.raises(p.HTTPException) as exc:
        p.create_transaction_batch(
            _batch_payload(
                _tx_input(),
                _tx_input(action="dividend", quantity=Decimal("100"),
                          price=Decimal("0.25")),
            ),
            db=db,
        )
    assert exc.value.status_code == 400
    assert "Transaction 1" in exc.value.detail
    db.add.assert_not_called()
    db.rollback.assert_called_once()


def test_batch_feliz_un_solo_commit(monkeypatch):
    # Lineas 1266-1413: inserta sin rebuild por fila, reconstruye una vez por
    # company, UN solo commit (del doble: la atomicidad real de la BD NO se
    # prueba), y post-procesa (diario, backfill, analisis) con el DCA
    # doblado (NADA de DCA real).
    auto_link = _dobles_batch(monkeypatch)
    monkeypatch.setattr(p, "PortfolioLedgerService", _LedgerBatch)
    db = _db_batch()
    salida = p.create_transaction_batch(
        _batch_payload(_tx_input(), _tx_input(action="sell", quantity=Decimal("2"))),
        db=db,
    )
    assert salida["created"] == 2
    assert salida["transaction_ids"] == [100, 101]
    assert salida["transactions"] == [{"tx": 100}, {"tx": 101}]
    assert db.commit.call_count == 1
    auto_link.assert_called_once()


def test_batch_posicion_de_captura_es_400(monkeypatch):
    # Lineas 1284-1288: comprar sobre una posicion de captura sin historial
    # -> 400 con mensaje accionable.
    _dobles_batch(monkeypatch)
    monkeypatch.setattr(p, "PortfolioLedgerService", _LedgerBatch)
    db = _db_batch()
    db.scalar.return_value = SimpleNamespace(id=9)  # snapshot_position
    with pytest.raises(p.HTTPException) as exc:
        p.create_transaction_batch(_batch_payload(_tx_input()), db=db)
    assert exc.value.status_code == 400
    assert "captura sin historial" in exc.value.detail
    db.rollback.assert_called_once()


def test_batch_sobrevendido_es_409(monkeypatch):
    # Lineas 1291-1297: vender mas de lo que hay -> 409.
    _dobles_batch(monkeypatch)
    monkeypatch.setattr(
        p, "PortfolioLedgerService",
        lambda: _LedgerBatch(held=Decimal("1")),
    )
    db = _db_batch()
    with pytest.raises(p.HTTPException) as exc:
        p.create_transaction_batch(
            _batch_payload(_tx_input(action="sell", quantity=Decimal("5"))),
            db=db,
        )
    assert exc.value.status_code == 409
    assert "only 1" in exc.value.detail
    db.rollback.assert_called_once()


def test_batch_error_inesperado_es_500_sanitizado(monkeypatch):
    # Lineas 1417-1422: cualquier otro fallo -> rollback + 500 saneado.
    _dobles_batch(monkeypatch)

    class Roto(_LedgerBatch):
        def ensure_company(self, db, ticker):
            raise RuntimeError("detalle interno con ruta /srv/secreta")

    monkeypatch.setattr(p, "PortfolioLedgerService", Roto)
    db = _db_batch()
    with pytest.raises(p.HTTPException) as exc:
        p.create_transaction_batch(_batch_payload(_tx_input()), db=db)
    assert exc.value.status_code == 500
    db.rollback.assert_called_once()


# --- forget price, update, delete, holding, price -------------------------------


def test_forget_removed_trade_price_cortocircuitos(monkeypatch):
    # Linea 1438: sin company/precio/fecha no hace nada (ni consulta).
    db = MagicMock()
    p._forget_removed_trade_price(db, None, Decimal("10"), date(2026, 1, 1))
    p._forget_removed_trade_price(db, 1, None, date(2026, 1, 1))
    db.scalar.assert_not_called()


def test_forget_removed_trade_price_solo_sin_cotizacion(monkeypatch):
    # Lineas 1439-1455: solo pisa el precio si la posicion es del ledger, no
    # esta en suspenso, coincide con el precio borrado y NO hay cotizacion
    # guardada desde esa fecha.
    monkeypatch.setattr(p, "tenant_filters", lambda db, model: [])
    posicion = SimpleNamespace(source="postgres_ledger", valuation_hold_reason=None,
                               market_price=Decimal("14"))
    db = MagicMock()
    db.scalar.side_effect = [posicion, None]  # position, MarketPrice
    p._forget_removed_trade_price(db, 1, Decimal("14"), date(2026, 1, 1))
    assert posicion.market_price == Decimal("0")
    # Con cotizacion real posterior, no se toca:
    posicion.market_price = Decimal("14")
    db.scalar.side_effect = [posicion, 1]
    p._forget_removed_trade_price(db, 1, Decimal("14"), date(2026, 1, 1))
    assert posicion.market_price == Decimal("14")
    # Posicion en suspenso o de otra fuente: intocable.
    for pos in (
        SimpleNamespace(source="postgres_ledger",
                        valuation_hold_reason="sin cotizacion",
                        market_price=Decimal("14")),
        SimpleNamespace(source="screenshot_confirmed", valuation_hold_reason=None,
                        market_price=Decimal("14")),
        None,
    ):
        db.scalar.side_effect = [pos]
        p._forget_removed_trade_price(db, 1, Decimal("14"), date(2026, 1, 1))
        if pos is not None:
            assert pos.market_price == Decimal("14")


def test_update_transaction_404s_y_400(monkeypatch):
    # Lineas 1464-1480: no existe o no es buy/sell -> 404; payload de caja
    # -> 400 (el rebuild solo reproduce buy/sell).
    db = MagicMock()
    db.get.return_value = None
    with pytest.raises(p.HTTPException) as exc:
        p.update_transaction(1, _tx_input(), db=db)
    assert exc.value.status_code == 404
    db.get.return_value = SimpleNamespace(action="dividend")
    with pytest.raises(p.HTTPException) as exc:
        p.update_transaction(1, _tx_input(), db=db)
    assert exc.value.status_code == 404
    db.get.return_value = SimpleNamespace(action="buy")
    with pytest.raises(p.HTTPException) as exc:
        p.update_transaction(
            1, _tx_input(action="dividend", quantity=Decimal("1"),
                         price=Decimal("2")), db=db,
        )
    assert exc.value.status_code == 400


def test_update_transaction_feliz_preserva_rastro(monkeypatch):
    # Lineas 1481-1526: edita, conserva el rastro IBKR (solo 'notes' es del
    # usuario), recalcula company vieja y nueva, y commitea.
    monkeypatch.setattr(p, "canonical_currency_code", lambda cur: cur.upper())
    monkeypatch.setattr(p, "_transaction_payload", lambda tx, comp: {"tx": tx.id})
    forget = MagicMock()
    monkeypatch.setattr(p, "_forget_removed_trade_price", forget)
    rebuilds = []
    monkeypatch.setattr(
        p, "PortfolioLedgerService",
        lambda: SimpleNamespace(
            ensure_company=lambda db, ticker: SimpleNamespace(id=2, ticker=ticker),
            rebuild_position=lambda db, cid, drop_when_empty=False: rebuilds.append(
                (cid, drop_when_empty),
            ),
        ),
    )
    tx = SimpleNamespace(
        id=5, action="buy", company_id=1, price=Decimal("10"),
        trade_date=date(2026, 1, 1), quantity=Decimal("1"),
        raw_payload={"tradeID": "IBKR1", "notes": "vieja", "notes_author": "user"},
        fees=Decimal("1"),
    )
    db = MagicMock()
    db.get.return_value = tx
    db.flush = MagicMock()
    db.commit = MagicMock()
    db.refresh = MagicMock()
    salida = p.update_transaction(
        5, _tx_input(action="sell", quantity=Decimal("3"), price=Decimal("12"),
                     notes="vendo yo"),
        db=db,
    )
    assert salida == {"tx": 5}
    assert tx.action == "sell"
    assert tx.company_id == 2
    assert tx.raw_payload == {
        "tradeID": "IBKR1", "notes": "vendo yo", "notes_author": "user",
    }
    forget.assert_called_once()
    assert rebuilds == [(1, True), (2, False)]  # cambio de company: drop vieja
    db.commit.assert_called_once()


def test_update_transaction_sobrevendido_409(monkeypatch):
    # Lineas 1527-1539 (parcial): oversell al recalcular -> rollback + 409.
    monkeypatch.setattr(p, "canonical_currency_code", lambda cur: cur.upper())
    monkeypatch.setattr(p, "_forget_removed_trade_price", MagicMock())
    monkeypatch.setattr(
        p, "PortfolioLedgerService",
        lambda: SimpleNamespace(
            ensure_company=lambda db, ticker: SimpleNamespace(id=1, ticker=ticker),
            rebuild_position=MagicMock(
                side_effect=p.PortfolioOversellError("pocas"),
            ),
        ),
    )
    tx = SimpleNamespace(id=5, action="buy", company_id=1, price=Decimal("10"),
                         trade_date=date(2026, 1, 1), raw_payload={})
    db = MagicMock()
    db.get.return_value = tx
    with pytest.raises(p.HTTPException) as exc:
        p.update_transaction(5, _tx_input(action="sell"), db=db)
    assert exc.value.status_code == 409
    db.rollback.assert_called_once()


def test_delete_transaction_404_y_feliz(monkeypatch):
    # Lineas 1544-1555: 404 si no es buy/sell; feliz borra, olvida el precio
    # y recalcula con drop_when_empty.
    db = MagicMock()
    db.get.return_value = None
    with pytest.raises(p.HTTPException) as exc:
        p.delete_transaction(1, db=db)
    assert exc.value.status_code == 404
    forget = MagicMock()
    monkeypatch.setattr(p, "_forget_removed_trade_price", forget)
    rebuild = MagicMock()
    monkeypatch.setattr(p, "PortfolioLedgerService",
                        lambda: SimpleNamespace(rebuild_position=rebuild))
    tx = SimpleNamespace(action="buy", company_id=1, price=Decimal("10"),
                         trade_date=date(2026, 1, 1))
    db.get.return_value = tx
    assert p.delete_transaction(1, db=db) is None
    db.delete.assert_called_once_with(tx)
    forget.assert_called_once_with(db, 1, Decimal("10"), date(2026, 1, 1))
    rebuild.assert_called_once_with(db, 1, drop_when_empty=True)
    db.commit.assert_called_once()


def test_delete_transaction_oversell_y_mixta(monkeypatch):
    # Lineas 1556-1565.
    monkeypatch.setattr(p, "_forget_removed_trade_price", MagicMock())
    tx = SimpleNamespace(action="sell", company_id=1, price=Decimal("10"),
                         trade_date=date(2026, 1, 1))
    for error, esperado in (
        (p.PortfolioOversellError("x"), 409),
        (p.PortfolioMixedCurrencyError("x"), 422),
    ):
        monkeypatch.setattr(
            p, "PortfolioLedgerService",
            lambda: SimpleNamespace(
                rebuild_position=MagicMock(side_effect=error),
            ),
        )
        db = MagicMock()
        db.get.return_value = tx
        with pytest.raises(p.HTTPException) as exc:
            p.delete_transaction(1, db=db)
        assert exc.value.status_code == esperado
        db.rollback.assert_called_once()


def test_delete_holding_404s_y_feliz(monkeypatch):
    # Lineas 1570-1577.
    monkeypatch.setattr(p, "resolve_company", lambda db, ticker: None)
    with pytest.raises(p.HTTPException) as exc:
        p.delete_holding("NOPE", db=MagicMock())
    assert exc.value.status_code == 404
    monkeypatch.setattr(p, "resolve_company",
                        lambda db, ticker: SimpleNamespace(id=1))
    monkeypatch.setattr(
        p, "PortfolioLedgerService",
        lambda: SimpleNamespace(delete_holding=lambda db, cid: False),
    )
    db = MagicMock()
    with pytest.raises(p.HTTPException) as exc:
        p.delete_holding("ASTS", db=db)
    assert exc.value.status_code == 404
    db.rollback.assert_called_once()
    monkeypatch.setattr(
        p, "PortfolioLedgerService",
        lambda: SimpleNamespace(delete_holding=lambda db, cid: True),
    )
    db = MagicMock()
    assert p.delete_holding("ASTS", db=db) is None
    db.commit.assert_called_once()


# --- positions (cuerpo), precios, refresh, cash --------------------------------


def _posicion(**kw):
    base = dict(
        id=9, quantity=Decimal("10"), average_cost=Decimal("10"),
        cost_basis_base=Decimal("100"), market_price=Decimal("12"),
        market_value=Decimal("120"), valuation_hold_reason=None,
        valuation_hold_effective_date=None, valuation_hold_since=None,
        unrealized_pnl=Decimal("20"), realized_pnl=Decimal("0"),
        cost_basis_native=Decimal("100"), as_of=date(2026, 11, 8),
        currency="USD", base_currency="EUR", market_value_native=Decimal("120"),
        market_value_base=Decimal("110"), unrealized_pnl_base=Decimal("18"),
        realized_pnl_base=Decimal("0"), fx_rate=Decimal("1.1"),
        source="postgres_ledger",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _db_positions(filas, total=1):
    db = MagicMock()
    db.scalar.return_value = total
    db.execute.return_value.all.return_value = filas
    return db


def _dobles_positions(monkeypatch, fallbacks=None):
    monkeypatch.setattr(p, "tenant_filters", lambda db, model: [])
    monkeypatch.setattr(
        p, "_fiscal_info_batch",
        lambda db, m: {1: {"first_buy_date": "2026-01-01",
                           "holding_days": 10, "fiscal_bucket": "short"}},
    )
    monkeypatch.setattr(p, "_fiscal_info",
                        lambda db, cid, hoy: {"first_buy_date": None,
                                              "holding_days": 0,
                                              "fiscal_bucket": None})
    monkeypatch.setattr(p, "tracked_statuses", lambda db, tickers: {})
    monkeypatch.setattr(
        "app.services.ibkr_cost_reconciliation.reconcile_ibkr_costs",
        lambda db, posiciones: {},
    )
    monkeypatch.setattr(
        "app.services.ibkr_cost_reconciliation.mask_cost_under_review",
        lambda payload, check: payload,
    )
    monkeypatch.setattr(p, "_trade_price_fallbacks",
                        lambda db, posiciones: fallbacks or set())
    monkeypatch.setattr(p, "split_unrealized_pnl", lambda **kw: (1.0, 2.0))


def test_positions_cuerpo_feliz(monkeypatch):
    # Lineas 906-1030: total, pagina, fiscal, estados, costes IBKR, fallback
    # de precio y payload con efectos precio/divisa.
    _dobles_positions(monkeypatch)
    comp = SimpleNamespace(id=1, ticker="ASTS", name="AST", sector="Space")
    salida = p.positions(db=_db_positions([(_posicion(), comp)]))
    item = salida["items"][0]
    assert item["ticker"] == "ASTS"
    assert item["market_price"] == 12.0
    assert item["quote_missing"] is False
    assert item["pnl_price_effect_base"] == 1.0
    assert item["pnl_fx_effect_base"] == 2.0
    assert item["fiscal_bucket"] == "short"
    assert salida["page_info"]["total_items"] == 1


def test_positions_limit_offset_y_valoracion_en_suspenso(monkeypatch):
    # Lineas 894-896 y 941-952: contrato limit/offset y held -> precio None
    # con motivo, nunca un cero disfrazado de cotizacion.
    _dobles_positions(monkeypatch)
    comp = SimpleNamespace(id=1, ticker="ASTS", name="AST", sector="Space")
    pos = _posicion(valuation_hold_reason="sin cotizacion",
                    valuation_hold_effective_date=date(2026, 11, 1),
                    valuation_hold_since=date(2026, 10, 30))
    salida = p.positions(limit=10, offset=0,
                         db=_db_positions([(pos, comp)], total=1))
    item = salida["items"][0]
    assert item["market_price"] is None
    assert item["market_value"] is None
    assert item["unrealized_pnl"] is None
    assert item["valuation_hold"]["reason"] == "sin cotizacion"
    assert salida["page_info"]["has_next"] is False
    assert salida["page_info"]["has_prev"] is False


def test_positions_sin_cotizacion_anula_plusvalias(monkeypatch):
    # Linea 1013-1014: si el precio viene de la ultima operacion (no de una
    # cotizacion), las plusvalias salen a None con quote_missing=True.
    _dobles_positions(monkeypatch, fallbacks={1})
    comp = SimpleNamespace(id=1, ticker="ASTS", name="AST", sector="Space")
    salida = p.positions(db=_db_positions([(_posicion(), comp)]))
    item = salida["items"][0]
    assert item["quote_missing"] is True
    assert item["unrealized_pnl"] is None


def test_update_price_404_y_feliz(monkeypatch):
    # Lineas 1582-1593: 404 sin holding; feliz commitea e invalida caches.
    monkeypatch.setattr(p, "resolve_company", lambda db, ticker: None)
    with pytest.raises(p.HTTPException) as exc:
        p.update_price(
            p.PortfolioPriceInput(ticker="NOPE", price=Decimal("1"),
                                  as_of=date(2026, 11, 8)),
            db=MagicMock(),
        )
    assert exc.value.status_code == 404
    monkeypatch.setattr(p, "resolve_company",
                        lambda db, ticker: SimpleNamespace(id=1, ticker="ASTS"))
    monkeypatch.setattr(
        p, "PortfolioLedgerService",
        lambda: SimpleNamespace(
            update_market_price=lambda db, company_id, price, as_of:
            SimpleNamespace(market_price=price),
        ),
    )
    invalida_car = MagicMock()
    invalida_merc = MagicMock()
    monkeypatch.setattr(p, "invalidate_portfolio_cache", invalida_car)
    monkeypatch.setattr(p, "invalidate_market_data_cache", invalida_merc)
    db = MagicMock()
    salida = p.update_price(
        p.PortfolioPriceInput(ticker="ASTS", price=Decimal("12"),
                              as_of=date(2026, 11, 8)),
        db=db,
    )
    assert salida == {"ticker": "ASTS", "market_price": 12.0}
    db.commit.assert_called_once()
    invalida_car.assert_called_once()
    invalida_merc.assert_called_once()


def test_update_price_held_409_y_value_error_404(monkeypatch):
    # Lineas 1594-1599.
    monkeypatch.setattr(p, "resolve_company",
                        lambda db, ticker: SimpleNamespace(id=1, ticker="ASTS"))
    entrada = p.PortfolioPriceInput(ticker="ASTS", price=Decimal("12"),
                                    as_of=date(2026, 11, 8))
    for error, esperado in (
        (p.ValuationHeldError("en suspenso"), 409),
        (ValueError("sin posicion"), 404),
    ):
        monkeypatch.setattr(
            p, "PortfolioLedgerService",
            lambda: SimpleNamespace(
                update_market_price=MagicMock(side_effect=error),
            ),
        )
        db = MagicMock()
        with pytest.raises(p.HTTPException) as exc:
            p.update_price(entrada, db=db)
        assert exc.value.status_code == esperado
        db.rollback.assert_called_once()


def test_refresh_market_feliz_y_400(monkeypatch):
    # Lineas 1603-1617: el puente le da su propio loop; ValueError -> 400.
    async def _coro():
        return {"nunca": True}  # no se llega a ejecutar: el doble la cierra

    def _run_falso(coro):
        coro.close()  # cierra la corutina doblada
        return {"refreshed": 3}

    monkeypatch.setattr("app.services.async_bridge.run_from_any_context",
                        _run_falso)
    monkeypatch.setattr(
        p, "MarketRefreshService",
        lambda: SimpleNamespace(refresh=lambda db, as_of=None: _coro()),
    )
    assert p.refresh_portfolio_market_data(db=MagicMock()) == {"refreshed": 3}

    def _run_falla(coro):
        coro.close()
        raise ValueError("fecha mala")

    monkeypatch.setattr("app.services.async_bridge.run_from_any_context",
                        _run_falla)
    with pytest.raises(p.HTTPException) as exc:
        p.refresh_portfolio_market_data(db=MagicMock())
    assert exc.value.status_code == 400


def test_cash_lista_saldos():
    # Lineas 1620-1629.
    db = MagicMock()
    db.scalars.return_value.all.return_value = [
        SimpleNamespace(currency="EUR", balance=Decimal("10"),
                        settled_cash=Decimal("8"),
                        interest_rate=Decimal("0.01"), source="manual"),
    ]
    salida = p.cash(db=db)
    assert salida == [{"currency": "EUR", "balance": 10.0,
                       "settled_cash": 8.0, "interest_rate": 0.01,
                       "source": "manual"}]


# --- IBKR: guardia de tenant e importaciones ------------------------------------


def _settings_ibkr():
    return SimpleNamespace(ibkr_flex_tenant_id=7, ibkr_flex_account_id="U1")


def test_require_ibkr_owner_guardias(monkeypatch):
    # Lineas 1632-1641: las credenciales Flex globales nunca valen para otro
    # tenant; sin cuenta configurada -> 503.
    monkeypatch.setattr(
        p, "ui_error",
        lambda codigo, clave: p.HTTPException(status_code=codigo, detail=clave),
    )
    monkeypatch.setattr(p, "get_settings", _settings_ibkr)
    for info in ({"tenant_id": 8}, {"tenant_id": "7"}, {}):
        with pytest.raises(p.HTTPException) as exc:
            p._require_ibkr_owner(MagicMock(info=info))
        assert exc.value.status_code == 403
    settings = _settings_ibkr()
    settings.ibkr_flex_tenant_id = "7"  # no es int
    monkeypatch.setattr(p, "get_settings", lambda: settings)
    with pytest.raises(p.HTTPException) as exc:
        p._require_ibkr_owner(MagicMock(info={"tenant_id": 7}))
    assert exc.value.status_code == 403
    settings = _settings_ibkr()
    settings.ibkr_flex_account_id = "  "
    monkeypatch.setattr(p, "get_settings", lambda: settings)
    with pytest.raises(p.HTTPException) as exc:
        p._require_ibkr_owner(MagicMock(info={"tenant_id": 7}))
    assert exc.value.status_code == 503


def test_require_ibkr_owner_conflicto_y_feliz(monkeypatch):
    # Lineas 1642-1645: conector ya dado de alta -> 409; si no, settings.
    monkeypatch.setattr(p, "get_settings", _settings_ibkr)
    db = MagicMock(info={"tenant_id": 7})
    db.scalar.return_value = 11
    with pytest.raises(p.HTTPException) as exc:
        p._require_ibkr_owner(db)
    assert exc.value.status_code == 409
    db = MagicMock(info={"tenant_id": 7})
    db.scalar.return_value = None
    assert p._require_ibkr_owner(db).ibkr_flex_account_id == "U1"


def _dobles_import_ibkr(monkeypatch, *, configurado=True, error=None):
    async def _hilo_falso(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    async def _xml():
        return "<xml/>"

    monkeypatch.setattr(p, "run_in_threadpool", _hilo_falso)
    monkeypatch.setattr(p, "_require_ibkr_owner", lambda db: _settings_ibkr())
    monkeypatch.setattr(
        p, "IBKRFlexClient",
        lambda: SimpleNamespace(
            configured=lambda: configurado, fetch_latest_xml=_xml,
        ),
    )
    servicio = SimpleNamespace(
        import_flex_xml=MagicMock(
            side_effect=error,
            return_value={"status": "imported"},
        ) if error else lambda db, xml, expected_account_id,
        max_statement_age_days: {"status": "imported"},
    )
    monkeypatch.setattr(p, "IBKRImportService", lambda: servicio)
    return servicio


def test_import_ibkr_no_configurado(monkeypatch):
    # Lineas 1652-1661.
    _dobles_import_ibkr(monkeypatch, configurado=False)
    import asyncio
    salida = asyncio.run(p.import_ibkr(db=MagicMock()))
    assert salida["status"] == "not_configured"


def test_import_ibkr_feliz_y_errores(monkeypatch):
    # Lineas 1662-1671: feliz; PnL no listo -> 503 con Retry-After; XML malo
    # -> 400.
    import asyncio
    _dobles_import_ibkr(monkeypatch)
    assert asyncio.run(p.import_ibkr(db=MagicMock())) == {"status": "imported"}
    _dobles_import_ibkr(monkeypatch, error=p.IBKRPnlNotReadyError("aun no"))
    with pytest.raises(p.HTTPException) as exc:
        asyncio.run(p.import_ibkr(db=MagicMock()))
    assert exc.value.status_code == 503
    assert exc.value.headers == {"Retry-After": "3600"}
    _dobles_import_ibkr(monkeypatch, error=p.IBKRImportError("xml roto"))
    with pytest.raises(p.HTTPException) as exc:
        asyncio.run(p.import_ibkr(db=MagicMock()))
    assert exc.value.status_code == 400


def test_import_ibkr_xml_y_csv(monkeypatch):
    # Lineas 1674-1690: el XML sube por body; el CSV no exige tenant dueño.
    monkeypatch.setattr(p, "_require_ibkr_owner", lambda db: _settings_ibkr())
    monkeypatch.setattr(
        p, "IBKRImportService",
        lambda: SimpleNamespace(
            import_flex_xml=lambda db, xml, expected_account_id,
            max_statement_age_days: {"status": "imported"},
            import_ibkr_csv=lambda db, csv: {"status": "csv_ok"},
        ),
    )
    salida = p.import_ibkr_xml(p.IBKRXmlImportRequest(xml="<FlexQueryResponse></FlexQueryResponse>"),
                               db=MagicMock())
    assert salida == {"status": "imported"}
    salida = p.import_ibkr_csv(p.IBKRCsvImportRequest(csv="ticker,date,qty,price"),
                               db=MagicMock())
    assert salida == {"status": "csv_ok"}
    monkeypatch.setattr(
        p, "IBKRImportService",
        lambda: SimpleNamespace(
            import_flex_xml=MagicMock(
                side_effect=p.IBKRImportError("malo"),
            ),
            import_ibkr_csv=MagicMock(
                side_effect=p.IBKRImportError("malo"),
            ),
        ),
    )
    with pytest.raises(p.HTTPException) as exc:
        p.import_ibkr_xml(p.IBKRXmlImportRequest(xml="<FlexQueryResponse></FlexQueryResponse>"), db=MagicMock())
    assert exc.value.status_code == 400
    with pytest.raises(p.HTTPException) as exc:
        p.import_ibkr_csv(p.IBKRCsvImportRequest(csv="ticker,date,qty,price"), db=MagicMock())
    assert exc.value.status_code == 400


# --- importacion CSV: preview, commit, fichero ----------------------------------


def test_preview_import_feliz_y_400(monkeypatch):
    # Lineas 1705-1713.
    monkeypatch.setattr(
        p, "TransactionImportService",
        lambda: SimpleNamespace(
            preview_import=lambda file_bytes, filename, custom_mapping:
            {"filename": filename},
        ),
    )
    salida = p.preview_transaction_import(
        p.CsvPreviewRequest(content="a;b", filename="f.csv"),
    )
    assert salida == {"filename": "f.csv"}
    monkeypatch.setattr(
        p, "TransactionImportService",
        lambda: SimpleNamespace(
            preview_import=MagicMock(side_effect=ValueError("ilegible")),
        ),
    )
    with pytest.raises(p.HTTPException) as exc:
        p.preview_transaction_import(p.CsvPreviewRequest(content="a;b"))
    assert exc.value.status_code == 400


def test_commit_import_senal_dca_doblada(monkeypatch):
    # Lineas 1716-1732: con altas, avisa a dca_on_add (DOBLADO: nunca DCA
    # real); sin altas no avisa; lote invalido -> 400.
    encolado = MagicMock()
    monkeypatch.setattr(
        "app.services.dca_on_add.enqueue_dca_for_new_tracked", encolado,
    )
    monkeypatch.setattr(
        p, "TransactionImportService",
        lambda: SimpleNamespace(
            commit_import=lambda db, txs, source_filename:
            {"imported_count": 2},
        ),
    )
    db = MagicMock()
    fila = {"row_number": 1, "ticker": "ASTS", "date": "2026-01-01",
            "action": "buy", "quantity": 1.0, "price": 10.0}
    salida = p.commit_transaction_import(
        p.TransactionImportCommitRequest(transactions=[fila],
                                         source_filename="f"),
        db=db,
    )
    assert salida == {"imported_count": 2}
    encolado.assert_called_once_with(db)
    encolado.reset_mock()
    monkeypatch.setattr(
        p, "TransactionImportService",
        lambda: SimpleNamespace(
            commit_import=lambda db, txs, source_filename:
            {"imported_count": 0},
        ),
    )
    p.commit_transaction_import(
        p.TransactionImportCommitRequest(transactions=[fila],
                                         source_filename="f"),
        db=db,
    )
    encolado.assert_not_called()
    monkeypatch.setattr(
        p, "TransactionImportService",
        lambda: SimpleNamespace(
            commit_import=MagicMock(side_effect=ValueError("lote malo")),
        ),
    )
    with pytest.raises(p.HTTPException) as exc:
        p.commit_transaction_import(
            p.TransactionImportCommitRequest(transactions=[fila],
                                             source_filename="f"),
            db=db,
        )
    assert exc.value.status_code == 400


class _SubidaFalsa:
    def __init__(self, trozos, filename="f.csv"):
        self._trozos = list(trozos)
        self.filename = filename

    async def read(self, n):
        return self._trozos.pop(0) if self._trozos else b""


def test_upload_import_file_feliz_nombre_y_400(monkeypatch):
    # Lineas 1742-1758: lectura en bloques; sin nombre -> "uploaded.csv".
    import asyncio
    recibido = {}
    monkeypatch.setattr(
        p, "TransactionImportService",
        lambda: SimpleNamespace(
            preview_import=lambda file_bytes, filename:
            recibido.update(bytes=file_bytes, nombre=filename) or {"ok": True},
        ),
    )
    salida = asyncio.run(
        p.upload_transaction_import_file(
            file=_SubidaFalsa([b"ab", b"cd"], filename=None),
        ),
    )
    assert salida == {"ok": True}
    assert recibido == {"bytes": b"abcd", "nombre": "uploaded.csv"}
    monkeypatch.setattr(
        p, "TransactionImportService",
        lambda: SimpleNamespace(
            preview_import=MagicMock(side_effect=ValueError("ilegible")),
        ),
    )
    with pytest.raises(p.HTTPException) as exc:
        asyncio.run(
            p.upload_transaction_import_file(file=_SubidaFalsa([b"x"])),
        )
    assert exc.value.status_code == 400


def test_upload_import_file_413(monkeypatch):
    # Linea 1747-1751: el tope duro corta la lectura a mitad.
    import asyncio
    monkeypatch.setattr(p, "MAX_IMPORT_BYTES", 3)
    with pytest.raises(p.HTTPException) as exc:
        asyncio.run(
            p.upload_transaction_import_file(file=_SubidaFalsa([b"ab", b"cd"])),
        )
    assert exc.value.status_code == 413


# --- huecos parciales de update/delete/create transaction -----------------------


def _dobles_update(monkeypatch, rebuild=None):
    monkeypatch.setattr(p, "canonical_currency_code", lambda cur: cur.upper())
    monkeypatch.setattr(p, "_transaction_payload", lambda tx, comp: {"tx": tx.id})
    monkeypatch.setattr(p, "_forget_removed_trade_price", MagicMock())
    monkeypatch.setattr(
        p, "PortfolioLedgerService",
        lambda: SimpleNamespace(
            ensure_company=lambda db, ticker: SimpleNamespace(id=1, ticker=ticker),
            rebuild_position=rebuild or MagicMock(),
        ),
    )
    tx = SimpleNamespace(id=5, action="buy", company_id=1, price=Decimal("10"),
                         trade_date=date(2026, 1, 1), raw_payload={},
                         fees=Decimal("1"))
    db = MagicMock()
    db.get.return_value = tx
    return tx, db


def test_update_transaction_comision_explicita(monkeypatch):
    # Lineas 1493-1494: solo si fees viene en el payload se pisa la comision.
    tx, db = _dobles_update(monkeypatch)
    p.update_transaction(1, _tx_input(fees=Decimal("2.5")), db=db)
    assert tx.fees == Decimal("2.5")


def test_update_transaction_divisa_mixta_y_value_error(monkeypatch):
    # Lineas 1532-1539.
    for error, esperado in (
        (p.PortfolioMixedCurrencyError("x"), 422),
        (ValueError("malo"), 400),
    ):
        _dobles_update(monkeypatch,
                       rebuild=MagicMock(side_effect=error))
        db = MagicMock()
        db.get.return_value = SimpleNamespace(
            id=5, action="buy", company_id=1, price=Decimal("10"),
            trade_date=date(2026, 1, 1), raw_payload={},
        )
        with pytest.raises(p.HTTPException) as exc:
            p.update_transaction(1, _tx_input(), db=db)
        assert exc.value.status_code == esperado
        db.rollback.assert_called_once()


def test_delete_transaction_sin_company_no_recalcula(monkeypatch):
    # Rama 1553->1555: company_id None -> no hay rebuild pero si commit.
    monkeypatch.setattr(p, "_forget_removed_trade_price", MagicMock())
    rebuild = MagicMock()
    monkeypatch.setattr(p, "PortfolioLedgerService",
                        lambda: SimpleNamespace(rebuild_position=rebuild))
    db = MagicMock()
    db.get.return_value = SimpleNamespace(
        action="buy", company_id=None, price=Decimal("10"),
        trade_date=date(2026, 1, 1),
    )
    assert p.delete_transaction(1, db=db) is None
    rebuild.assert_not_called()
    db.commit.assert_called_once()


def test_create_transaction_sin_tenant_ni_user(monkeypatch):
    # Lineas 1159-1160: sin tenant/user en db.info se encola con None.
    monkeypatch.setattr(p, "_transaction_payload", lambda tx, comp: {"tx": tx.id})
    monkeypatch.setattr(p, "PortfolioLedgerService", _ledger(resultado=_tx_devuelta()))
    _dobles_auxiliares(monkeypatch)
    backfill = MagicMock()
    monkeypatch.setattr(
        "app.services.market_close_sync.enqueue_price_backfills", backfill,
    )
    db = _db_create()
    db.info = {}
    salida = p.create_transaction(_tx_input(), db=db)
    assert salida == {"tx": 5}
    kwargs = backfill.call_args.kwargs
    assert kwargs["tenant_id"] is None
    assert kwargs["user_id"] is None


def test_create_transaction_backfill_roto_no_rompe_la_compra(monkeypatch):
    # Lineas 1159-1160: si el backfill de precios falla, rollback de lo
    # pendiente y la compra (commiteada) responde igual.
    monkeypatch.setattr(p, "_transaction_payload", lambda tx, comp: {"tx": tx.id})
    monkeypatch.setattr(p, "PortfolioLedgerService", _ledger(resultado=_tx_devuelta()))
    _dobles_auxiliares(monkeypatch)
    monkeypatch.setattr(
        "app.services.market_close_sync.enqueue_price_backfills",
        MagicMock(side_effect=RuntimeError("cola caida")),
    )
    db = _db_create()
    assert p.create_transaction(_tx_input(), db=db) == {"tx": 5}
    db.rollback.assert_called()


# --- notas de usuario vs codigos de broker; colas del lote ----------------------


def test_user_notes_autor_user_conserva_nota_y_codigos():
    # Lineas 385-393: con notes_author="user" la nota es del usuario aunque
    # parezca un codigo de broker; los codigos salen de ibkr_notes.
    notas, codigos = p._user_notes_and_broker_codes(
        {"notes": "P", "notes_author": "user", "ibkr_notes": "P; L"},
    )
    assert notas == "P"
    assert codigos == ["P", "L"]
    notas, codigos = p._user_notes_and_broker_codes(
        {"notes": "mi nota", "notes_author": "user", "ibkr_notes": "  "},
    )
    assert notas == "mi nota"
    assert codigos is None


def test_user_notes_leyenda_broker_se_oculta_como_codigos():
    # Lineas 394-413: sin autoria de usuario, una nota que es solo codigos de
    # la leyenda IBKR en fila de broker se sirve como codigos, no como nota.
    clave_identidad = sorted(p._BROKER_IDENTITY_KEYS)[0]
    codigo = sorted(p._IBKR_NOTE_CODES)[0]
    notas, codigos = p._user_notes_and_broker_codes(
        {"notes": codigo, clave_identidad: "X"},
    )
    assert notas is None
    assert codigos == [codigo]
    # Mezcla de codigo y texto libre: sigue siendo nota visible.
    notas, codigos = p._user_notes_and_broker_codes(
        {"notes": f"{codigo}; texto libre", clave_identidad: "X"},
    )
    assert notas == f"{codigo}; texto libre"
    assert codigos is None
    # Sin identidad de broker: nota normal; ibkr_notes tiene prioridad.
    notas, codigos = p._user_notes_and_broker_codes({"notes": "hola"})
    assert notas == "hola"
    assert codigos is None
    notas, codigos = p._user_notes_and_broker_codes(
        {"notes": "hola", "ibkr_notes": "A;B"},
    )
    assert notas == "hola"
    assert codigos == ["A", "B"]


def test_batch_value_error_es_400(monkeypatch):
    # Linea 1333: un ValueError del ledger en una fila -> 400 con el indice.
    _dobles_batch(monkeypatch)

    class Raro(_LedgerBatch):
        def _held_quantity(self, db, company_id):
            raise ValueError("cantidad rara")

    monkeypatch.setattr(p, "PortfolioLedgerService", Raro)
    db = _db_batch()
    with pytest.raises(p.HTTPException) as exc:
        p.create_transaction_batch(
            _batch_payload(_tx_input(action="sell")), db=db,
        )
    assert exc.value.status_code == 400
    assert "Transaction 0" in exc.value.detail
    db.rollback.assert_called_once()


def test_batch_divisa_mixta_es_422(monkeypatch):
    # Linea 1333: una divisa mixta en una fila -> 422 con el indice.
    _dobles_batch(monkeypatch)

    class Mixta(_LedgerBatch):
        def _held_quantity(self, db, company_id):
            raise p.PortfolioMixedCurrencyError("mixta")

    monkeypatch.setattr(p, "PortfolioLedgerService", Mixta)
    db = _db_batch()
    with pytest.raises(p.HTTPException) as exc:
        p.create_transaction_batch(
            _batch_payload(_tx_input(action="sell")), db=db,
        )
    assert exc.value.status_code == 422
    assert "Transaction 0" in exc.value.detail
    db.rollback.assert_called_once()


def test_batch_colas_rotas_no_rompen_el_lote(monkeypatch):
    # Lineas 1350-1353, 1371-1372, 1387-1388, 1396-1397: fallos de las colas
    # (seeds, diario, backfill, analisis) -> rollback de lo pendiente y el
    # lote commiteado responde igual. Todo lo de DCA sigue doblado.
    # seeds: solo deja rastro en el log, ni siquiera rollback.
    _dobles_batch(monkeypatch)
    monkeypatch.setattr(p, "PortfolioLedgerService", _LedgerBatch)
    monkeypatch.setattr(
        "app.services.fundamentals_seed_service.enqueue_fundamentals_seed",
        MagicMock(side_effect=RuntimeError("cola caida")),
    )
    aviso = MagicMock()
    monkeypatch.setattr(p, "logger", SimpleNamespace(warning=aviso))
    db = _db_batch()
    salida = p.create_transaction_batch(_batch_payload(_tx_input()), db=db)
    assert salida["created"] == 1
    db.commit.assert_called_once()
    db.rollback.assert_not_called()
    aviso.assert_called_once()
    # diario y backfill: rollback de lo pendiente y a seguir.
    objetivos = (
        "app.services.journal_trade_link.auto_link_journal_trades_best_effort",
        "app.services.market_close_sync.enqueue_price_backfills",
    )
    for objetivo in objetivos:
        _dobles_batch(monkeypatch)
        monkeypatch.setattr(p, "PortfolioLedgerService", _LedgerBatch)
        monkeypatch.setattr(
            objetivo, MagicMock(side_effect=RuntimeError("cola caida")),
        )
        db = _db_batch()
        salida = p.create_transaction_batch(_batch_payload(_tx_input()), db=db)
        assert salida["created"] == 1
        db.commit.assert_called_once()
        db.rollback.assert_called()
    # El analisis del ticker comprado (parcheado en el modulo de rutas):
    _dobles_batch(monkeypatch)
    monkeypatch.setattr(p, "PortfolioLedgerService", _LedgerBatch)
    monkeypatch.setattr(
        p, "enqueue_tracked_analysis",
        MagicMock(side_effect=RuntimeError("cola caida")),
    )
    db = _db_batch()
    salida = p.create_transaction_batch(_batch_payload(_tx_input()), db=db)
    assert salida["created"] == 1
    db.rollback.assert_called()
