"""A/B real de carriles por proveedor (#3763): workers Dramatiq reales contra
un Redis aislado (TcpFakeServer, uno por corrida; nada de red/DB de prod).

Topologia A (actual): 1 worker, 2 hilos, una cola compartida "shared".
Topologia B (propuesta): 2 workers de 2 hilos, colas "largo" y "corto".
Carga identica en ambas: 2 largos + 20 cortos, mismo orden (semilla fija).
Metrica: segundos desde el primer encolado hasta que termina el ultimo corto.

Uso: python run_ab.py --pares 5 --largo 20 --corto 0.5 --semilla 31
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path

import redis

HERE = Path(__file__).resolve().parent


def _arranca_worker(url: str, ns: str, cola: str, largo: float, corto: float,
                    colas: dict) -> subprocess.Popen:
    env = dict(os.environ, BENCH_REDIS_URL=url, BENCH_NS=ns,
               BENCH_LONG_S=str(largo), BENCH_SHORT_S=str(corto),
               BENCH_QUEUE_LARGO=colas["largo"], BENCH_QUEUE_CORTO=colas["corto"],
               PYTHONPATH=str(HERE))
    return subprocess.Popen(
        [sys.executable, "-m", "dramatiq", "bench_actors",
         "--processes", "1", "--threads", "2", "-Q", cola],
        cwd=HERE, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _puerto_libre() -> int:
    import socket
    with socket.socket() as sck:
        sck.bind(("127.0.0.1", 0))
        return sck.getsockname()[1]


def _corrida(topologia: str, largo: float, corto: float, semilla: int,
             redis_bin: str, datos: str) -> dict:
    puerto = _puerto_libre()
    Path(datos).mkdir(parents=True, exist_ok=True)
    server = subprocess.Popen(
        [redis_bin, "--port", str(puerto), "--bind", "127.0.0.1",
         "--dir", datos, "--save", "", "--appendonly", "no",
         "--maxmemory", "64mb", "--maxmemory-policy", "noeviction"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"redis://127.0.0.1:{puerto}"
    ns = f"bench-{topologia}"
    workers = []
    try:
        for _ in range(80):  # espera al PING del Redis aislado
            try:
                if redis.Redis.from_url(url, socket_connect_timeout=0.3).ping():
                    break
            except redis.RedisError:
                time.sleep(0.1)
        else:
            raise RuntimeError("el Redis aislado no respondio")
        redis.Redis.from_url(url).flushall()
        colas = ({"largo": "shared", "corto": "shared"} if topologia == "A"
                 else {"largo": "largo", "corto": "corto"})
        if topologia == "A":
            workers.append(_arranca_worker(url, ns, "shared", largo, corto, colas))
        else:
            workers.append(_arranca_worker(url, ns, "largo", largo, corto, colas))
            workers.append(_arranca_worker(url, ns, "corto", largo, corto, colas))
        time.sleep(2.5)  # arranque de workers (solo duermen en espera)
        env = dict(os.environ, BENCH_REDIS_URL=url, BENCH_NS=ns,
                   BENCH_LONG_S=str(largo), BENCH_SHORT_S=str(corto),
                   BENCH_QUEUE_LARGO=colas["largo"], BENCH_QUEUE_CORTO=colas["corto"],
                   PYTHONPATH=str(HERE))
        # Encolado identico en ambas topologias (misma semilla, mismo orden).
        # Forma del incidente (31-oct): los 2 largos llegan primero y ocupan
        # los 2 hilos; los cortos se encolan detras. La semilla solo baraja
        # el orden INTERNO de los cortos, identico entre A y B del mismo par.
        rng = random.Random(semilla)
        cortos = [f"C{i}" for i in range(20)]
        rng.shuffle(cortos)
        orden = ["L0", "L1"] + cortos
        encolar = subprocess.run(
            [sys.executable, "-c", ENCOLADOR, *orden],
            cwd=HERE, env=env, capture_output=True, text=True)
        if encolar.returncode != 0:
            raise RuntimeError(f"encolador fallo: {encolar.stderr[-400:]}")
        t0 = float(encolar.stdout.strip())
        cli = redis.Redis.from_url(url)
        limite = time.time() + largo + 180
        while time.time() < limite:
            fines = [cli.lindex(f"bench:marca:corto:{i}:fin", -1) for i in range(20)]
            fin_largos = [cli.lindex(f"bench:marca:largo:{i}:fin", -1) for i in range(2)]
            if all(fines) and all(fin_largos):
                fines = [float(f) for f in fines]
                fin_largos = [float(f) for f in fin_largos]
                return {"ultimo_corto_s": round(max(fines) - t0, 3),
                        "makespan_s": round(max(max(fines), *fin_largos) - t0, 3)}
            time.sleep(0.25)
        raise TimeoutError(f"corrida {topologia} no dreno en el limite")
    finally:
        for w in workers:
            w.terminate()
        for w in workers:
            w.wait(timeout=10)
        server.terminate()
        server.wait(timeout=10)


ENCOLADOR = """
import sys, time
import bench_actors as b
t0 = time.time()
for nombre in sys.argv[1:]:
    if nombre.startswith("L"):
        b.bench_largo.send(int(nombre[1:]))
    else:
        b.bench_corto.send(int(nombre[1:]))
print(t0)
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pares", type=int, default=5)
    ap.add_argument("--largo", type=float, default=20.0)
    ap.add_argument("--corto", type=float, default=0.5)
    ap.add_argument("--semilla", type=int, default=31)
    ap.add_argument("--redis-bin", default="/tmp/redis-bin/usr/bin/redis-server")
    ap.add_argument("--datos", default="/tmp/redis-run")
    ap.add_argument("--out", default="/tmp/ab-carriles.jsonl")
    ap.add_argument("--desde", type=int, default=1, help="primer par a correr")
    args = ap.parse_args()
    resultados = []
    for par in range(args.desde, args.pares + 1):
        orden = ("A", "B") if par % 2 == 1 else ("B", "A")  # alterna deriva
        fila = {"par": par, "orden": orden}
        for topo in orden:
            fila[topo] = _corrida(topo, args.largo, args.corto, args.semilla + par, args.redis_bin, args.datos)
            print(f"par {par} {topo}: {fila[topo]}", flush=True)
        resultados.append(fila)
        with open(args.out, "a") as fh:
            fh.write(json.dumps(fila, ensure_ascii=False) + "\n")
    a = [r["A"]["ultimo_corto_s"] for r in resultados]
    b = [r["B"]["ultimo_corto_s"] for r in resultados]
    salida = {
        "metrica": "segundos hasta que termina el ultimo corto (2 largos + 20 cortos)",
        "comando": f"python run_ab.py --pares {args.pares} --largo {args.largo} --corto {args.corto} --semilla {args.semilla}",
        "duraciones_s": {"largo": args.largo, "corto": args.corto},
        "semilla": args.semilla,
        "pares": resultados,
        "mediana_A_s": statistics.median(a),
        "mediana_B_s": statistics.median(b),
        "mejora_x": round(statistics.median(a) / statistics.median(b), 2),
    }
    print(json.dumps(salida, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
