"""Bordes de la capa de datos de valoración de preingresos (app/services/pre_revenue_valuation.py).

La suite existente cubre la regla pura (app/valuation/pre_revenue_irr) y el camino feliz de la ficha;
aquí se cubre la capa de servicio con dobles quirúrgicos (mismo patrón _FakeDB de la suite del módulo):

- _tenant y _convert (divisa, tipo de cambio guardado, ausente o roto);
- revenue_anchors: analistas (firmas, rangos, consenso de prensa, filtros), guía declarada
  (duplicados, sin base, conversión), backlog y contrato oficial (reemplazo por importe mayor);
- official_contract_anchor (sin catalizadores, sin importe convertible, importe no positivo);
- _unlisted_reason y _mature_multiple (memo, privada sin filings, maduro, preingresos, financiera,
  sin precio, error inesperado con rollback);
- revenue_cagr (TCAC exacto, extremos ausentes o no positivos, filas inválidas, error con rollback);
- by_market_cap, _derived_cap_usd y _nearest_by_cap (ordenaciones y derivaciones);
- mature_peers: salto de la propia empresa, servicio de comparables roto, capa de grupo SIC y
  agotamiento de capas con motivo;
- value_pre_revenue llamado directo (payload completo, mes de cierre fiscal parseado y roto).
"""

from datetime import date
from types import SimpleNamespace

import pytest

from app.models.entities import Company
from app.services import analyst_consensus as ac
from app.services import official_catalysts as oc
from app.services import peer_comparison_service as pcs
from app.services import pre_revenue_valuation as svc
from app.services import shareholder_irr_service as sir
from app.services import sic_classification as sic_mod
from app.services import user_sotp_service as sotp
from app.valuation import pre_revenue_irr as R

TODAY = date(2026, 11, 9)


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _DB:
    def __init__(self, scalar_queue=(), execute_queue=(), tenant_id=1):
        self._scalars = list(scalar_queue)
        self._execute = list(execute_queue)
        self.info = {"tenant_id": tenant_id}
        self.rolled_back = False

    def scalars(self, _stmt):
        return _Rows(self._scalars.pop(0))

    def execute(self, _stmt):
        return _Rows(self._execute.pop(0))

    def rollback(self):
        self.rolled_back = True


def _co(i, ticker, **kw):
    # Modelo ORM real (regla gerarai-orm-fake-simplenamespace): Company no tiene columna
    # tenant_id; el servicio lo lee con getattr(..., None) como rasgo opcional del doble.
    co = Company(
        id=i,
        ticker=ticker,
        name=ticker,
        cik=kw.get("cik"),
        exchange=kw.get("exchange", "NASDAQ"),
        sector=kw.get("sector", "Comms"),
        industry=kw.get("industry", "Satellite"),
        currency=kw.get("currency", "USD"),
    )
    co.tenant_id = kw.get("tenant_id", 1)
    return co


# --- _tenant / _convert -------------------------------------------------------


def test_tenant_prioriza_info_y_cae_a_company():
    assert svc._tenant(_DB(tenant_id=3), _co(1, "A")) == 3
    assert svc._tenant(_DB(tenant_id=0), _co(1, "A", tenant_id=7)) == 7
    assert svc._tenant(_DB(tenant_id="x"), _co(1, "A", tenant_id=7)) == 7
    assert svc._tenant(_DB(tenant_id=None), _co(1, "A", tenant_id="x")) is None
    assert svc._tenant(SimpleNamespace(), _co(1, "A", tenant_id=9)) == 9


def test_convert_misma_divisa_o_sin_divisa_no_consulta_tipos():
    db = _DB()
    assert svc._convert(db, 5.0, None, "USD", TODAY) == (5.0, None)
    assert svc._convert(db, 5.0, "USD", "USD", TODAY) == (5.0, None)
    assert svc._convert(db, 5.0, "", "", TODAY) == (5.0, None)


def test_convert_con_tipo_guardado_ausente_y_roto(monkeypatch):
    db = _DB()
    monkeypatch.setattr(sotp, "convert_amount", lambda db, v, u, c, t: (v * 2, "par guardado"))
    assert svc._convert(db, 5.0, "EUR", "USD", TODAY) == (10.0, "par guardado")
    monkeypatch.setattr(sotp, "convert_amount", lambda db, v, u, c, t: None)
    assert svc._convert(db, 5.0, "EUR", "USD", TODAY) == (None, "en EUR sin tipo de cambio guardado a USD")

    def roto(db, v, u, c, t):
        raise RuntimeError("sin tabla de tipos")

    monkeypatch.setattr(sotp, "convert_amount", roto)
    assert svc._convert(db, 5.0, "EUR", "USD", TODAY) == (None, "en EUR sin tipo de cambio guardado a USD")


# --- revenue_anchors ----------------------------------------------------------


def _item(**kw):
    base = {
        "metric": "revenue",
        "year": 2028,
        "n_firms": 3,
        "median": 100.0,
        "low": 90.0,
        "high": 110.0,
        "firms": ["F1", "F2", "F3"],
        "press_consensus": None,
    }
    base.update(kw)
    return base


def test_anchors_analistas_firmas_rangos_y_filtros(monkeypatch):
    monkeypatch.setattr(ac, "history_for", lambda db, c, t: ["h"])
    items = [
        _item(),  # entra con rango (3 firmas)
        _item(year=2029, n_firms=1, median=120.0, low=115.0, high=125.0),  # rango None con 1 firma
        _item(year=2031),  # fuera de la ventana 2028-2030
        _item(metric="ebitda"),  # otra métrica
        _item(year=2030, median=None),  # sin mediana
        _item(
            year=2030,
            n_firms=0,
            median=200.0,
            press_consensus={"value_millions": 200.0, "url": "u2", "as_of": "2026-11-01"},
        ),
        _item(
            year=2030, n_firms=0, median=None, press_consensus={"value_millions": None}
        ),  # consenso sin valor
    ]
    monkeypatch.setattr(ac, "aggregate", lambda h: items)
    db = _DB([[], [None]])  # sin guía, sin backlog
    out = svc.revenue_anchors(db, _co(1, "A"), last_fy=2025, ccy="USD", today=TODAY)
    assert [(a.year, a.source, a.low, a.high) for a in out] == [
        (2028, "analistas", 90.0, 110.0),
        (2029, "analistas", None, None),
        (2030, "consenso_prensa", None, None),
    ]
    assert out[0].cite["firms"] == ["F1", "F2", "F3"] and out[2].cite["url"] == "u2"


def test_anchors_sin_tenant_no_consulta_analistas(monkeypatch):
    monkeypatch.setattr(ac, "aggregate", lambda h: (_ for _ in ()).throw(AssertionError("no debe llamarse")))
    db = _DB([[], [None]], tenant_id=None)
    company = _co(1, "A", tenant_id=None)
    assert svc.revenue_anchors(db, company, last_fy=2025, ccy="USD", today=TODAY) == []


def test_anchors_error_de_analistas_no_tumba(monkeypatch):
    monkeypatch.setattr(ac, "history_for", lambda db, c, t: (_ for _ in ()).throw(RuntimeError("tabla rota")))
    db = _DB([[], [None]])
    assert svc.revenue_anchors(db, _co(1, "A"), last_fy=2025, ccy="USD", today=TODAY) == []


def _div(key, base, low=None, high=None, unit="USD", **kw):
    return SimpleNamespace(
        input_key=key,
        base=base,
        low=low,
        high=high,
        unit=unit,
        source_url=kw.get("url", "u"),
        source_quote="q",
        as_of=None,
    )


def test_anchors_guia_deduplica_convierte_y_salta_sin_base():
    rows = [
        _div("guidance.revenue.fy2028", None),  # sin base: fuera
        _div("guidance.revenue.fy2028", 1000e6, low=900e6, high=1100e6),
        _div("guidance.revenue.fy2028", 2000e6),  # duplicada: gana la primera
        _div("guidance.revenue.fy2029", 1500e6),  # sin rango
    ]
    db = _DB([rows, [None]], tenant_id=None)
    out = svc.revenue_anchors(db, _co(1, "A", tenant_id=None), last_fy=2025, ccy="USD", today=TODAY)
    assert [(a.year, a.source, a.base, a.low, a.high) for a in out] == [
        (2028, "guia", 1000.0, 900.0, 1100.0),
        (2029, "guia", 1500.0, None, None),
    ]
    assert out[0].cite == {"url": "u", "quote": "q", "as_of": None}


def test_anchors_guia_sin_conversion_no_entra(monkeypatch):
    monkeypatch.setattr(sotp, "convert_amount", lambda db, v, u, c, t: None)
    rows = [_div("guidance.revenue.fy2028", 1000e6, unit="JPY")]
    db = _DB([rows, [None]], tenant_id=None)
    assert svc.revenue_anchors(db, _co(1, "A", tenant_id=None), last_fy=2025, ccy="USD", today=TODAY) == []


def _backlog(value, unit="USD"):
    return SimpleNamespace(
        metric="backlog",
        period="2025:FY",
        value=value,
        unit=unit,
        source=None,
        source_url=None,
        filed=None,
        source_type=None,
    )


def test_anchors_backlog_repartido_en_el_horizonte_minimo():
    db = _DB([[], [_backlog(900e6)]], tenant_id=None)
    out = svc.revenue_anchors(db, _co(1, "A", tenant_id=None), last_fy=2025, ccy="USD", today=TODAY)
    assert len(out) == 1 and out[0].source == "backlog"
    assert out[0].year == 2028 and out[0].base == pytest.approx(300.0)
    assert out[0].cite["total_millions"] == pytest.approx(900.0)


def test_anchors_backlog_sin_conversion_o_no_positivo_no_entra(monkeypatch):
    monkeypatch.setattr(sotp, "convert_amount", lambda db, v, u, c, t: None)
    db = _DB([[], [_backlog(900e6, unit="JPY")]], tenant_id=None)
    assert svc.revenue_anchors(db, _co(1, "A", tenant_id=None), last_fy=2025, ccy="USD", today=TODAY) == []
    db = _DB([[], [_backlog(0)]], tenant_id=None)
    assert svc.revenue_anchors(db, _co(1, "A", tenant_id=None), last_fy=2025, ccy="USD", today=TODAY) == []


def _cat(amount):
    return {
        "amount_for_company_value": amount,
        "amount_currency": "USD",
        "date": "2026-10-01",
        "publisher": "8-K",
        "url": "u3",
        "summary": "contrato",
        "amount_for_company": str(amount),
    }


def test_anchors_contrato_mayor_que_backlog_lo_sustituye_en_orden(monkeypatch):
    monkeypatch.setattr(oc, "catalysts_for", lambda db, c, today: [_cat(1200e6)])
    db = _DB([[], [_backlog(900e6)]], tenant_id=None)
    out = svc.revenue_anchors(db, _co(1, "A", tenant_id=None), last_fy=2025, ccy="USD", today=TODAY)
    assert [a.cite["total_millions"] for a in out] == [pytest.approx(1200.0), pytest.approx(900.0)]


def test_anchors_contrato_menor_que_backlog_no_desplaza(monkeypatch):
    # Un contrato oficial menor que la cartera ya archivada no entra: manda el filing.
    monkeypatch.setattr(oc, "catalysts_for", lambda db, c, today: [_cat(600e6)])
    db = _DB([[], [_backlog(900e6)]], tenant_id=None)
    out = svc.revenue_anchors(db, _co(1, "A", tenant_id=None), last_fy=2025, ccy="USD", today=TODAY)
    assert [a.cite["total_millions"] for a in out] == [pytest.approx(900.0)]


# --- official_contract_anchor --------------------------------------------------


def test_contrato_error_o_sin_importes_da_none(monkeypatch):
    monkeypatch.setattr(oc, "catalysts_for", lambda db, c, today: (_ for _ in ()).throw(RuntimeError("x")))
    assert svc.official_contract_anchor(_DB(), _co(1, "A"), last_fy=2025, ccy="USD", today=TODAY) is None
    monkeypatch.setattr(oc, "catalysts_for", lambda db, c, today: [{"amount_for_company_value": None}])
    assert svc.official_contract_anchor(_DB(), _co(1, "A"), last_fy=2025, ccy="USD", today=TODAY) is None


def test_contrato_sin_conversion_o_no_positivo_se_salta(monkeypatch):
    jpy = {**_cat(100e6), "amount_currency": "JPY"}
    monkeypatch.setattr(oc, "catalysts_for", lambda db, c, today: [_cat(0), jpy])
    monkeypatch.setattr(sotp, "convert_amount", lambda db, v, u, c, t: None)
    assert svc.official_contract_anchor(_DB(), _co(1, "A"), last_fy=2025, ccy="USD", today=TODAY) is None


def test_contrato_valido_reparte_en_horizonte_minimo(monkeypatch):
    monkeypatch.setattr(oc, "catalysts_for", lambda db, c, today: [_cat(900e6)])
    out = svc.official_contract_anchor(_DB(), _co(1, "A"), last_fy=2025, ccy="USD", today=TODAY)
    assert out is not None and out.source == "backlog" and out.year == 2028
    assert out.base == pytest.approx(300.0) and out.cite["url"] == "u3"


# --- _unlisted_reason / _mature_multiple ---------------------------------------


def test_unlisted_reason_solo_con_error_de_precio():
    assert svc._unlisted_reason(_co(1, "A"), ValueError("otro problema")) is None
    assert (
        svc._unlisted_reason(_co(1, "A", exchange="private"), ValueError("sin precio")) == svc.PRIVATE_REASON
    )
    assert (
        svc._unlisted_reason(_co(1, "A", exchange=" NASDAQ "), ValueError("sin precio"))
        == "N/D (sin precio de mercado guardado)"
    )


def _sp_ok(kind="operating", revenue=100.0, ev=400.0):
    sp = SimpleNamespace(revenue=revenue, enterprise_value=ev)
    cites = {"method": {"kind": kind}}
    return sp, None, None, cites


def test_mature_multiple_memo_y_privada_sin_filings(monkeypatch):
    pm = R.PeerMultiple("P1", "n", 400.0, 100.0)
    memo = {1: pm, 2: None}
    assert svc._mature_multiple(_DB(), _co(1, "P1"), TODAY, memo) is pm
    assert svc._mature_multiple(_DB(), _co(2, "P2"), TODAY, memo) is None
    # Sin excluded: una privada sin filings devuelve None sin registrar nada.
    assert svc._mature_multiple(_DB(), _co(3, "PRIV", exchange="PRIVATE"), TODAY, memo) is None
    assert memo[3] is None
    # Con excluded: queda registrada con su motivo y no se consulta nada más.
    excluded = {}
    assert svc._mature_multiple(_DB(), _co(4, "PRIV2", exchange="PRIVATE"), TODAY, memo, excluded) is None
    assert excluded[4] == svc.PRIVATE_REASON and memo[4] is None


def test_mature_multiple_maduro_preingresos_y_financiera(monkeypatch):
    monkeypatch.setattr(sir, "starting_point", lambda db, p, today, basis: _sp_ok())
    monkeypatch.setattr(sir, "_is_financial", lambda p: False)
    monkeypatch.setattr(svc, "revenue_cagr", lambda db, p: 0.12)
    pm = svc._mature_multiple(_DB(), _co(1, "P1"), TODAY, {})
    assert pm is not None and pm.multiple == pytest.approx(4.0) and pm.growth == 0.12

    monkeypatch.setattr(sir, "starting_point", lambda db, p, today, basis: _sp_ok(revenue=0))
    assert svc._mature_multiple(_DB(), _co(5, "P5"), TODAY, {}) is None  # ingresos no positivos
    monkeypatch.setattr(sir, "starting_point", lambda db, p, today, basis: _sp_ok(ev=0))
    assert svc._mature_multiple(_DB(), _co(6, "P6"), TODAY, {}) is None  # EV no positivo

    excluded = {}
    monkeypatch.setattr(sir, "starting_point", lambda db, p, today, basis: _sp_ok(kind="pre_revenue"))
    assert svc._mature_multiple(_DB(), _co(2, "P2"), TODAY, {}, excluded) is None
    assert excluded[2].startswith("sin múltiplo maduro")

    monkeypatch.setattr(sir, "starting_point", lambda db, p, today, basis: _sp_ok())
    monkeypatch.setattr(sir, "_is_financial", lambda p: True)
    excluded = {}
    assert svc._mature_multiple(_DB(), _co(3, "P3"), TODAY, {}, excluded) is None
    assert excluded == {}


def test_mature_multiple_sin_precio_y_error_inesperado(monkeypatch):
    def sin_precio(db, p, today, basis):
        raise ValueError("sin precio de mercado")

    monkeypatch.setattr(sir, "starting_point", sin_precio)
    excluded = {}
    assert (
        svc._mature_multiple(_DB(), _co(1, "P1", exchange="PRIVATE", cik="0001"), TODAY, {}, excluded) is None
    )
    assert excluded[1] == svc.PRIVATE_REASON
    excluded = {}
    assert svc._mature_multiple(_DB(), _co(2, "P2"), TODAY, {}, excluded) is None
    assert excluded[2] == "N/D (sin precio de mercado guardado)"

    def otro(db, p, today, basis):
        raise ValueError("sin ingresos")

    monkeypatch.setattr(sir, "starting_point", otro)
    excluded = {}
    assert svc._mature_multiple(_DB(), _co(3, "P3"), TODAY, {}, excluded) is None
    assert excluded == {}

    def roto(db, p, today, basis):
        raise RuntimeError("bd caída")

    monkeypatch.setattr(sir, "starting_point", roto)
    db = _DB()
    assert svc._mature_multiple(db, _co(4, "P4"), TODAY, {}) is None
    assert db.rolled_back is True


# --- revenue_cagr ---------------------------------------------------------------


def test_revenue_cagr_exacto_y_extremos():
    rows = [("2025:FY", 133.1), ("2024:FY", 120.0), ("2023:FY", 110.0), ("2022:FY", 100.0)]
    assert svc.revenue_cagr(_DB(execute_queue=[rows]), _co(1, "A")) == pytest.approx(0.1)
    assert (
        svc.revenue_cagr(_DB(execute_queue=[[("2025:FY", 100.0)]]), _co(1, "A")) is None
    )  # falta el primer año
    assert svc.revenue_cagr(_DB(execute_queue=[[("2025:FY", 100.0), ("2022:FY", 0)]]), _co(1, "A")) is None
    assert svc.revenue_cagr(_DB(execute_queue=[[("2025:FY", 0), ("2022:FY", 100.0)]]), _co(1, "A")) is None
    rows = [("2025:FY", 133.1), ("malperiodo", "x"), ("2022:FY", 100.0)]
    assert svc.revenue_cagr(_DB(execute_queue=[rows]), _co(1, "A"), years=3) == pytest.approx(0.1)
    assert svc.revenue_cagr(_DB(execute_queue=[[]]), _co(1, "A")) is None


def test_revenue_cagr_error_devuelve_none_y_rollback():
    class DBrota(_DB):
        def execute(self, _stmt):
            raise RuntimeError("sin tabla")

    db = DBrota()
    assert svc.revenue_cagr(db, _co(1, "A")) is None
    assert db.rolled_back is True


# --- by_market_cap / _derived_cap_usd / _nearest_by_cap -------------------------


def test_by_market_cap_ordena_por_cap_y_ticker(monkeypatch):
    monkeypatch.setattr(
        pcs.PeerComparisonService, "_latest_market_caps_usd", lambda self, db, ids: {1: 100.0, 3: 300.0}
    )
    companies = [_co(1, "AAA"), _co(2, "BBB"), _co(3, "CCC"), _co(4, "AAB")]
    got = svc.by_market_cap(_DB(), companies)
    assert [c.ticker for c in got] == ["CCC", "AAA", "AAB", "BBB"]  # sin cap al final, desempate ticker


def test_by_market_cap_error_cae_a_ticker(monkeypatch):
    def roto(self, db, ids):
        raise RuntimeError("sin caps")

    monkeypatch.setattr(pcs.PeerComparisonService, "_latest_market_caps_usd", roto)
    db = _DB()
    got = svc.by_market_cap(db, [_co(2, "BBB"), _co(1, "AAA")])
    assert [c.ticker for c in got] == ["AAA", "BBB"] and db.rolled_back is True


def _shares_fact(value):
    return SimpleNamespace(
        metric="shares_outstanding",
        period="2025:FY",
        value=value,
        unit="shares",
        source=None,
        source_url=None,
        filed=None,
        source_type=None,
    )


def test_derived_cap_usd_caminos(monkeypatch):
    monkeypatch.setattr(sotp, "_price", lambda db, c: (None, None, None))
    assert svc._derived_cap_usd(_DB(), _co(1, "A")) is None

    monkeypatch.setattr(sotp, "_price", lambda db, c: (10.0, "USD", TODAY))
    assert svc._derived_cap_usd(_DB([[_shares_fact(100.0)]]), _co(1, "A")) == pytest.approx(1000.0)
    # Sin shares_outstanding pero con shares_diluted: segunda métrica.
    diluted = _shares_fact(50.0)
    assert svc._derived_cap_usd(_DB([[None], [diluted]]), _co(1, "A")) == pytest.approx(500.0)
    assert svc._derived_cap_usd(_DB([[None], [None]]), _co(1, "A")) is None
    # Conversión a USD con tipo guardado; sin tipo, None.
    monkeypatch.setattr(sotp, "_price", lambda db, c: (10.0, "EUR", TODAY))
    monkeypatch.setattr(sotp, "convert_amount", lambda db, v, u, c, t: (v * 2, "par"))
    assert svc._derived_cap_usd(_DB([[_shares_fact(100.0)]]), _co(1, "A")) == pytest.approx(2000.0)
    monkeypatch.setattr(sotp, "convert_amount", lambda db, v, u, c, t: None)
    assert svc._derived_cap_usd(_DB([[_shares_fact(100.0)]]), _co(1, "A")) is None

    def roto(db, c):
        raise RuntimeError("sin precios")

    monkeypatch.setattr(sotp, "_price", roto)
    db = _DB()
    assert svc._derived_cap_usd(db, _co(1, "A")) is None and db.rolled_back is True


def test_nearest_by_cap_distancia_logaritmica_y_finales(monkeypatch):
    monkeypatch.setattr(
        pcs.PeerComparisonService,
        "_latest_market_caps_usd",
        lambda self, db, ids: {1: 100.0, 2: 110.0, 3: 90.0, 4: 400.0},
    )
    monkeypatch.setattr(svc, "_derived_cap_usd", lambda db, c: None)
    cands = [_co(4, "LEJOS"), _co(2, "CERCA"), _co(3, "CERCA2"), _co(5, "SINCAP")]
    got = svc._nearest_by_cap(_DB(), _co(1, "A"), cands, 3)
    assert [c.ticker for c in got] == ["CERCA", "CERCA2", "LEJOS"]  # SINCAP al final y fuera por n=3
    # Sin capitalización propia: los mayores primero.
    monkeypatch.setattr(
        pcs.PeerComparisonService, "_latest_market_caps_usd", lambda self, db, ids: {2: 110.0}
    )
    got = svc._nearest_by_cap(_DB(), _co(1, "A"), [_co(2, "CONCAP"), _co(3, "SIN")], 2)
    assert [c.ticker for c in got] == ["CONCAP", "SIN"]


# --- mature_peers: ramas no cubiertas por la suite -------------------------------


def _patch_peers_common(monkeypatch, svc_peers=(), base_rows=(), caps=None, mult=None):
    monkeypatch.setattr(
        pcs.PeerComparisonService, "_find_peers", lambda self, db, c, n: (list(svc_peers), "x", {})
    )
    monkeypatch.setattr(
        pcs.PeerComparisonService, "_latest_market_caps_usd", lambda self, db, ids: dict(caps or {})
    )
    monkeypatch.setattr(pcs, "_same_issuer", lambda a, b: False)
    monkeypatch.setattr(
        svc, "_mature_multiple", mult or (lambda db, c, today, memo, *exc: memo.setdefault(c.id, None))
    )
    monkeypatch.setattr(sic_mod, "company_sic", lambda c: None)
    monkeypatch.setattr(svc, "by_market_cap", lambda db, cs: list(cs))


def test_mature_peers_salta_la_propia_empresa(monkeypatch):
    target = _co(1, "TGT")
    base = [_co(1, "TGT"), _co(2, "P1"), _co(3, "P2"), _co(4, "P3")]
    mult = lambda db, c, today, memo, *exc: memo.setdefault(
        c.id, R.PeerMultiple(c.ticker, None, 400.0, 100.0)
    )
    _patch_peers_common(monkeypatch, base_rows=base, mult=mult)
    got, layer, missing, tried = svc.mature_peers(_DB([base]), target, TODAY)
    assert [p.ticker for p in got] == ["P1", "P2", "P3"] and missing is None


def test_mature_peers_servicio_roto_sigue_con_capas(monkeypatch):
    def roto(self, db, c, n):
        raise RuntimeError("servicio caído")

    monkeypatch.setattr(pcs.PeerComparisonService, "_find_peers", roto)
    monkeypatch.setattr(pcs.PeerComparisonService, "_latest_market_caps_usd", lambda self, db, ids: {})
    monkeypatch.setattr(pcs, "_same_issuer", lambda a, b: False)
    monkeypatch.setattr(sic_mod, "company_sic", lambda c: None)
    monkeypatch.setattr(svc, "by_market_cap", lambda db, cs: list(cs))
    mult = lambda db, c, today, memo, *exc: memo.setdefault(
        c.id, R.PeerMultiple(c.ticker, None, 400.0, 100.0)
    )
    monkeypatch.setattr(svc, "_mature_multiple", mult)
    base = [_co(2, "P1"), _co(3, "P2"), _co(4, "P3")]
    db = _DB([base])
    got, layer, missing, _t = svc.mature_peers(db, _co(1, "TGT"), TODAY)
    assert len(got) == 3 and layer == "misma industria (Satellite)" and db.rolled_back is True


def test_mature_peers_capa_de_grupo_sic(monkeypatch):
    base = [_co(2, "P1"), _co(3, "P2"), _co(4, "P3")]
    mult = lambda db, c, today, memo, *exc: memo.setdefault(
        c.id, R.PeerMultiple(c.ticker, None, 400.0, 100.0)
    )
    _patch_peers_common(monkeypatch, base_rows=base, mult=mult, caps={1: 100.0, 2: 100.0, 3: 100.0, 4: 100.0})
    monkeypatch.setattr(sic_mod, "company_sic", lambda c: "2834")
    monkeypatch.setattr(sic_mod, "industry_group", lambda s: "farma")
    monkeypatch.setattr(sic_mod, "group_label", lambda g: "Farma")
    got, layer, missing, _t = svc.mature_peers(_DB([base]), _co(1, "TGT"), TODAY)
    assert len(got) == 3 and layer.startswith("mismo grupo de industria: Farma")


def test_mature_peers_ninguna_capa_devuelve_motivo_y_excluidos(monkeypatch):
    privada = _co(2, "PRIV", exchange="PRIVATE")

    def mult(db, c, today, memo, excluded=None):
        memo[c.id] = None
        if excluded is not None and c.id == 2:
            excluded[c.id] = svc.PRIVATE_REASON
        return None

    _patch_peers_common(monkeypatch, svc_peers=[privada], base_rows=[privada, _co(3, "P2")], mult=mult)
    excluded_out = []
    got, layer, missing, tried = svc.mature_peers(
        _DB([[privada, _co(3, "P2")]]), _co(1, "TGT"), TODAY, excluded_out
    )
    assert got == [] and layer is None and "menos de 3 comparables maduros" in missing
    assert excluded_out == [{"ticker": "PRIV", "name": "PRIV", "motivo": svc.PRIVATE_REASON}]


# --- value_pre_revenue directo ----------------------------------------------------


def _fakes_para_valor():
    sp = SimpleNamespace(
        currency="USD",
        cash=50.0,
        price=10.0,
        shares_diluted=100.0,
        debt=0.0,
        leases=0.0,
        minorities=0.0,
        hybrids=0.0,
        revenue=5.0,
    )
    hist = SimpleNamespace(years=[2024, 2025])
    runway = {"free_cash_flow": -10.0, "missing": None, "dilution_cagr": 0.05, "sources": {}}
    return sp, hist, runway


def test_value_pre_revenue_payload_completo(monkeypatch):
    anchor = R.RevenueAnchor(2028, 1730.0, None, None, "guia", "guía de la empresa", {"url": "u"})
    peers = [
        R.PeerMultiple("P1", "Peer 1", 400.0, 100.0, 0.1),
        R.PeerMultiple("P2", "Peer 2", 800.0, 100.0, 0.2),
        R.PeerMultiple("P3", "Peer 3", 1200.0, 100.0, 0.3),
    ]
    monkeypatch.setattr(svc, "revenue_anchors", lambda db, c, last_fy, ccy, today, last_revenue=None: [anchor])
    monkeypatch.setattr(
        svc, "mature_peers", lambda db, c, today, exc: (peers, "capa", None, [{"capa": "capa"}])
    )
    sp, hist, runway = _fakes_para_valor()
    cites = {"annual": {"revenue": {"2025": {"period": "2025-09"}}}}
    out = svc.value_pre_revenue(_DB(), _co(1, "A"), sp=sp, hist=hist, cites=cites, runway=runway, today=TODAY)
    assert out["rules"] == R.RULES_VERSION and out["currency"] == "USD" and out["last_fiscal_year"] == 2025
    assert out["revenue_anchor"]["base"] == 1730.0 and out["peer_layer"] == "capa"
    assert [p["multiple"] for p in out["peers"]] == [4.0, 8.0, 12.0]
    assert set(out["scenarios"]) == {"bear", "base", "bull"}
    assert len(out["fingerprint"]) == 64


def test_value_pre_revenue_mes_fiscal_roto_e_historial_vacio(monkeypatch):
    monkeypatch.setattr(svc, "revenue_anchors", lambda db, c, last_fy, ccy, today, last_revenue=None: [])
    monkeypatch.setattr(svc, "mature_peers", lambda db, c, today, exc: ([], None, "sin maduros", []))
    sp, hist, runway = _fakes_para_valor()
    cites = {"annual": {"revenue": {"2025": {"period": "2025-XX"}}}}
    out = svc.value_pre_revenue(_DB(), _co(1, "A"), sp=sp, hist=hist, cites=cites, runway=runway, today=TODAY)
    assert out["revenue_anchor"] is None and out["revenue_anchor_missing"] is not None
    assert out["peers"] == [] and out["peers_missing"] == "sin maduros"
    hist_vacio = SimpleNamespace(years=[])
    out2 = svc.value_pre_revenue(
        _DB(), _co(1, "A"), sp=sp, hist=hist_vacio, cites={}, runway=runway, today=TODAY
    )
    assert out2["last_fiscal_year"] == TODAY.year - 1


def test_anchors_guia_error_de_consulta_queda_vacia(monkeypatch):
    class DBrota(_DB):
        def scalars(self, _stmt):
            if not self.rolled_back:
                self.rolled_back = True
                raise RuntimeError("tabla declared_input_values rota")
            return _Rows([None])

    db = DBrota(tenant_id=None)
    assert svc.revenue_anchors(db, _co(1, "A", tenant_id=None), last_fy=2025, ccy="USD", today=TODAY) == []


def test_nearest_by_cap_rellena_con_cap_derivada(monkeypatch):
    monkeypatch.setattr(pcs.PeerComparisonService, "_latest_market_caps_usd", lambda self, db, ids: {})
    derivadas = {1: 100.0, 2: 110.0}
    monkeypatch.setattr(svc, "_derived_cap_usd", lambda db, c: derivadas.get(c.id))
    got = svc._nearest_by_cap(_DB(), _co(1, "A"), [_co(3, "SIN"), _co(2, "CON")], 2)
    assert [c.ticker for c in got] == ["CON", "SIN"]


def test_mature_peers_capa_mismo_sic_sin_grupo(monkeypatch):
    base = [_co(2, "P1"), _co(3, "P2"), _co(4, "P3")]
    mult = lambda db, c, today, memo, *exc: memo.setdefault(
        c.id, R.PeerMultiple(c.ticker, None, 400.0, 100.0)
    )
    _patch_peers_common(monkeypatch, base_rows=base, mult=mult)
    monkeypatch.setattr(sic_mod, "company_sic", lambda c: "2834")
    monkeypatch.setattr(sic_mod, "industry_group", lambda s: None)
    got, layer, missing, _t = svc.mature_peers(_DB([base]), _co(1, "TGT"), TODAY)
    assert len(got) == 3 and layer.startswith("mismo código SIC (2834)")


def test_mature_peers_sin_industria_ni_sector_no_cae_a_la_base(monkeypatch):
    base = [
        _co(2, "P1", industry="Otra", sector="Otro"),
        _co(3, "P2", industry="Otra", sector="Otro"),
        _co(4, "P3", industry="Otra", sector="Otro"),
    ]
    mult = lambda db, c, today, memo, *exc: memo.setdefault(
        c.id, R.PeerMultiple(c.ticker, None, 400.0, 100.0)
    )
    _patch_peers_common(monkeypatch, base_rows=base, mult=mult)
    target = _co(1, "TGT", industry="unknown", sector="N/A")
    got, layer, missing, tried = svc.mature_peers(_DB([base]), target, TODAY)
    # Regla «comparables-sin-base-v1»: la base entera ya no es una capa; sin SIC, servicio, industria ni sector
    # el resultado es N/D con su motivo.
    assert got == [] and layer is None and missing.startswith("N/D")


def test_nearest_by_cap_error_de_caps_usa_derivadas_y_rollback(monkeypatch):
    def roto(self, db, ids):
        raise RuntimeError("sin caps")

    monkeypatch.setattr(pcs.PeerComparisonService, "_latest_market_caps_usd", roto)
    monkeypatch.setattr(svc, "_derived_cap_usd", lambda db, c: {1: 100.0, 2: 110.0}.get(c.id))
    db = _DB()
    got = svc._nearest_by_cap(db, _co(1, "A"), [_co(2, "CON"), _co(3, "SIN")], 2)
    assert [c.ticker for c in got] == ["CON", "SIN"] and db.rolled_back is True


def test_contrato_convertido_a_cero_se_salta(monkeypatch):
    # El importe es positivo pero el tipo de cambio lo deja en 0: no hay suelo contratado.
    monkeypatch.setattr(oc, "catalysts_for", lambda db, c, today: [{**_cat(100e6), "amount_currency": "JPY"}])
    monkeypatch.setattr(sotp, "convert_amount", lambda db, v, u, c, t: (0.0, "par roto"))
    assert svc.official_contract_anchor(_DB(), _co(1, "A"), last_fy=2025, ccy="USD", today=TODAY) is None
