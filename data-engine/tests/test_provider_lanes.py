"""Carriles de ingesta por proveedor (Finnhub / GDELT / Yahoo-Google news).

Medido en prod (31-oct, piloto): 2 refresh_valuation_metrics largos en los 2
hilos de default sosteniendo 7.617 pendientes. La tasa por proveedor la fijan
los pacers/frenos en Redis (Finnhub ~60/min compartido, GDELT 1/5s por IP,
Yahoo/Google 1 req/1,5 s): los hilos solo solapan latencia, asi que cada
carril va con 2 hilos y NO se suben a ciegas.

La prueba A/B de aislamiento del final es el MODELO de eventos discretos; el
A/B REAL con workers Dramatiq y Redis aislado (5 pares, 4,8x) vive en
scripts/perf_ab/ (README con comando exacto y tabla de tiempos).
"""
from __future__ import annotations

import heapq
from pathlib import Path

import yaml

COMPOSE_PATH = Path(__file__).resolve().parents[2] / "docker-compose.prod.yml"


class _ComposeLoader(yaml.SafeLoader):
    pass


_ComposeLoader.add_multi_constructor(
    "!",
    lambda loader, tag, node: loader.construct_sequence(node)
    if isinstance(node, yaml.SequenceNode)
    else (loader.construct_mapping(node) if isinstance(node, yaml.MappingNode)
          else loader.construct_scalar(node)),
)


# Toda la ingesta ligada a Yahoo/yfinance va al carril "yahoo" (31-oct, el
# carril de tests rojos encontro 4 actores Yahoo sueltos en default).
ACTORES_YAHOO = [
    "refresh_ticker_news",        # Yahoo + Google RSS
    "ingest_ca_insider_yahoo",    # Yahoo quoteSummary
    "ingest_corporate_splits",    # Yahoo (FMP de respaldo)
    "sync_portfolio_dividends",   # Yahoo (FMP de respaldo)
    "sync_paper_dividends",       # Yahoo
    "refresh_earnings_calendar",  # Yahoo calendarEvents (+NASDAQ)
]

# Actores que llaman a Yahoo/yfinance y NO van al carril "yahoo", con motivo
# INTENCIONADO fijado aqui (no descuido):
YAHOO_FUERA_INTENCIONADO = {
    # Mixto yfinance + contraste Finnhub: carril externo mixto.
    "refresh_valuation_metrics": "externa",
    # Precios Yahoo: ya tenian carril propio "prices" (worker-prices, pacer 1,5 s).
    "refresh_portfolio_prices_intraday": "prices",
    # Pipeline propicks co-localizado en computed: si Yahoo frena, el pipeline
    # que necesita esos precios tambien se frena; separarlos no aislava nada.
    "refresh_propicks_prices": "computed",
    "ingest_spy_daily": "computed",
}


def test_routing_por_proveedor():
    from app.workers.dramatiq_app import broker

    esperado = {
        **dict.fromkeys(ACTORES_YAHOO, "yahoo"),
        **YAHOO_FUERA_INTENCIONADO,
        "backfill_finnhub_profiles": "finnhub",
        "backfill_sec_fundamentals": "externa",
        "backfill_company_price_history": "externa",
        # GDELT ya tenia carril propio.
        "refresh_news": "gdelt",
        "refresh_macro_news": "gdelt",
    }
    for nombre, cola in esperado.items():
        assert broker.get_actor(nombre).queue_name == cola, nombre


def test_enumeracion_completa_actores_yahoo():
    """Barrido estatico (mismo criterio que el carril de tests rojos): TODO
    actor cuyo codigo mencione yahoo/yfinance esta en el carril "yahoo" o
    fijado como intencionado en otro carril con su motivo. Un actor nuevo
    que llame a Yahoo rompe este test hasta que se ubique a proposito."""
    import re
    from pathlib import Path

    from app.workers.dramatiq_app import broker

    fuente = (Path(__file__).resolve().parents[1]
              / "app" / "workers" / "dramatiq_app.py").read_text()
    encontrados = set()
    for parte in fuente.split("@dramatiq.actor(")[1:]:
        m = re.search(r"\ndef (\w+)\(", parte)
        if not m:
            continue
        nombre = m.group(1)
        segmento = parte[:parte.find(f"def {nombre}(") + 4000]
        if re.search(r"yahoo|yfinance", segmento, re.I):
            encontrados.add(nombre)
    esperados = set(ACTORES_YAHOO) | set(YAHOO_FUERA_INTENCIONADO)
    assert encontrados == esperados, (
        f"sin clasificar: {encontrados - esperados}; "
        f"ya no usan Yahoo: {esperados - encontrados}")
    for nombre in encontrados:
        destino = ("yahoo" if nombre in ACTORES_YAHOO
                   else YAHOO_FUERA_INTENCIONADO[nombre])
        assert broker.get_actor(nombre).queue_name == destino, nombre


def test_workers_de_proveedor_en_compose():
    compose = yaml.load(COMPOSE_PATH.read_text(), Loader=_ComposeLoader)
    fin = compose["services"]["worker-finnhub"]
    assert fin["command"][fin["command"].index("-Q") + 1] == "finnhub"
    assert "FINNHUB_API_KEY" in fin["environment"]
    assert fin["environment"]["dramatiq_queue_prefetch"] == "1"
    yahoo = compose["services"]["worker-yahoo"]
    assert yahoo["command"][yahoo["command"].index("-Q") + 1] == "yahoo"
    # Transicion: drena la cola efimera del primer despliegue de #3763.
    assert "yahoo-news" in yahoo["command"]
    # Nadie mas consume los carriles nuevos: el aislamiento es real.
    for nombre in ("worker", "worker-externa", "worker-gdelt"):
        comando = compose["services"][nombre]["command"]
        assert "finnhub" not in comando and '"yahoo"' not in comando, nombre
    # Presupuesto de memoria intacto (techo 16 GiB, host 24 GB).
    total = 0
    for svc in compose["services"].values():
        memoria = str(svc["deploy"]["resources"]["limits"]["memory"])
        valor = float(memoria.rstrip("MG"))
        total += int(valor * 1024) if memoria.endswith("G") else int(valor)
    assert total <= 16384, f"los limites suman {total} MiB"


def _simula(colas: dict[str, int], trabajos: list[tuple[str, float]]) -> float:
    """Modelo de eventos discretos: devuelve el instante en que termina el
    ultimo trabajo CORTO. Cada cola tiene N hilos; los trabajos se atienden
    en orden de llegada por cola."""
    hilos = {c: [0.0] * n for c, n in colas.items()}  # heap de liberacion
    fin_cortos = 0.0
    for cola, duracion in trabajos:
        libre = heapq.heapreplace(hilos[cola], hilos[cola][0] + duracion)
        if duracion < 1.0:
            fin_cortos = max(fin_cortos, libre)
    return fin_cortos


def test_ab_aislamiento_carril_dedicado():
    """Forma del incidente real: 2 corridas largas (2 hilos ocupados) + 20
    trabajos cortos de OTRO proveedor. Compartido vs carriles dedicados."""
    largos = [("larga", 60.0), ("larga", 60.0)]
    cortos = [("corta", 0.3)] * 20
    compartido = _simula({"shared": 2}, [("shared", d) for _, d in largos + cortos])
    dedicado = _simula({"larga": 2, "corta": 2}, largos + cortos)
    # Compartido: los cortos esperan a que se libere un hilo (~60 s).
    # Dedicado: los cortos drenan en su carril (~2 s de cola interna).
    assert compartido >= 60.0
    assert dedicado <= 3.0
    print(f"\nA/B modelo: cortos terminan en {dedicado:.1f}s dedicado "
          f"vs {compartido:.1f}s compartido ({compartido / dedicado:.0f}x)")
