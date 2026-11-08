"""Huecos de cobertura en screeners (lote 15).

Medicion previa (mismo metodo, tests que referencian el modulo): screeners
81,4 %. Se cubren: custom-metrics (lista, crear 400), screens (update 404/
duplicado 400, delete 404, run 404/feliz), metric-coverage, run ad hoc (feliz
y 400), _load_universe_from_db y _load_screener_ratios (felices y fallo),
los metodos del Protocol, _finnhub_get (429/no-200/no-dict/error HTTP),
_reserve_finnhub_call (espera de ventana), el retry de Finnhub, Yahoo
(error HTTP, no-200, sin cierres), _candle_market_date con zona mala, las
caches de quote/profile (hit, leader, follower), _store_real_items (cambio de
vendor e invalidacion por tenant), el refresh en background y su cooldown,
el endpoint /real (cache hit, LKG fresca, desalojo de cache llena),
_safe_fetch_* tragando errores y _refetch_real_items (sin quote, perfil
cacheado).

Que NO se prueba aqui: nada de HTTP ni auth; ninguna base de datos real (la
lectura del universo va contra una db doblada: el SQL real NO se prueba);
CustomMetricService, ScreenerService, SafeFormula y los vendors remotos van
doblados (solo delegacion); NINGUNA llamada de red real a Finnhub/Yahoo (los
clientes httpx son falsos); el reloj va doblado en la prueba de la ventana
de rate limit; los ThreadPoolExecutor se ejecutan con funciones dobladas, no
con trabajo real de red.

Rama declarada inalcanzable: en _reserve_finnhub_call el arco 461->463
(`if wait > 0` falso) no puede darse: las llamadas expiradas se purgan antes
(455-456), asi que cuando la ventana esta llena siempre queda wait > 0.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.api.routes import screeners as s


@pytest.fixture(autouse=True)
def _caches_limpias():
    for nombre in (
        "_real_quote_cache", "_real_profile_cache", "_real_items_cache",
        "_real_response_cache", "_real_refresh_futures", "_real_refresh_generations",
        "_real_refresh_last_attempt", "_profile_singleflight", "_finnhub_call_times",
    ):
        getattr(s, nombre).clear()
    yield


def _db(tenant=1):
    db = Mock()
    db.info = {"tenant_id": tenant, "user_id": "u"}
    return db


FILA_METRICA = SimpleNamespace(
    id=1, metric_key="pe_custom", name="PE custom", formula="a/b", unit="decimal",
    description="", version=1, active=True, metadata_={}, created_at=None,
)


# --- custom metrics y screens ------------------------------------------------


def test_lista_metricas_custom(monkeypatch):
    monkeypatch.setattr(
        s.CustomMetricService, "active", staticmethod(lambda db: [FILA_METRICA])
    )
    result = s.list_custom_metrics(db=_db())
    assert result[0]["metric_key"] == "pe_custom"


def test_crear_metrica_feliz(monkeypatch):
    monkeypatch.setattr(
        s, "CustomMetricService", lambda: SimpleNamespace(create=lambda db, **kw: FILA_METRICA)
    )
    payload = s.CustomMetricCreate(metric_key="pe_custom", name="PE custom", formula="a/b")
    assert s.create_custom_metric(payload, db=_db())["id"] == 1


def test_crear_metrica_invalida_es_400(monkeypatch):
    def malo(db, **kw):
        raise ValueError("formula invalida")

    monkeypatch.setattr(s, "CustomMetricService", lambda: SimpleNamespace(create=malo))
    payload = s.CustomMetricCreate(metric_key="pe_custom", name="PE custom", formula="??")
    with pytest.raises(HTTPException) as exc:
        s.create_custom_metric(payload, db=_db())
    assert exc.value.status_code == 400


def _payload_screen():
    return s.ScreenCreate(
        name="Baratas",
        criteria=[s.Criterion(left="pe", operator="<", right="10")],
    )


def test_actualizar_screen_inexistente_es_404():
    db = _db()
    db.get.return_value = None
    with pytest.raises(HTTPException) as exc:
        s.update_screen(5, _payload_screen(), db=db)
    assert exc.value.status_code == 404


def test_actualizar_screen_archivada_es_404():
    db = _db()
    db.get.return_value = SimpleNamespace(id=5, active=False)
    with pytest.raises(HTTPException) as exc:
        s.update_screen(5, _payload_screen(), db=db)
    assert exc.value.status_code == 404


def test_actualizar_screen_nombre_duplicado_es_400(monkeypatch):
    monkeypatch.setattr(
        s,
        "ScreenerService",
        lambda: SimpleNamespace(
            _criterion=lambda item: {"left": item["left"], "right": item["right"]},
            claim_screen_name=lambda db, name, exclude_id: name,
        ),
    )
    monkeypatch.setattr(
        s.SafeFormula, "reject_out_of_range", staticmethod(lambda *a: None)
    )
    db = _db()
    db.get.return_value = SimpleNamespace(id=5, active=True)
    db.commit.side_effect = IntegrityError("stmt", {}, Exception("dup"))
    with pytest.raises(HTTPException) as exc:
        s.update_screen(5, _payload_screen(), db=db)
    assert exc.value.status_code == 400
    db.rollback.assert_called()


def test_borrar_screen_inexistente_es_404():
    db = _db()
    db.get.return_value = None
    with pytest.raises(HTTPException) as exc:
        s.delete_screen(5, db=db)
    assert exc.value.status_code == 404


def test_run_screen_inexistente_es_404():
    db = _db()
    db.get.return_value = None
    with pytest.raises(HTTPException) as exc:
        s.run_saved_screen(5, db=db)
    assert exc.value.status_code == 404


def test_run_screen_feliz(monkeypatch):
    monkeypatch.setattr(
        s, "ScreenerService", lambda: SimpleNamespace(run_saved=lambda db, sc: {"n": 3})
    )
    db = _db()
    db.get.return_value = SimpleNamespace(id=5, active=True)
    assert s.run_saved_screen(5, db=db) == {"n": 3}


def test_metric_coverage_delega(monkeypatch):
    monkeypatch.setattr(
        s, "ScreenerService", lambda: SimpleNamespace(metric_coverage=lambda db: ["pe", "pb"])
    )
    assert s.metric_coverage(db=_db()) == {"metrics_with_data": ["pe", "pb"]}


def test_run_ad_hoc_feliz(monkeypatch):
    monkeypatch.setattr(s.SafeFormula, "reject_out_of_range", staticmethod(lambda *a: None))
    monkeypatch.setattr(
        s, "ScreenerService", lambda: SimpleNamespace(run=lambda db, **kw: {"matches": []})
    )
    payload = s.AdHocScreen(criteria=[s.Criterion(left="pe", operator="<", right="10")])
    assert s.run_ad_hoc_screen(payload, db=_db()) == {"matches": []}


def test_run_ad_hoc_fuera_de_rango_es_400(monkeypatch):
    def fuera(*a):
        raise ValueError("literal gigante")

    monkeypatch.setattr(s.SafeFormula, "reject_out_of_range", staticmethod(fuera))
    payload = s.AdHocScreen(criteria=[s.Criterion(left="pe", operator="<", right="10")])
    with pytest.raises(HTTPException) as exc:
        s.run_ad_hoc_screen(payload, db=_db())
    assert exc.value.status_code == 400


# --- cargas best-effort desde BD -------------------------------------------------


class _SesionFalsa:
    def __init__(self, db):
        self._db = db

    def __enter__(self):
        return self._db

    def __exit__(self, *a):
        return False


def test_universo_desde_db_feliz(monkeypatch):
    db = SimpleNamespace(
        execute=lambda stmt: SimpleNamespace(
            fetchall=lambda: [("asts", "AST SpaceMobile", "Technology")]
        )
    )
    from app.core import database

    monkeypatch.setattr(database, "SessionLocal", lambda: _SesionFalsa(db))
    assert s._load_universe_from_db() == {"ASTS": ("AST SpaceMobile", "Technology")}


def test_universo_desde_db_falla_y_sigue(monkeypatch):
    from app.core import database

    def roto():
        raise ConnectionError("sin db")

    monkeypatch.setattr(database, "SessionLocal", roto)
    assert s._load_universe_from_db() == {}


def test_ratios_fijan_tenant_antes_de_leer(monkeypatch):
    visto = {}
    db = SimpleNamespace(info={})
    from app.core import database
    from app.services import screener_fundamentals

    monkeypatch.setattr(database, "SessionLocal", lambda: _SesionFalsa(db))
    monkeypatch.setattr(
        screener_fundamentals,
        "load_screener_ratios",
        lambda db, symbols, live_prices: visto.update(tenant=db.info.get("tenant_id")) or {"ASTS": {}},
    )
    result = s._load_screener_ratios(live_prices=None, tenant_id=7)
    assert result == {"ASTS": {}}
    assert visto["tenant"] == 7


def test_ratios_fallo_devuelve_vacio(monkeypatch):
    from app.core import database

    def roto():
        raise ConnectionError("sin db")

    monkeypatch.setattr(database, "SessionLocal", roto)
    assert s._load_screener_ratios() == {}


# --- vendors ---------------------------------------------------------------------


def test_metodos_del_protocolo_devuelven_none():
    assert s.ScreenQuoteVendor.fetch_quote(Mock(), Mock(), "ASTS") is None
    assert s.ScreenQuoteVendor.fetch_profile(Mock(), Mock(), "ASTS") is None


def test_finnhub_get_429_devuelve_none(monkeypatch):
    monkeypatch.setattr(s, "_reserve_finnhub_call", lambda: 0.0)
    cliente = Mock()
    cliente.get.return_value = SimpleNamespace(status_code=429)
    assert s._finnhub_get(cliente, "/quote", "ASTS", 1.0) is None


def test_finnhub_get_no_200_devuelve_none(monkeypatch):
    monkeypatch.setattr(s, "_reserve_finnhub_call", lambda: 0.0)
    cliente = Mock()
    cliente.get.return_value = SimpleNamespace(status_code=500)
    assert s._finnhub_get(cliente, "/quote", "ASTS", 1.0) is None


def test_finnhub_get_payload_no_dict_devuelve_none(monkeypatch):
    monkeypatch.setattr(s, "_reserve_finnhub_call", lambda: 0.0)
    cliente = Mock()
    cliente.get.return_value = SimpleNamespace(status_code=200, json=lambda: [1, 2])
    assert s._finnhub_get(cliente, "/quote", "ASTS", 1.0) is None


def test_finnhub_get_error_http_devuelve_none(monkeypatch):
    monkeypatch.setattr(s, "_reserve_finnhub_call", lambda: 0.0)
    cliente = Mock()
    cliente.get.side_effect = httpx.HTTPError("red caida")
    assert s._finnhub_get(cliente, "/quote", "ASTS", 1.0) is None


def test_reserve_finnhub_call_espera_la_ventana(monkeypatch):
    # Ventana llena: la primera pasada espera (reloj doblado, sin dormir de
    # verdad) y la segunda encuentra hueco tras expirar las llamadas.
    s._finnhub_call_times.extend([1000.0] * s._FINNHUB_MAX_CALLS_PER_WINDOW)
    tiempos = iter([1000.0, 1000.0 + s._FINNHUB_WINDOW_SECONDS])
    monkeypatch.setattr(s.time, "monotonic", lambda: next(tiempos))
    dormido = []
    monkeypatch.setattr(s.time, "sleep", lambda seg: dormido.append(seg))
    s._reserve_finnhub_call()
    assert len(dormido) == 1
    assert dormido[0] > 0


def test_finnhub_quote_reintenta_una_vez(monkeypatch):
    llamadas = []

    def get_falso(client, path, symbol, timeout):
        llamadas.append(symbol)
        if len(llamadas) == 1:
            return None
        return {"c": 12.5, "d": None, "dp": None, "v": None, "pc": None, "t": 1}

    monkeypatch.setattr(s, "_finnhub_get", get_falso)
    monkeypatch.setattr(s.time, "sleep", lambda seg: None)
    vendor = s.FinnhubScreenVendor()
    result = vendor.fetch_quote(Mock(), "ASTS")
    assert result["price"] == 12.5
    assert result["change"] is None
    assert llamadas == ["ASTS", "ASTS"]


def test_yahoo_quote_error_http():
    cliente = Mock()
    cliente.get.side_effect = httpx.HTTPError("red caida")
    assert s.YahooScreenVendor().fetch_quote(cliente, "ASTS") is None


def test_yahoo_quote_no_200():
    cliente = Mock()
    cliente.get.return_value = SimpleNamespace(status_code=404)
    assert s.YahooScreenVendor().fetch_quote(cliente, "ASTS") is None


def _payload_yahoo(closes):
    return {
        "chart": {
            "result": [{
                "indicators": {"quote": [{"close": closes, "volume": []}]},
                "timestamp": [],
                "meta": {},
            }]
        }
    }


def test_yahoo_quote_sin_cierres_validos():
    cliente = Mock()
    cliente.get.return_value = SimpleNamespace(
        status_code=200, json=lambda: _payload_yahoo([None, None])
    )
    assert s.YahooScreenVendor().fetch_quote(cliente, "ASTS") is None


def test_candle_market_date_zona_inexistente():
    assert s._candle_market_date(1_700_000_000.0, "No/Existe") is None


# --- caches de quote/profile -------------------------------------------------------


def _vendor_falso(quote=None, profile=None):
    return SimpleNamespace(
        name="fake",
        fetch_quote=Mock(return_value=quote),
        fetch_profile=Mock(return_value=profile),
    )


def test_fetch_quote_cachea_y_reusa(monkeypatch):
    vendor = _vendor_falso(quote={"price": 1.0})
    monkeypatch.setattr(s, "resolve_screener_vendor", lambda v=None: vendor)
    assert s._fetch_quote(Mock(), "ASTS") == {"price": 1.0}
    assert s._fetch_quote(Mock(), "ASTS") == {"price": 1.0}
    vendor.fetch_quote.assert_called_once()


def test_fetch_quote_sin_dato_no_cachea(monkeypatch):
    vendor = _vendor_falso(quote=None)
    monkeypatch.setattr(s, "resolve_screener_vendor", lambda v=None: vendor)
    assert s._fetch_quote(Mock(), "ASTS") is None
    assert s._real_quote_cache == {}


def test_fetch_profile_hit_de_cache(monkeypatch):
    vendor = _vendor_falso(profile={"name": "X"})
    monkeypatch.setattr(s, "resolve_screener_vendor", lambda v=None: vendor)
    s._real_profile_cache["fake:ASTS"] = {"at": time.monotonic(), "data": {"name": "CACHE"}}
    assert s._fetch_profile(Mock(), "ASTS") == {"name": "CACHE"}
    vendor.fetch_profile.assert_not_called()


def test_fetch_profile_leader_guarda_y_libera(monkeypatch):
    vendor = _vendor_falso(profile={"name": "X"})
    monkeypatch.setattr(s, "resolve_screener_vendor", lambda v=None: vendor)
    assert s._fetch_profile(Mock(), "ASTS") == {"name": "X"}
    assert s._real_profile_cache["fake:ASTS"]["data"] == {"name": "X"}
    assert "fake:ASTS" not in s._profile_singleflight


def test_fetch_profile_follower_espera_y_lee_cache(monkeypatch):
    vendor = _vendor_falso(profile={"name": "X"})
    monkeypatch.setattr(s, "resolve_screener_vendor", lambda v=None: vendor)
    listo = threading.Event()
    listo.set()
    s._profile_singleflight["fake:ASTS"] = listo
    s._real_profile_cache["fake:ASTS"] = {"at": time.monotonic(), "data": {"name": "DEL LIDER"}}
    assert s._fetch_profile(Mock(), "ASTS") == {"name": "DEL LIDER"}
    vendor.fetch_profile.assert_not_called()


# --- store / refresh ----------------------------------------------------------------


def test_store_real_items_cambio_de_vendor_reemplaza():
    s._real_items_cache[1] = {
        "items": [{"symbol": "VIEJO", "price": 1}], "vendor": "finnhub", "at_wall": 1.0,
    }
    nuevos = [{"symbol": "NUEVO", "price": 2}]
    s._store_real_items(nuevos, "yahoo", 1)
    assert s._real_items_cache[1]["items"] == nuevos


def test_store_real_items_invalida_respuestas_del_tenant():
    s._real_items_cache[1] = {"items": [], "vendor": "yahoo", "at_wall": 1.0}
    s._real_response_cache[("yahoo", None, None, 25, 1)] = {"at": 1.0, "payload": {}}
    s._real_response_cache[("yahoo", None, None, 25, 2)] = {"at": 1.0, "payload": {}}
    s._store_real_items([{"symbol": "X", "price": 1}], "yahoo", 1)
    assert ("yahoo", None, None, 25, 1) not in s._real_response_cache
    assert ("yahoo", None, None, 25, 2) in s._real_response_cache


def test_refresh_background_guarda_si_generacion_vigente(monkeypatch):
    # El merge conserva solo simbolos del universo: uso uno real.
    simbolo = s._REAL_UNIVERSE[0][0]
    monkeypatch.setattr(s, "_refetch_real_items", lambda vendor, tenant_id: [{"symbol": simbolo}])
    s._real_refresh_generations[1] = 3
    s._refresh_real_items_background("yahoo", 3, 1)
    assert s._real_items_cache[1]["items"] == [{"symbol": simbolo}]


def test_refresh_background_traga_el_fallo(monkeypatch):
    def roto(vendor, tenant_id):
        raise ConnectionError("vendor caido")

    monkeypatch.setattr(s, "_refetch_real_items", roto)
    s._real_refresh_real_items_background = None  # no-op por si acaso
    s._refresh_real_items_background("yahoo", 1, 1)  # no lanza


def test_schedule_refresh_reusa_futuro_en_vuelo():
    futuro = Mock()
    futuro.done.return_value = False
    s._real_refresh_futures[1] = futuro
    assert s._schedule_real_refresh("yahoo", 1) is futuro


# --- endpoint /real -----------------------------------------------------------------


def _settings(**kw):
    base = dict(screener_quote_vendor="yahoo", finnhub_api_key=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_endpoint_cache_hit_devuelve_payload_guardado(monkeypatch):
    monkeypatch.setattr(s, "get_settings", _settings)
    monkeypatch.setattr(s, "_schedule_real_refresh", lambda v, t: None)
    key = s._real_response_key("yahoo", None, None, 25, 1)
    s._real_response_cache[key] = {
        "at": time.monotonic(),
        "payload": {"source": "yahoo_finance", "screener": [{"symbol": "X"}], "refreshing": True},
    }
    result = s.real_time_screener(marketCapMoreThan=None, sector=None, limit=25, db=_db())
    assert result["screener"] == [{"symbol": "X"}]
    # refreshing refleja el AHORA (sin refresh en vuelo), no el valor guardado.
    assert result["refreshing"] is False
    assert result["universe_size"] == len(s._REAL_UNIVERSE)


def test_endpoint_lkg_fresca_sin_refresh(monkeypatch):
    monkeypatch.setattr(s, "get_settings", _settings)
    programado = []
    monkeypatch.setattr(s, "_schedule_real_refresh", lambda v, t: programado.append(v))
    s._real_items_cache[1] = {
        "items": [{"symbol": "X", "marketCap": 10.0, "sector": "Technology"}],
        "vendor": "yahoo",
        "at": time.monotonic(),
        "at_wall": 123.0,
    }
    result = s.real_time_screener(marketCapMoreThan=None, sector=None, limit=25, db=_db())
    assert programado == []
    assert result["count"] == 1
    assert result["as_of"] == 123.0


def test_endpoint_cache_llena_desaloja_la_mas_vieja(monkeypatch):
    monkeypatch.setattr(s, "get_settings", _settings)
    monkeypatch.setattr(s, "_schedule_real_refresh", lambda v, t: None)
    monkeypatch.setattr(s, "_REAL_RESPONSE_CACHE_MAX", 2)
    s._real_response_cache[("yahoo", None, None, 25, 1)] = {"at": 1.0, "payload": {}}
    s._real_response_cache[("yahoo", 5.0, None, 25, 1)] = {"at": 2.0, "payload": {}}
    s._real_items_cache[1] = {
        "items": [{"symbol": "X", "marketCap": 10.0, "sector": "Technology"}],
        "vendor": "yahoo",
        "at": time.monotonic(),
        "at_wall": 1.0,
    }
    s.real_time_screener(marketCapMoreThan=None, sector=None, limit=50, db=_db())
    assert ("yahoo", None, None, 25, 1) not in s._real_response_cache
    assert ("yahoo", 5.0, None, 25, 1) in s._real_response_cache


# --- safe fetch y refetch --------------------------------------------------------------


def test_safe_fetch_quote_traga_el_fallo(monkeypatch):
    def roto(client, symbol, vendor=None):
        raise RuntimeError("vendor roto")

    monkeypatch.setattr(s, "_fetch_quote", roto)
    assert s._safe_fetch_quote(Mock(), "ASTS", "yahoo") is None


def test_safe_fetch_profile_traga_el_fallo(monkeypatch):
    def roto(client, symbol, vendor=None):
        raise RuntimeError("vendor roto")

    monkeypatch.setattr(s, "_fetch_profile", roto)
    assert s._safe_fetch_profile(Mock(), "ASTS", "yahoo") is None


class _ClienteFalso:
    def __init__(self, *a, **kw):
        self.params = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _parchear_refetch(monkeypatch, quotes):
    monkeypatch.setattr(s, "_load_universe_from_db", lambda: {})
    monkeypatch.setattr(s, "get_settings", _settings)
    monkeypatch.setattr(s.httpx, "Client", _ClienteFalso)
    monkeypatch.setattr(
        s,
        "_safe_fetch_quote",
        lambda client, symbol, vendor: quotes.get(symbol),
    )
    monkeypatch.setattr(s, "_safe_fetch_profile", lambda client, symbol, vendor: None)
    monkeypatch.setattr(s, "_load_screener_ratios", lambda live_prices=None, tenant_id=None: {})


def test_refetch_omite_simbolos_sin_quote(monkeypatch):
    primero = s._REAL_UNIVERSE[0][0]
    _parchear_refetch(monkeypatch, {primero: {"price": 9.0, "change": None,
                                              "changePercent": None, "volume": None,
                                              "prevClose": None, "asOf": None}})
    items = s._refetch_real_items(vendor="yahoo", tenant_id=1)
    assert [item["symbol"] for item in items] == [primero]
    assert items[0]["marketCap"] is None
    assert items[0]["priceTimestampKind"] == "daily_candle_open"


def test_refetch_usa_perfiles_ya_cacheados(monkeypatch):
    primero = s._REAL_UNIVERSE[0][0]
    ahora = time.monotonic()
    for symbol, _, _ in s._REAL_UNIVERSE:
        s._real_profile_cache[f"yahoo:{symbol}"] = {
            "at": ahora,
            "data": {"name": f"Nombre {symbol}", "marketCap": 1e9, "sector": "Tech", "exchange": "US"},
        }
    llamadas_perfil = []
    _parchear_refetch(monkeypatch, {primero: {"price": 9.0, "change": None,
                                              "changePercent": None, "volume": None,
                                              "prevClose": None, "asOf": None}})
    monkeypatch.setattr(
        s,
        "_safe_fetch_profile",
        lambda client, symbol, vendor: llamadas_perfil.append(symbol),
    )
    items = s._refetch_real_items(vendor="yahoo", tenant_id=1)
    assert llamadas_perfil == []
    assert items[0]["name"] == f"Nombre {primero}"
    assert items[0]["marketCap"] == 1e9


# --- segunda pasada: ramas finas ------------------------------------------------


def test_resolve_offline_ignorado_en_produccion(monkeypatch):
    monkeypatch.setattr(s, "get_settings", lambda: SimpleNamespace(is_production=True))
    assert s.resolve_screener_vendor("offline").name == "finnhub"


def test_resolve_vacio_cae_al_defecto():
    assert s.resolve_screener_vendor("  ").name == "finnhub"
    assert s.resolve_screener_vendor(None).name == "finnhub"


def test_resolve_desconocido_cae_al_defecto():
    assert s.resolve_screener_vendor("vendor-inventado").name == "finnhub"


def test_resolve_profile_vendor_con_perfiles_devuelve_el_mismo():
    assert s.resolve_profile_vendor(s.SCREEN_VENDORS["finnhub"]).name == "finnhub"


def test_resolve_profile_vendor_yahoo_sin_key_conserva_yahoo(monkeypatch):
    monkeypatch.setattr(s, "get_settings", lambda: SimpleNamespace(finnhub_api_key=None))
    assert s.resolve_profile_vendor(s.SCREEN_VENDORS["yahoo"]).name == "yahoo"


def test_resolve_profile_vendor_yahoo_con_key_usa_finnhub(monkeypatch):
    monkeypatch.setattr(s, "get_settings", lambda: SimpleNamespace(finnhub_api_key="k"))
    assert s.resolve_profile_vendor(s.SCREEN_VENDORS["yahoo"]).name == "finnhub"


def test_offline_vendor_siempre_none():
    vendor = s.OfflineScreenVendor()
    assert vendor.fetch_quote(Mock(), "ASTS") is None
    assert vendor.fetch_profile(Mock(), "ASTS") is None


def test_yahoo_fetch_profile_siempre_none():
    assert s.YahooScreenVendor().fetch_profile(Mock(), "ASTS") is None


def test_yahoo_quote_feliz(monkeypatch):
    payload = {
        "chart": {
            "result": [{
                "indicators": {"quote": [{"close": [10.0, 12.0], "volume": [100, 200]}]},
                "timestamp": [1_700_000_000, 1_700_086_400],
                "meta": {
                    "currency": "USD",
                    "chartPreviousClose": 9.5,
                    "exchangeTimezoneName": "America/New_York",
                },
            }]
        }
    }
    cliente = Mock()
    cliente.get.return_value = SimpleNamespace(status_code=200, json=lambda: payload)
    result = s.YahooScreenVendor().fetch_quote(cliente, "ASTS")
    assert result["price"] == 12.0
    assert result["change"] == 2.0
    assert result["changePercent"] == pytest.approx(20.0)
    assert result["volume"] == 200.0
    assert result["prevClose"] == 10.0
    assert result["asOf"] == 1_700_086_400
    assert result["asOfDate"] is not None


def test_yahoo_quote_payload_malformado():
    cliente = Mock()
    cliente.get.return_value = SimpleNamespace(status_code=200, json=lambda: {"chart": {}})
    assert s.YahooScreenVendor().fetch_quote(cliente, "ASTS") is None


def test_candle_market_date_tipos_malos():
    assert s._candle_market_date("no-epoch", "America/New_York") is None
    assert s._candle_market_date(1_700_000_000.0, "") is None


def test_finnhub_quote_sin_reintento_si_la_primera_va_bien(monkeypatch):
    llamadas = []

    def get_falso(client, path, symbol, timeout):
        llamadas.append(symbol)
        return {"c": 12.5, "d": 0.5, "dp": 4.0, "v": 100.0, "pc": 12.0, "t": 7}

    monkeypatch.setattr(s, "_finnhub_get", get_falso)
    result = s.FinnhubScreenVendor().fetch_quote(Mock(), "ASTS")
    assert result == {"price": 12.5, "change": 0.5, "changePercent": 4.0,
                      "volume": 100.0, "prevClose": 12.0, "asOf": 7}
    assert llamadas == ["ASTS"]


def test_finnhub_quote_precio_cero_es_none(monkeypatch):
    monkeypatch.setattr(s, "_finnhub_get", lambda *a, **kw: {"c": 0})
    monkeypatch.setattr(s.time, "sleep", lambda seg: None)
    assert s.FinnhubScreenVendor().fetch_quote(Mock(), "ASTS") is None


def test_finnhub_profile_feliz(monkeypatch):
    monkeypatch.setattr(
        s,
        "_finnhub_get",
        lambda *a, **kw: {
            "ticker": "ASTS", "name": "AST SpaceMobile", "currency": "USD",
            "marketCapitalization": 3000.0, "finnhubIndustry": "Telecom", "exchange": "NASDAQ",
        },
    )
    result = s.FinnhubScreenVendor().fetch_profile(Mock(), "ASTS")
    assert result["marketCap"] == 3000.0 * 1_000_000.0
    assert result["sector"] == "Telecom"


def test_finnhub_profile_sin_ticker_es_none(monkeypatch):
    monkeypatch.setattr(s, "_finnhub_get", lambda *a, **kw: {"name": "sin ticker"})
    assert s.FinnhubScreenVendor().fetch_profile(Mock(), "ASTS") is None


def test_ratios_sin_tenant_no_fija_scope(monkeypatch):
    db = SimpleNamespace(info={})
    from app.core import database
    from app.services import screener_fundamentals

    monkeypatch.setattr(database, "SessionLocal", lambda: _SesionFalsa(db))
    monkeypatch.setattr(
        screener_fundamentals, "load_screener_ratios", lambda db, symbols, live_prices: {}
    )
    assert s._load_screener_ratios(live_prices=None, tenant_id=None) == {}
    assert "tenant_id" not in db.info


def test_fetch_profile_follower_con_cache_stale_al_llegar(monkeypatch):
    vendor = _vendor_falso(profile={"name": "X"})
    monkeypatch.setattr(s, "resolve_screener_vendor", lambda v=None: vendor)
    # Cache vieja: el chequeo inicial falla, se entra como follower y tras la
    # espera la cache ya tiene el dato del lider.
    s._real_profile_cache["fake:ASTS"] = {"at": time.monotonic() - (s._PROFILE_TTL + 1), "data": {"name": "VIEJO"}}
    listo = threading.Event()
    listo.set()
    s._profile_singleflight["fake:ASTS"] = listo

    def espera_y_publica(timeout):
        s._real_profile_cache["fake:ASTS"] = {"at": time.monotonic(), "data": {"name": "DEL LIDER"}}

    monkeypatch.setattr(listo, "wait", espera_y_publica)
    assert s._fetch_profile(Mock(), "ASTS") == {"name": "DEL LIDER"}
    vendor.fetch_profile.assert_not_called()


def test_fetch_profile_leader_sin_dato_no_cachea(monkeypatch):
    vendor = _vendor_falso(profile=None)
    monkeypatch.setattr(s, "resolve_screener_vendor", lambda v=None: vendor)
    assert s._fetch_profile(Mock(), "ASTS") is None
    assert "fake:ASTS" not in s._real_profile_cache
    assert "fake:ASTS" not in s._profile_singleflight


def test_refresh_background_generacion_vieja_no_guarda(monkeypatch):
    monkeypatch.setattr(s, "_refetch_real_items", lambda vendor, tenant_id: [{"symbol": "X"}])
    s._real_refresh_generations[1] = 5
    s._refresh_real_items_background("yahoo", 3, 1)
    assert 1 not in s._real_items_cache


def test_schedule_refresh_cooldown_devuelve_el_terminado():
    futuro = Mock()
    futuro.done.return_value = True
    s._real_refresh_futures[1] = futuro
    s._real_refresh_last_attempt[1] = time.monotonic()
    assert s._schedule_real_refresh("yahoo", 1) is futuro


def test_schedule_refresh_lanza_nuevo_tras_cooldown(monkeypatch):
    enviado = {}

    class ExecutorFalso:
        def submit(self, fn, vendor, generation, tenant_id):
            enviado.update(fn=fn, generation=generation)
            return Mock(done=lambda: False)

    monkeypatch.setattr(s, "_real_refresh_executor", ExecutorFalso())
    futuro = s._schedule_real_refresh("yahoo", 1)
    assert enviado["generation"] == 1
    assert s._real_refresh_futures[1] is futuro


def test_active_vendor_cold_wait():
    assert s.active_vendor_allows_cold_wait("yahoo", _settings()) is True
    assert s.active_vendor_allows_cold_wait("finnhub", _settings()) is True
    assert s.active_vendor_allows_cold_wait(
        "finnhub", _settings(finnhub_api_key="k")
    ) is False


def test_endpoint_cache_hit_con_items_frescos_no_reprograma(monkeypatch):
    monkeypatch.setattr(s, "get_settings", _settings)
    programado = []
    monkeypatch.setattr(s, "_schedule_real_refresh", lambda v, t: programado.append(v))
    key = s._real_response_key("yahoo", None, None, 25, 1)
    s._real_response_cache[key] = {
        "at": time.monotonic(),
        "payload": {"source": "yahoo_finance", "screener": [], "refreshing": True},
    }
    s._real_items_cache[1] = {
        "items": [{"symbol": "X"}], "vendor": "yahoo", "at": time.monotonic(),
    }
    s.real_time_screener(marketCapMoreThan=None, sector=None, limit=25, db=_db())
    assert programado == []


def test_endpoint_carga_fria_espera_lo_minimo_y_declara_no_disponible(monkeypatch):
    monkeypatch.setattr(s, "get_settings", _settings)
    futuro = Mock()
    futuro.done.return_value = False
    futuro.result.side_effect = TimeoutError("sigue sin datos")
    monkeypatch.setattr(s, "_schedule_real_refresh", lambda v, t: futuro)
    result = s.real_time_screener(marketCapMoreThan=None, sector=None, limit=25, db=_db())
    assert result["refreshing"] is True
    assert result["unavailable"] is True
    assert result["screener"] == []


def test_refetch_perfil_del_pool_se_usa(monkeypatch):
    primero = s._REAL_UNIVERSE[0][0]
    _parchear_refetch(monkeypatch, {primero: {"price": 9.0, "change": None,
                                              "changePercent": None, "volume": None,
                                              "prevClose": None, "asOf": None}})
    monkeypatch.setattr(
        s,
        "_safe_fetch_profile",
        lambda client, symbol, vendor: {
            "name": "DelPool", "marketCap": 5e8, "sector": "Finance", "exchange": "NYSE",
        },
    )
    items = s._refetch_real_items(vendor="yahoo", tenant_id=1)
    assert items[0]["name"] == "DelPool"
    assert items[0]["marketCap"] == 5e8
    assert items[0]["exchange"] == "NYSE"


def test_endpoint_lkg_stale_no_espera_y_reprograma(monkeypatch):
    # has_lkg=True con items viejos: se programa el refresh en background pero
    # NO hay espera de cold start (924->940): la respuesta sale al instante
    # con el last-known-good.
    monkeypatch.setattr(s, "get_settings", _settings)
    futuro = Mock()
    futuro.done.return_value = True
    programado = []
    monkeypatch.setattr(
        s, "_schedule_real_refresh", lambda v, t: programado.append(v) or futuro
    )
    s._real_items_cache[1] = {
        "items": [{"symbol": "X", "marketCap": 10.0, "sector": "Technology"}],
        "vendor": "yahoo",
        "at": time.monotonic() - (s._QUOTE_TTL + 1),
        "at_wall": 50.0,
    }
    result = s.real_time_screener(marketCapMoreThan=None, sector=None, limit=25, db=_db())
    assert programado == ["yahoo"]
    assert result["refreshing"] is False
    assert result["count"] == 1
    assert result["as_of"] == 50.0
