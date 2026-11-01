"""A/B de carga sobre Postgres restaurado con topes de memoria. Reproducible.

Apoyo al A/B de Postgres: para CADA tope (896m, 4g, 6g, 8g...) el ciclo es el
mismo y la carga es LA MISMA, para que la unica variable sea el tope (y la
config que el piloto aplique entre ejecuciones):

  1. Entorno aislado propio (cavaai-loadab-*) con Postgres TOPEADO con
     --memory/--memory-swap (sin swap: el tope es duro; si no cabe, OOM, y eso
     es un RESULTADO del A/B, no un fallo del instrumento).
  2. Semilla determinista (mismo modulo que el drill, N companies).
  3. Backup de los tres pilares -> destruir -> restore -> VERIFICACION de
     restore (fase de datos, fail-closed) tras cada cambio de tope.
  4. Carga determinista (mismo plan de consultas, misma semilla, un solo
     cliente, SIN backup concurrente: las corridas son secuenciales) con
     tiempos por consulta y pico de memoria del contenedor.
  5. Informe JSON por tope.

Un tope que rompe el restore o mata Postgres por OOM NO hace fallar el
instrumento: queda registrado en el informe (eso es exactamente lo que el A/B
quiere saber). El instrumento solo devuelve 1 si el propio instrumento no
puede ejecutarse (docker ausente, argumentos invalidos...): fail-closed.

Modo externo (`--external`): el piloto apunta el MISMO plan de carga (y, si
pasa --backup-dir y los endpoints, la verificacion) contra la copia restaurada
de la VM con el tope que el haya aplicado al contenedor. Misma carga, medida
igual, comparable con la matriz local.

Uso:
    python -m scripts.backup.pg_load_ab --caps 896m,4g,6g,8g --out load_ab.json
    python -m scripts.backup.pg_load_ab --external \
        --database-url postgresql://... --cap-label 4g --out load_vm_4g.json
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import statistics
import sys
import tempfile
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.backup._kit import (  # noqa: E402
    FailClosedError,
    PsqlTarget,
    format_table,
    new_backup_id,
    redact,
    require,
    require_tool,
    run,
)
from scripts.backup.disaster_drill import (  # noqa: E402
    MINIO_PASSWORD,
    MINIO_USER,
    PG_PASSWORD,
    PG_USER,
    SEED_BUCKET,
    DrillEnvironment,
    seed_all,
)

CAP_PATTERN = re.compile(r"^\d+[mMgG]$")
DEFAULT_CAPS = ("896m", "4g", "6g", "8g")
DEFAULT_COMPANIES = 500
DEFAULT_ROUNDS = 3
DEFAULT_SEED = 42

# Plantillas de la carga. FIJAS: cualquier cambio aqui invalida la
# comparabilidad entre topes y entre ejecuciones del A/B (por eso el orden y
# los parametros salen de una semilla fija, no del azar del momento).
TEMPLATES = ("count", "window", "sort")
WINDOW_ROWS = 200
SORT_ROWS = 50


def parse_caps(text: str) -> list[str]:
    """'896m,4g' -> ['896m', '4g'], validando el formato docker de memoria."""
    caps = [cap.strip().lower() for cap in text.split(",") if cap.strip()]
    require(bool(caps), "lista de topes vacia")
    for cap in caps:
        require(
            bool(CAP_PATTERN.match(cap)),
            f"tope '{cap}' no tiene formato docker de memoria (ejemplos: 896m, 4g)",
        )
    return caps


@dataclass(frozen=True)
class TableInfo:
    name: str
    order_col: str
    text_col: str | None
    est_rows: int


@dataclass(frozen=True)
class Step:
    template: str
    table: str
    sql: str


def discover_tables(conn) -> list[TableInfo]:
    """Tablas de public ordenadas por nombre: la carga es generica para valer
    igual contra la semilla sintetica y contra la copia restaurada real."""
    rows = conn.execute(
        """
        SELECT t.table_name,
               (SELECT c.column_name FROM information_schema.columns c
                 WHERE c.table_schema = 'public' AND c.table_name = t.table_name
                 ORDER BY c.ordinal_position LIMIT 1) AS first_col,
               (SELECT c.column_name FROM information_schema.columns c
                 WHERE c.table_schema = 'public' AND c.table_name = t.table_name
                   AND c.data_type IN ('text', 'character varying')
                 ORDER BY c.ordinal_position LIMIT 1) AS text_col
        FROM information_schema.tables t
        WHERE t.table_schema = 'public' AND t.table_type = 'BASE TABLE'
        ORDER BY t.table_name
        """
    ).fetchall()
    tables: list[TableInfo] = []
    for name, first_col, text_col in rows:
        if not first_col:
            continue
        est = conn.execute(
            "SELECT GREATEST(c.reltuples, 0)::bigint FROM pg_class c"
            " JOIN pg_namespace n ON n.oid = c.relnamespace"
            " WHERE n.nspname = 'public' AND c.relname = %s",
            (name,),
        ).fetchone()[0]
        tables.append(
            TableInfo(name=name, order_col=first_col, text_col=text_col, est_rows=int(est))
        )
    require(bool(tables), "la base restaurada no tiene tablas en public: nada que medir")
    return tables


def build_plan(tables: list[TableInfo], *, rounds: int, seed: int) -> list[Step]:
    """Plan completo y DETERMINISTA: mismas tablas, orden y offsets -> mismos
    pasos. El azar sale de `seed`, no del reloj, asi que cada tope ejecuta
    exactamente la misma carga."""
    rng = random.Random(seed)
    plan: list[Step] = []
    for _round in range(rounds):
        for table in tables:
            quoted = '"' + table.name.replace('"', '""') + '"'
            plan.append(
                Step("count", table.name, f"SELECT count(*) FROM {quoted}")
            )
            offset = rng.randint(0, max(table.est_rows - 1, 0))
            order_col = '"' + table.order_col.replace('"', '""') + '"'
            plan.append(
                Step(
                    "window",
                    table.name,
                    f"SELECT * FROM {quoted} ORDER BY {order_col}"
                    f" LIMIT {WINDOW_ROWS} OFFSET {offset}",
                )
            )
            if table.text_col:
                text_col = '"' + table.text_col.replace('"', '""') + '"'
                plan.append(
                    Step(
                        "sort",
                        table.name,
                        f"SELECT * FROM {quoted} ORDER BY {text_col} LIMIT {SORT_ROWS}",
                    )
                )
    require(bool(plan), "plan de carga vacio")
    return plan


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    index = min(int(round((pct / 100) * (len(sorted_values) - 1))), len(sorted_values) - 1)
    return sorted_values[index]


def run_load(database_url: str, *, rounds: int, seed: int) -> dict[str, Any]:
    """Ejecuta el plan y mide. Un solo cliente: la carga es fija y medible;
    el objetivo es comparar topes, no estresar concurrencia."""
    import psycopg  # dependencia del proyecto; se importa aqui para que el
    # parseo de argumentos y los tests de contrato no la necesiten.

    timings: dict[str, list[float]] = {template: [] for template in TEMPLATES}
    started = time.perf_counter()
    with psycopg.connect(database_url, connect_timeout=15, autocommit=True) as conn:
        tables = discover_tables(conn)
        plan = build_plan(tables, rounds=rounds, seed=seed)
        for step in plan:
            t0 = time.perf_counter()
            conn.execute(step.sql).fetchall()
            timings[step.template].append((time.perf_counter() - t0) * 1000)
    wall_ms = (time.perf_counter() - started) * 1000
    per_template = {}
    for template, values in timings.items():
        values = sorted(values)
        if not values:
            continue
        per_template[template] = {
            "n": len(values),
            "total_ms": round(sum(values), 1),
            "mean_ms": round(statistics.fmean(values), 2),
            "p50_ms": round(_percentile(values, 50), 2),
            "p95_ms": round(_percentile(values, 95), 2),
            "max_ms": round(values[-1], 2),
        }
    return {
        "tables": len(tables),
        "steps": len(plan),
        "rounds": rounds,
        "seed": seed,
        "wall_ms": round(wall_ms, 1),
        "per_template": per_template,
    }


_MEM_USAGE = re.compile(r"^([\d.]+)\s*([KMGT]?i?B)")


def _parse_mem_usage(text: str) -> int:
    """'123.4MiB / 896MiB' -> bytes usados. 0 si no se puede parsear."""
    match = _MEM_USAGE.match(text.strip())
    if not match:
        return 0
    value, unit = match.groups()
    factor = {
        "B": 1, "KB": 1000, "MB": 1000**2, "GB": 1000**3, "TB": 1000**4,
        "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3, "TiB": 1024**4,
    }.get(unit, 1)
    return int(float(value) * factor)


class MemSampler:
    """Muestrea `docker stats` mientras corre la carga y guarda el pico."""

    def __init__(self, container: str) -> None:
        self.container = container
        self.peak_bytes = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def _loop(self) -> None:
        while not self._stop.is_set():
            result = run(
                ["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", self.container],
                timeout=30,
                check=False,
                what="docker stats",
            )
            self.peak_bytes = max(self.peak_bytes, _parse_mem_usage(result.stdout))
            self._stop.wait(0.5)

    def __enter__(self) -> MemSampler:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=10)


def container_state(container: str) -> dict[str, Any]:
    """OOMKilled y estado del contenedor: un OOM bajo un tope es un DATO."""
    result = run(
        ["docker", "inspect", "-f", "{{.State.OOMKilled}} {{.State.Status}}", container],
        timeout=60,
        check=False,
        what="docker inspect",
    )
    parts = result.stdout.split()
    return {
        "oom_killed": parts[0] == "true" if parts else False,
        "status": parts[1] if len(parts) > 1 else "unknown",
    }


def run_cap_cycle(
    cap: str,
    *,
    workdir: Path,
    companies: int,
    rounds: int,
    seed: int,
    keep: bool,
) -> dict[str, Any]:
    """Ciclo completo para UN tope: seed -> backup -> destroy -> restore ->
    verificacion -> carga. Devuelve el resultado del tope (nunca lanza por un
    tope inviable: eso es el dato que busca el A/B)."""
    from scripts.backup import backup_all
    from scripts.restore import restore_minio, restore_postgres, restore_qdrant, verify_restore

    result: dict[str, Any] = {"cap": cap, "restore_ok": False, "verify_ok": False, "load_ok": False}
    drill = DrillEnvironment(workdir=workdir, keep=keep, pg_memory=cap)
    backup_dir = workdir / "backup"
    try:
        drill.require_isolated()
        drill.up()
        os.environ["DRILL_COMPANIES"] = str(companies)
        seed_all(drill)

        backup_args = backup_all.build_parser().parse_args(
            [
                "--out", str(backup_dir),
                "--backup-id", new_backup_id(),
                "--pg-mode", "docker",
                "--pg-container", drill.containers["postgres"],
                "--pg-user", PG_USER,
                "--pg-database", "cavaai_drill",
                "--minio-endpoint", f"127.0.0.1:{drill.minio_port}",
                "--minio-access-key", MINIO_USER,
                "--minio-secret-key", MINIO_PASSWORD,
                "--minio-bucket", SEED_BUCKET,
                "--qdrant-url", f"http://127.0.0.1:{drill.qdrant_port}",
            ]
        )
        builder, backup_dir = backup_all.run_all(backup_args)
        builder.write()

        drill.destroy()  # borra TODO y levanta vacio CON EL MISMO TOPE
        pg_container = drill.containers["postgres"]
        restore_postgres.run_restore(backup_dir, mode="docker", container=pg_container, user=PG_USER)
        restore_minio.run_restore(
            backup_dir,
            endpoint=f"127.0.0.1:{drill.minio_port}",
            access_key=MINIO_USER,
            secret_key=MINIO_PASSWORD,
        )
        restore_qdrant.run_restore(backup_dir, url=f"http://127.0.0.1:{drill.qdrant_port}")
        result["restore_ok"] = True

        # Verificacion de restore tras el cambio de tope (fase de datos).
        verify_config = verify_restore.VerifyConfig(
            manifest_path=backup_dir,
            pg_target=PsqlTarget(
                mode="docker", database="postgres", user=PG_USER, container=pg_container
            ),
            minio_endpoint=f"127.0.0.1:{drill.minio_port}",
            minio_access_key=MINIO_USER,
            minio_secret_key=MINIO_PASSWORD,
            qdrant_url=f"http://127.0.0.1:{drill.qdrant_port}",
            qdrant_api_key=None,
            app_base_url=None,
            versions_dir=None,
        )
        data_ok, data_results, data_report = verify_restore.verify(
            verify_config, phase=verify_restore.PHASE_DATA
        )
        print(format_table(data_results, heading=f"Verificacion de datos (tope {cap})"))
        result["verify_ok"] = data_ok
        result["verify"] = {
            "passed": data_report["checks_passed"],
            "total": data_report["checks_total"],
        }
        require(
            data_ok,
            f"el restore con tope {cap} no pasa la verificacion de datos: "
            f"{data_report['checks_passed']}/{data_report['checks_total']}",
        )

        database_url = (
            f"postgresql://{PG_USER}:{PG_PASSWORD}@127.0.0.1:{drill.pg_port}/cavaai_drill"
        )
        with MemSampler(pg_container) as sampler:
            result["load"] = run_load(database_url, rounds=rounds, seed=seed)
        result["load_ok"] = True
        result["mem_peak_bytes"] = sampler.peak_bytes
        result["container"] = container_state(pg_container)
    except FailClosedError as exc:
        result["failure"] = str(exc)
    except Exception as exc:  # noqa: BLE001 - un OOM o caida del motor es un DATO del tope
        result["failure"] = f"{type(exc).__name__}: {redact(str(exc))}"
        if drill.containers.get("postgres"):
            state = container_state(drill.containers["postgres"])
            result["container"] = state
            if state["oom_killed"]:
                result["failure"] += " (Postgres OOM-killed bajo este tope)"
    finally:
        drill.cleanup()
    return result


def run_external(args: argparse.Namespace) -> dict[str, Any]:
    """Carga (y verificacion, si hay --backup-dir) contra una copia restaurada
    externa: la VM del piloto con el tope que el haya aplicado."""
    result: dict[str, Any] = {"cap": args.cap_label, "external": True}
    if args.backup_dir:
        from scripts.restore import verify_restore

        verify_config = verify_restore.VerifyConfig(
            manifest_path=Path(args.backup_dir),
            pg_target=PsqlTarget(
                mode="local",
                database=args.pg_database,
                user=args.pg_user,
                host=args.pg_host,
                port=args.pg_port,
                password=args.pg_password,
            ),
            minio_endpoint=args.minio_endpoint,
            minio_access_key=args.minio_access_key,
            minio_secret_key=args.minio_secret_key,
            qdrant_url=args.qdrant_url,
            qdrant_api_key=None,
            app_base_url=None,
            versions_dir=None,
        )
        data_ok, data_results, data_report = verify_restore.verify(
            verify_config, phase=verify_restore.PHASE_DATA
        )
        print(format_table(data_results, heading="Verificacion de datos (externo)"))
        result["verify_ok"] = data_ok
        result["verify"] = {
            "passed": data_report["checks_passed"],
            "total": data_report["checks_total"],
        }
        require(
            data_ok,
            "la copia restaurada no pasa la verificacion de datos tras el cambio",
        )
    result["load"] = run_load(args.database_url, rounds=args.rounds, seed=args.seed)
    result["load_ok"] = True
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--caps", default=",".join(DEFAULT_CAPS),
                        help="topes docker separados por coma (defecto: %(default)s)")
    parser.add_argument("--companies", type=int, default=DEFAULT_COMPANIES,
                        help="companies sembradas (defecto: %(default)s)")
    parser.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS,
                        help="rondas del plan de carga (defecto: %(default)s)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED,
                        help="semilla del plan (defecto: %(default)s; no la cambies entre topes)")
    parser.add_argument("--out", default=None, help="ruta del informe JSON")
    parser.add_argument("--keep", action="store_true", help="no borrar el ultimo entorno")
    parser.add_argument("--external", action="store_true",
                        help="modo externo: carga/verificacion contra una copia restaurada fuera")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--cap-label", default="external",
                        help="etiqueta del tope aplicado fuera (solo informativa)")
    parser.add_argument("--backup-dir", default=None,
                        help="externo: backup con manifiesto para verificar el restore")
    parser.add_argument("--pg-host", default="127.0.0.1")
    parser.add_argument("--pg-port", type=int, default=5432)
    parser.add_argument("--pg-user", default="portfolio")
    parser.add_argument("--pg-database", default="cavaai_research")
    parser.add_argument("--pg-password", default=os.getenv("PGPASSWORD"))
    parser.add_argument("--minio-endpoint", default=None)
    parser.add_argument("--minio-access-key", default=None)
    parser.add_argument("--minio-secret-key", default=None)
    parser.add_argument("--qdrant-url", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.external:
            require(bool(args.database_url), "--external necesita --database-url")
            report = {"mode": "external", "results": [run_external(args)]}
        else:
            require_tool("docker", what="A/B de carga")
            caps = parse_caps(args.caps)
            results = []
            for cap in caps:
                print(f"\n[load-ab] === tope {cap} ===")
                with tempfile.TemporaryDirectory(prefix=f"cavaai-loadab-{cap}-") as tmp:
                    cap_result = run_cap_cycle(
                        cap,
                        workdir=Path(tmp),
                        companies=args.companies,
                        rounds=args.rounds,
                        seed=args.seed,
                        keep=args.keep,
                    )
                results.append(cap_result)
                estado = "OK" if cap_result.get("load_ok") else f"FALLO: {cap_result.get('failure')}"
                print(f"[load-ab] tope {cap}: {estado}")
            report = {
                "mode": "matrix",
                "companies": args.companies,
                "rounds": args.rounds,
                "seed": args.seed,
                "results": results,
            }
        out = args.out or f"load_ab_{new_backup_id()}.json"
        Path(out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\n[load-ab] informe: {out}")
        return 0
    except FailClosedError as exc:
        print(f"\n[load-ab] FALLO: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - fail-closed tambien ante lo inesperado
        traceback.print_exc()
        print(f"\n[load-ab] FALLO (inesperado): {type(exc).__name__}: {redact(str(exc))}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
