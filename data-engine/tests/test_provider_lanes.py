"""Carriles de ingesta por proveedor (Finnhub / GDELT / Yahoo-Google news).

Medido en prod (31-oct, piloto): 2 refresh_valuation_metrics largos en los 2
hilos de default sosteniendo 7.617 pendientes. La tasa por proveedor la fijan
los pacers/frenos en Redis (Finnhub ~60/min compartido, GDELT 1/5s por IP,
Yahoo/Google 1 req/1,5 s): los hilos solo solapan latencia, asi que cada
carril va con 2 hilos y NO se suben a ciegas.

La prueba A/B es un MODELO de eventos discretos (no prod): mide el efecto de
aislamiento con la forma del incidente real; las cifras de prod las mide el
piloto con su A/B tras el despliegue.
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


def test_routing_por_proveedor():
    from app.workers.dramatiq_app import broker

    esperado = {
        "backfill_finnhub_profiles": "finnhub",
        "refresh_ticker_news": "yahoo-news",
        "ingest_ca_insider_yahoo": "yahoo-news",
        # Mixto (yfinance + contraste Finnhub): se queda en externa.
        "refresh_valuation_metrics": "externa",
        "backfill_sec_fundamentals": "externa",
        "backfill_company_price_history": "externa",
        # GDELT ya tenia carril propio.
        "refresh_news": "gdelt",
        "refresh_macro_news": "gdelt",
    }
    for nombre, cola in esperado.items():
        assert broker.get_actor(nombre).queue_name == cola, nombre


def test_workers_de_proveedor_en_compose():
    compose = yaml.load(COMPOSE_PATH.read_text(), Loader=_ComposeLoader)
    fin = compose["services"]["worker-finnhub"]
    assert fin["command"][fin["command"].index("-Q") + 1] == "finnhub"
    assert "FINNHUB_API_KEY" in fin["environment"]
    assert fin["environment"]["dramatiq_queue_prefetch"] == "1"
    yahoo = compose["services"]["worker-yahoo-news"]
    assert yahoo["command"][yahoo["command"].index("-Q") + 1] == "yahoo-news"
    # Nadie mas consume los carriles nuevos: el aislamiento es real.
    for nombre in ("worker", "worker-externa", "worker-gdelt"):
        comando = compose["services"][nombre]["command"]
        assert "finnhub" not in comando and "yahoo-news" not in comando, nombre
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
