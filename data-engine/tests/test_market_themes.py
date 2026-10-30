"""Contratos de /api/market/themes: calculo honesto de temas (YTD, 1M, cobertura)."""

from __future__ import annotations

import threading
import time
from datetime import UTC, date, datetime, timedelta

from app.api.routes import market
from app.services import market_themes as mt


def _ts(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, 21, tzinfo=UTC).timestamp())


def _candles(points: dict[date, float]) -> dict:
    days = sorted(points)
    return {"s": "ok", "t": [_ts(d) for d in days], "c": [points[d] for d in days]}


SESSION = date(2026, 10, 9)  # viernes


def _series(
    start_close: float,
    end_close: float,
    last: date = SESSION,
    base_ytd: float | None = None,
    base_1m: float | None = None,
) -> dict:
    """Serie diaria sintetica con cierres fijos en las fechas que importan."""
    pts: dict[date, float] = {}
    d = date(2025, 12, 10)
    while d <= last:
        if d.weekday() < 5:
            pts[d] = start_close
        d += timedelta(days=1)
    if base_ytd is not None:
        pts[date(2025, 12, 31)] = base_ytd
    if base_1m is not None:
        pts[date(2026, 9, 9)] = base_1m
    pts[last] = end_close
    return _candles(pts)


def _basket(name: str, tickers: list[str]) -> dict:
    return {"id": name.lower(), "name": name, "tickers": tickers}


def test_ytd_y_1m_exactos_de_un_valor():
    r = mt.symbol_returns(_series(100, 150, base_ytd=100, base_1m=120), SESSION)
    assert round(r["ytd"], 6) == 50.0
    assert round(r["m1"], 6) == 25.0
    assert r["last_date"] == SESSION


def test_ytd_usa_el_ultimo_cierre_del_año_anterior_no_el_primero_del_año():
    pts = {date(2025, 12, 30): 90.0, date(2025, 12, 31): 100.0, date(2026, 1, 2): 500.0, SESSION: 110.0}
    r = mt.symbol_returns(_candles(pts), SESSION)
    assert round(r["ytd"], 6) == 10.0


def test_sin_cierre_de_hace_un_mes_no_hay_1m_y_sin_cierre_del_año_anterior_no_hay_ytd():
    r = mt.symbol_returns(_candles({date(2026, 10, 1): 100.0, SESSION: 110.0}), SESSION)
    assert r["ytd"] is None and r["m1"] is None


def test_mes_anterior_con_fin_de_mes_corto():
    assert mt._month_back(date(2026, 3, 31)) == date(2026, 2, 28)
    assert mt._month_back(date(2026, 1, 15)) == date(2025, 12, 15)
    assert mt._month_back(date(2024, 3, 31)) == date(2024, 2, 29)


def test_valor_obsoleto_queda_fuera_de_las_metricas():
    old = _series(100, 300, last=date(2026, 9, 20), base_ytd=100, base_1m=100)
    r = mt.symbol_returns(old, SESSION)
    assert r["ytd"] is None and r["m1"] is None
    assert r["last_date"] == date(2026, 9, 20)


def test_cierres_invalidos_se_descartan():
    bad = {
        "s": "ok",
        "t": [_ts(date(2025, 12, 31)), _ts(date(2026, 6, 1)), _ts(SESSION)],
        "c": [100.0, float("nan"), 120.0],
    }
    assert round(mt.symbol_returns(bad, SESSION)["ytd"], 6) == 20.0
    assert mt.symbol_returns({"s": "no_data"}, SESSION)["ytd"] is None
    assert mt.symbol_returns(None, SESSION)["ytd"] is None


def test_media_simple_ranking_y_hot():
    baskets = [
        _basket("Alfa", ["A1", "A2"]),
        _basket("Beta", ["B1", "B2"]),
        _basket("Gama", ["G1", "G2"]),
        _basket("Delta", ["D1", "D2"]),
    ]
    candles = {
        "A1": _series(100, 200, base_ytd=100, base_1m=100),
        "A2": _series(100, 100, base_ytd=100, base_1m=100),
        "B1": _series(100, 130, base_ytd=100, base_1m=100),
        "B2": _series(100, 130, base_ytd=100, base_1m=100),
        "G1": _series(100, 110, base_ytd=100, base_1m=100),
        "G2": _series(100, 110, base_ytd=100, base_1m=100),
        "D1": _series(100, 90, base_ytd=100, base_1m=100),
        "D2": _series(100, 90, base_ytd=100, base_1m=100),
    }
    out = mt.compute_themes(candles, baskets)
    names = [t["name"] for t in out["themes"]]
    assert names == ["Alfa", "Beta", "Gama", "Delta"]
    alfa = next(t for t in out["themes"] if t["name"] == "Alfa")
    assert alfa["ytd"] == {"pct": 50.0, "n": 2}  # media simple de +100 % y 0 %
    assert [t["hot"] for t in out["themes"]] == [True, True, True, False]
    assert [t["rank"] for t in out["themes"]] == [1, 2, 3, 4]
    assert out["as_of"] == SESSION.isoformat()
    assert out["source"] == "Yahoo Finance" and out["method"] == "media simple"


def test_cobertura_minima_70_por_ciento_por_metrica():
    tickers = [f"T{i}" for i in range(10)]
    baskets = [_basket("Tema", tickers)]
    candles = {t: _series(100, 120, base_ytd=100, base_1m=100) for t in tickers[:6]}  # 60 %
    out = mt.compute_themes(candles, baskets)
    theme = out["themes"][0]
    assert theme["ytd"] == {"pct": None, "n": 6}
    assert theme["rank"] is None and theme["hot"] is False
    candles = {t: _series(100, 120, base_ytd=100, base_1m=100) for t in tickers[:7]}  # 70 %
    theme = mt.compute_themes(candles, baskets)["themes"][0]
    assert theme["ytd"] == {"pct": 20.0, "n": 7}
    assert theme["n_total"] == 10


def test_ytd_y_1m_tienen_cobertura_independiente():
    tickers = [f"T{i}" for i in range(10)]
    candles = {}
    for i, t in enumerate(tickers):
        candles[t] = _series(100, 120, base_ytd=100, base_1m=100 if i < 3 else None)
        if i >= 3:
            # sin cierre cerca de hace un mes
            pts = {date(2025, 12, 31): 100.0, date(2026, 10, 1): 110.0, SESSION: 120.0}
            candles[t] = _candles(pts)
    theme = mt.compute_themes(candles, [_basket("Tema", tickers)])["themes"][0]
    assert theme["ytd"]["pct"] == 20.0 and theme["m1"]["pct"] is None and theme["m1"]["n"] == 3


def test_giro_solo_con_signo_contrario_y_1m_relevante():
    def one(base_ytd, base_1m, end):
        c = {"X": _series(100, end, base_ytd=base_ytd, base_1m=base_1m)}
        return mt.compute_themes(c, [_basket("T", ["X"])])["themes"][0]["turn"]

    assert one(100, 80, 90) == "sube"  # YTD -10 %, 1M +12,5 %
    assert one(100, 130, 120) == "baja"  # YTD +20 %, 1M -7,7 %
    assert one(100, 100, 120) is None  # mismo signo
    assert one(100, 120.5, 120) is None  # 1M -0,4 %: por debajo del umbral


def test_sin_datos_no_inventa_nada():
    out = mt.compute_themes({}, [_basket("T", ["X"])])
    assert out["status"] == "sin_datos" and out["themes"] == [] and out["as_of"] is None


def test_un_valor_con_fecha_futura_no_deja_obsoletos_a_los_demas():
    candles = {t: _series(100, 120, base_ytd=100, base_1m=100) for t in ["A", "B", "C"]}
    candles["F"] = _series(100, 120, last=date(2026, 12, 25), base_ytd=100, base_1m=100)
    out = mt.compute_themes(candles, [_basket("T", ["A", "B", "C", "F"])])
    assert out["as_of"] == SESSION.isoformat()
    assert out["themes"][0]["ytd"]["n"] == 4


def test_cestas_sin_duplicados_internos_ni_vacias():
    assert len({b["id"] for b in mt.BASKETS}) == len(mt.BASKETS)
    for basket in mt.BASKETS:
        assert len(basket["tickers"]) >= 8, basket["id"]
        assert len(set(basket["tickers"])) == len(basket["tickers"]), basket["id"]
        assert all(t == t.upper() for t in basket["tickers"])
    assert len(mt.all_symbols()) == len(set(mt.all_symbols()))


def test_fetch_all_un_simbolo_roto_no_tumba_y_el_plazo_corta_lo_lento():
    def fetch(sym: str):
        if sym == "BAD":
            raise RuntimeError("boom")
        if sym == "SLOW":
            time.sleep(0.6)
        return {"s": "ok", "t": [1], "c": [1.0]}

    started = time.monotonic()
    out = mt.fetch_all(["OK", "BAD", "SLOW"], fetch, workers=3, deadline_seconds=0.1)
    assert time.monotonic() - started < 0.5
    assert out["OK"] is not None and out["BAD"] is None and out["SLOW"] is None


def test_cache_sirve_dato_y_no_guarda_un_calculo_sin_datos():
    clock = {"now": 0.0}
    cache = mt.ThemesCache(ttl=100, clock=lambda: clock["now"])
    calls = []

    def empty():
        calls.append("empty")
        return {"symbols_with_data": 0, "themes": []}

    assert cache.get(empty)["themes"] == []
    assert cache.get(empty)["themes"] == []
    assert calls == ["empty"]  # dentro de FAILED_TTL_SECONDS no se relanza la descarga
    clock["now"] = mt.FAILED_TTL_SECONDS + 1
    assert cache.get(empty)["themes"] == []
    assert calls == ["empty", "empty"]  # Yahoo caido: no se cachea durante una hora
    clock["now"] = 2 * mt.FAILED_TTL_SECONDS + 2

    def good():
        calls.append("good")
        return {"symbols_with_data": 5, "themes": [1]}

    assert cache.get(good)["stale"] is False
    assert cache.get(good)["themes"] == [1]
    assert calls.count("good") == 1


def test_cache_caducada_sirve_el_anterior_y_refresca_en_segundo_plano():
    clock = {"now": 0.0}
    cache = mt.ThemesCache(ttl=10, clock=lambda: clock["now"])
    cache.get(lambda: {"symbols_with_data": 1, "v": 1})
    clock["now"] = 11.0
    gate = threading.Event()
    done = threading.Event()

    def slow():
        gate.wait(2)
        done.set()
        return {"symbols_with_data": 1, "v": 2}

    stale = cache.get(slow)
    assert stale["v"] == 1 and stale["stale"] is True  # no espera al refresco
    again = cache.get(slow)  # segundo aviso mientras refresca: no lanza otro
    assert again["v"] == 1
    gate.set()
    assert done.wait(2)
    for _ in range(50):
        if cache.get(lambda: {"symbols_with_data": 1, "v": 3})["v"] == 2:
            break
        time.sleep(0.02)
    assert cache.get(lambda: {"symbols_with_data": 1, "v": 3})["v"] == 2


def test_la_ruta_usa_velas_diarias_desde_diciembre_y_publica_el_ranking(monkeypatch):
    seen = []

    def fake_fetch(client, symbol, from_ts, to_ts, interval):
        seen.append((symbol, interval, from_ts))
        return _series(100, 120, base_ytd=100, base_1m=100)

    monkeypatch.setattr(market, "_fetch_yahoo_candles", fake_fetch)
    monkeypatch.setattr(market, "_themes_cache", mt.ThemesCache())
    out = market.market_themes_ranking()
    assert out["themes"] and out["stale"] is False
    assert {i for _, i, _ in seen} == {"1d"}
    assert len(seen) == len(mt.all_symbols())
    first_from = datetime.fromtimestamp(seen[0][2], tz=UTC)
    assert (first_from.month, first_from.day) == (12, 10)


def test_marca_intradia_solo_con_la_sesion_en_curso():
    sesion = date(2026, 10, 9)
    abierto = datetime(2026, 10, 9, 15, 0, tzinfo=UTC)  # 11:00 ET
    cerrado = datetime(2026, 10, 9, 21, 0, tzinfo=UTC)  # 17:00 ET
    otro_dia = datetime(2026, 10, 10, 15, 0, tzinfo=UTC)  # sabado
    assert mt.last_point_is_intraday(sesion, abierto) is True
    assert mt.last_point_is_intraday(sesion, cerrado) is False
    assert mt.last_point_is_intraday(sesion, otro_dia) is False
    c = {"X": _series(100, 120, base_ytd=100, base_1m=100)}
    assert mt.compute_themes(c, [_basket("T", ["X"])], generated_at=abierto)["intraday"] is True
    assert mt.compute_themes(c, [_basket("T", ["X"])], generated_at=cerrado)["intraday"] is False


def test_intradia_se_recalcula_al_servir_y_no_se_queda_del_momento_de_generar():
    from datetime import UTC, datetime

    cached = {"as_of": "2026-10-12", "intraday": True, "status": "ok"}
    # 16:30 ET (20:30 UTC, octubre = EDT): ya es cierre aunque se generase a las 15:30 ET.
    assert mt.with_live_intraday(cached, datetime(2026, 10, 12, 20, 30, tzinfo=UTC))["intraday"] is False
    assert mt.with_live_intraday(cached, datetime(2026, 10, 12, 19, 30, tzinfo=UTC))["intraday"] is True
    assert mt.with_live_intraday({"as_of": None, "status": "sin_datos"}) == {
        "as_of": None,
        "status": "sin_datos",
    }


def test_resultado_parcial_caduca_pronto_y_uno_completo_dura_el_ttl():
    clock = {"now": 0.0}
    cache = mt.ThemesCache(ttl=3600, clock=lambda: clock["now"])
    calls = []

    def compute_partial():
        calls.append(1)
        return {"symbols_with_data": 5, "status": "parcial"}

    cache.get(compute_partial)
    clock["now"] = 299
    assert cache.get(compute_partial)["stale"] is False
    clock["now"] = 301
    assert cache.get(compute_partial)["stale"] is True  # caducado a los 5 min, no a la hora

    ok = mt.ThemesCache(ttl=3600, clock=lambda: clock["now"])
    clock["now"] = 0
    ok.get(lambda: {"symbols_with_data": 5, "status": "ok"})
    clock["now"] = 3000
    assert ok.get(lambda: {"symbols_with_data": 5, "status": "ok"})["stale"] is False


def test_toda_cesta_curada_justifica_sus_valores():
    """Cada ticker de las cestas publicadas lleva su razon (verificable, corta),
    y no hay razones colgadas de tickers que ya no estan."""
    assert mt.REASONS, "sin razones curadas"
    for basket in mt.BASKETS:
        reasons = mt.REASONS.get(basket["id"], {})
        for ticker in basket["tickers"]:
            reason = reasons.get(ticker)
            assert reason, f"{basket['id']}:{ticker} sin justificacion"
            assert len(reason) <= 70, f"{basket['id']}:{ticker} razon demasiado larga"
        extra = set(reasons) - set(basket["tickers"])
        assert not extra, f"{basket['id']}: razones sobrantes {sorted(extra)}"


def test_la_justificacion_llega_al_constituyente():
    candles = {t: _series(100, 110, base_ytd=100, base_1m=100) for t in ("NVDA", "AMD")}
    basket = {
        "id": "semiconductores",
        "name": "Semiconductores",
        "tickers": ["NVDA", "AMD"],
    }
    out = mt.compute_themes(candles, baskets=[basket])
    rows = {r["ticker"]: r for r in out["themes"][0]["constituents"]}
    assert rows["NVDA"]["reason"] == "GPU dominantes para entrenar IA"
    assert rows["AMD"]["reason"] == "CPU EPYC y GPU Instinct"


def test_yahoo_caido_no_relanza_la_descarga_en_cada_visita_ni_encola_peticiones():
    """Sin datos, cada visita recalculaba (hasta 40 s) y las concurrentes esperaban en fila."""
    clock = {"now": 0.0}
    cache = mt.ThemesCache(ttl=3600, clock=lambda: clock["now"])
    calls = []
    started = threading.Event()
    release = threading.Event()

    def outage():
        calls.append(1)
        started.set()
        release.wait(5)
        return {"symbols_with_data": 0, "themes": []}

    results = []
    first = threading.Thread(target=lambda: results.append(cache.get(outage)))
    first.start()
    assert started.wait(5)
    others = [threading.Thread(target=lambda: results.append(cache.get(outage))) for _ in range(4)]
    for th in others:
        th.start()
    release.set()
    for th in [first, *others]:
        th.join(5)
    assert len(results) == 5 and all(r["themes"] == [] for r in results)
    assert len(calls) == 1
    assert cache.get(outage)["symbols_with_data"] == 0
    assert len(calls) == 1
    clock["now"] = mt.FAILED_TTL_SECONDS + 1
    cache.get(lambda: {"symbols_with_data": 3, "themes": [1]})
    assert cache.get(outage)["themes"] == [1]  # el dato bueno manda en cuanto vuelve Yahoo
