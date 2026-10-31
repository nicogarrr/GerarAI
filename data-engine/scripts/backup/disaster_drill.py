"""Drill de desastre: backup -> DESTRUIR -> restore -> verificar. Aislado y no destructivo.

El drill SIEMPRE trabaja en contenedores, volumenes, puertos y directorio
temporales propios, con nombres `cavaai-drill-*`. No toca los contenedores ni
los volumenes de `docker-compose.yml` ni de `docker-compose.prod.yml`: para que
sea imposible confundirlo con produccion, el drill ABORTA si el directorio de
trabajo no es un temporal y si algun nombre de contenedor ya existe.

El ciclo completo:
  0. Preflight: docker, python, puertos libres.
  1. Levantar Postgres/MinIO/Qdrant vacios, con volumenes propios.
  2. Sembrar datos DETERMINISTAS (N companies, M objetos, P puntos de dim D).
  3. Backup de los tres pilares -> manifiesto.
  4. DESTRUCIR: borrar contenedores y volumenes y volver a crearlos vacios.
     Esto es el desastre: se pierde el servidor, no solo una tabla.
  5. Restore contra el destino limpio (--confirm-restore).
  6. verify_restore: las seis comprobaciones, fail-closed.
  7. Limpieza (siempre, tambien al fallar).

Devuelve 0 solo si las seis comprobaciones pasan. Si alguna no se puede
ejecutar, es fallo.

Uso:
    python -m scripts.backup.disaster_drill
    python -m scripts.backup.disaster_drill --keep   # deja el entorno para inspeccionar
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.backup import seed_drill_data
from scripts.backup._kit import (  # noqa: E402
    DATA_ENGINE_ROOT,
    MINIO_IMAGE,
    POSTGRES_IMAGE,
    QDRANT_IMAGE,
    REQUIRED_QDRANT_MAJOR_MINOR,
    FailClosedError,
    PsqlTarget,
    format_table,
    new_backup_id,
    redact,
    require,
    require_tool,
    run,
    sha256_file,
)
from scripts.backup.seed_drill_data import (  # noqa: E402
    SEED_COMPANIES,
    SEED_DIM,
    SEED_OBJECTS,
    SEED_POINTS,
)

# Nombres de destino propios del drill: no tocan el bucket ni la coleccion que
# usa la aplicacion, ni en una maquina donde Develop al lado.
SEED_BUCKET = "drill-bucket"
SEED_COLLECTION = "drill_collection"

PG_USER = os.getenv("DRILL_PG_USER", "drill")
PG_PASSWORD = os.getenv("DRILL_PG_PASSWORD", "drill-password")
MINIO_USER = os.getenv("DRILL_MINIO_USER", "drilluser")
MINIO_PASSWORD = os.getenv("DRILL_MINIO_PASSWORD", "drillpassword123")
APP_WAIT_SECONDS = 180


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class DrillEnvironment:
    """Contenedores, puertos y volumenes PROPIOS del drill."""

    def __init__(
        self, *, workdir: Path, keep: bool = False, minio_image: str | None = None
    ) -> None:
        self.workdir = workdir
        self.keep = keep
        self.drill_id = f"drill{os.getpid()}{uuid.uuid4().hex[:4]}"
        self.containers: dict[str, str] = {}
        self.volumes: dict[str, str] = {}
        self.pg_port = free_port()
        self.minio_port = free_port()
        self.qdrant_port = free_port()
        self.app_port = free_port()
        # El pin del compose es la fuente de verdad; `--minio-image` solo cambia
        # el REGISTRO (mismo release tag) en hosts donde quay.io no responde.
        self.minio_image = minio_image or MINIO_IMAGE

    # -- ciclo de vida ------------------------------------------------------

    def require_isolated(self) -> None:
        """Aborta si el drill no puede ser inequivocamente aislado."""
        require(
            self.workdir != Path(DATA_ENGINE_ROOT),
            "el drill no puede usar data-engine/ como directorio de trabajo",
        )
        planned = [f"cavaai-{self.drill_id}-{service}" for service in ("postgres", "minio", "qdrant")]
        listed = run(
            ["docker", "ps", "-a", "--format", "{{.Names}}"],
            timeout=120,
            what="docker ps",
        ).stdout.split()
        for name in planned:
            require(
                name not in listed,
                f"ya existe un contenedor llamado '{name}': el drill no lo reutiliza "
                "ni lo borra. Renombra el que estorbe y repite",
            )

    def _run_container(self, service: str, image: str, options: list[str], command: list[str]) -> str:
        """`docker run` con las OPCIONES antes de la imagen y el COMANDO despues."""
        name = f"cavaai-{self.drill_id}-{service}"
        require_tool_docker()
        run(
            ["docker", "run", "-d", "--name", name, *options, image, *command],
            timeout=600,
            what=f"docker run {service}",
        )
        self.containers[service] = name
        return name

    def _volume(self, service: str) -> str:
        name = f"cavaai-{self.drill_id}-{service}-data"
        run(["docker", "volume", "create", name], timeout=120, what="docker volume create")
        self.volumes[service] = name
        return name

    def up(self) -> None:
        require_tool_docker()
        pg_volume = self._volume("postgres")
        minio_volume = self._volume("minio")
        qdrant_volume = self._volume("qdrant")
        self._run_container(
            "postgres",
            POSTGRES_IMAGE,
            [
                "-e",
                f"POSTGRES_USER={PG_USER}",
                "-e",
                f"POSTGRES_PASSWORD={PG_PASSWORD}",
                "-e",
                "POSTGRES_DB=cavaai_drill",
                "-v",
                f"{pg_volume}:/var/lib/postgresql/data",
                "-p",
                f"127.0.0.1:{self.pg_port}:5432",
            ],
            [],
        )
        self._run_container(
            "minio",
            self.minio_image,
            [
                "-v",
                f"{minio_volume}:/data",
                "-p",
                f"127.0.0.1:{self.minio_port}:9000",
                "-e",
                f"MINIO_ROOT_USER={MINIO_USER}",
                "-e",
                f"MINIO_ROOT_PASSWORD={MINIO_PASSWORD}",
            ],
            ["server", "--address", ":9000", "/data"],
        )
        self._run_container(
            "qdrant",
            QDRANT_IMAGE,
            [
                "-v",
                f"{qdrant_volume}:/qdrant/storage",
                "-p",
                f"127.0.0.1:{self.qdrant_port}:6333",
            ],
            [],
        )
        self.wait_ready()

    def wait_ready(self, timeout: int = 300) -> None:
        """Espera a que los TRES respondan de verdad. Sin espera, el seed falla en falso.

        Para Postgres no basta `pg_isready`: da ok durante la fase de servidor
        temporal del initdb y despues el motor reinicia, que es como el drill
        fallaba con "the database system is shutting down" a mitad del restore.
        """
        deadline = time.monotonic() + timeout
        pending = {
            "postgres": lambda: self._pg_query(),
            "minio": lambda: self._http_ok(self.minio_port, "/minio/health/live"),
            "qdrant": lambda: self._http_ok(self.qdrant_port, "/healthz"),
        }
        while pending and time.monotonic() < deadline:
            for service, probe in list(pending.items()):
                if probe():
                    del pending[service]
                    print(f"[drill] {service} listo")
            if pending:
                time.sleep(2)
        if pending:
            raise FailClosedError(
                f"los servicios {sorted(pending)} no respondieron en {timeout}s: "
                "el drill no puede seguir (fallo, no un resultado verde).\n"
                + self._diagnostico_contenedores(sorted(pending))
            )

    def _diagnostico_contenedores(self, servicios: list[str]) -> str:
        """Estado y ultimas lineas de log de los contenedores que no arrancaron.

        Un timeout de espera sin el log del contenedor es un fallo mudo: en CI
        el runner se destruye y no hay forma de saber si la imagen no tiro del
        entrypoint, pidio una variable o nunca llego a escuchar (medido
        2026-10-31: bitnamilegacy/minio no acepta el comando `server ...` de la
        imagen oficial y el drill solo decia "no respondio en 300s").
        """
        partes: list[str] = []
        for servicio in servicios:
            nombre = self.containers.get(servicio)
            if not nombre:
                continue
            estado = run(
                [
                    "docker",
                    "inspect",
                    "--format",
                    "{{.State.Status}} exit={{.State.ExitCode}}",
                    nombre,
                ],
                timeout=30,
                check=False,
                what="docker inspect",
            ).stdout.strip()
            logs = run(
                ["docker", "logs", "--tail", "15", nombre],
                timeout=30,
                check=False,
                what="docker logs",
            )
            lineas = (logs.stdout + logs.stderr).strip().splitlines()
            partes.append(
                f"{servicio} ({nombre}): {estado}; ultimas lineas: "
                + redact(" | ".join(lineas[-8:]))
            )
        return "\n".join(partes)

    def _pg_query(self) -> bool:
        result = run(
            [
                "docker",
                "exec",
                self.containers["postgres"],
                "psql",
                "--username",
                PG_USER,
                "--dbname",
                "postgres",
                "-tAc",
                "SELECT 1",
            ],
            timeout=30,
            check=False,
            what="psql SELECT 1",
        )
        return result.returncode == 0 and result.stdout.strip() == "1"

    @staticmethod
    def _http_ok(port: int, path: str) -> bool:
        import urllib.error
        import urllib.request

        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3) as response:
                return response.status < 500
        except urllib.error.HTTPError as exc:
            return exc.code < 500
        except OSError:
            return False

    def destroy(self) -> None:
        """Fase 4: se borra TODO y se vuelve a levantar vacio. Esto es el desastre."""
        for name in self.containers.values():
            run(["docker", "rm", "-f", name], timeout=300, check=False, what="docker rm")
        for volume in self.volumes.values():
            run(["docker", "volume", "rm", "-f", volume], timeout=300, check=False, what="docker volume rm")
        print("[drill] servicios destruidos (contenedores y volumenes borrados)")
        self.containers.clear()
        self.volumes.clear()
        self.up()

    def cleanup(self) -> None:
        if self.keep:
            print(f"[drill] --keep: no se borra {sorted(self.containers.values())}")
            return
        for name in self.containers.values():
            run(["docker", "rm", "-f", name], timeout=300, check=False, what="docker rm")
        for volume in self.volumes.values():
            run(["docker", "volume", "rm", "-f", volume], timeout=300, check=False, what="docker volume rm")
        self.containers.clear()
        self.volumes.clear()
        print("[drill] limpieza del entorno aislado completada")


def require_tool_docker() -> None:
    require_tool("docker", what="drill de desastre")


# --- Siembra determinista --------------------------------------------------


def _drill_app_env(drill: DrillEnvironment) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "APP_ENV": "test",
            "RESEARCH_AUTH_REQUIRED": "false",
            "WORKERS_ENABLED": "false",
            "DATABASE_URL": (
                f"postgresql+psycopg://{PG_USER}:{PG_PASSWORD}"
                f"@127.0.0.1:{drill.pg_port}/cavaai_drill"
            ),
            "QDRANT_URL": f"http://127.0.0.1:{drill.qdrant_port}",
            "VECTOR_STORE": "qdrant",
            "MINIO_ENDPOINT": f"127.0.0.1:{drill.minio_port}",
            "MINIO_ACCESS_KEY": MINIO_USER,
            "MINIO_SECRET_KEY": MINIO_PASSWORD,
            "MINIO_BUCKET": SEED_BUCKET,
            "DOCUMENT_STORAGE_BACKEND": "minio",
            "REDIS_URL": "redis://127.0.0.1:6379/15",
            "DUCKDB_PATH": str(drill.workdir / "analytics.duckdb"),
            "LANGFUSE_ENABLED": "false",
            "SEC_USER_AGENT": "GerarAI-drill contact@example.com",
        }
    )
    return env


def seed_all(drill: DrillEnvironment) -> None:
    """Siembra los tres pilares con el MISMO modulo que usa CI.

    `seed_drill_data` es la unica definicion de "que datos hay": si el drill y el
    workflow Sembraran distinto, el manifest que uno verifica no seria el que el
    otro restorea.
    """
    seed_drill_data.seed_postgres(_drill_app_env(drill)["DATABASE_URL"], python=sys.executable)
    seed_drill_data.seed_minio(
        f"127.0.0.1:{drill.minio_port}", MINIO_USER, MINIO_PASSWORD, bucket=SEED_BUCKET
    )
    seed_drill_data.seed_qdrant(
        f"http://127.0.0.1:{drill.qdrant_port}",
        SEED_COLLECTION,
        points=SEED_POINTS,
        dim=SEED_DIM,
    )


# --- Aplicacion para la comprobacion (d) -----------------------------------


class AppProcess:
    """`uvicorn main:app` en un subproceso, contra la base restaurada."""

    def __init__(self, drill: DrillEnvironment) -> None:
        self.drill = drill
        self.proc: subprocess.Popen | None = None
        self.log = drill.workdir / "uvicorn.log"

    def start(self) -> str:
        env = _drill_app_env(self.drill)
        handle = self.log.open("w", encoding="utf-8")
        self.proc = subprocess.Popen(  # noqa: S603 - argv explicito, sin shell
            [
                sys.executable,
                "-m",
                "uvicorn",
                "main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.drill.app_port),
                "--log-level",
                "warning",
            ],
            cwd=str(DATA_ENGINE_ROOT),
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
        )
        base_url = f"http://127.0.0.1:{self.drill.app_port}"
        deadline = time.monotonic() + APP_WAIT_SECONDS
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                tail = "\n".join(self.log.read_text(encoding="utf-8", errors="replace").splitlines()[-8:])
                raise FailClosedError(
                    f"la app de drill arranco y morreu (codigo {self.proc.returncode}): "
                    + redact(tail)
                )
            if self.drill._http_ok(self.drill.app_port, "/health/live"):
                print(f"[drill] aplicacion escuchando en {base_url}")
                return base_url
            time.sleep(2)
        raise FailClosedError(
            f"la app de drill no respondio en {APP_WAIT_SECONDS}s: "
            + redact(self.log.read_text(encoding="utf-8", errors="replace")[-400:])
        )

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=30)
            except subprocess.TimeoutExpired:  # pragma: no cover - defensivo
                self.proc.kill()


# --- Ciclo completo ---------------------------------------------------------


def run_drill(*, workdir: Path, keep: bool = False, minio_image: str | None = None) -> int:
    from scripts.backup import backup_all
    from scripts.restore import restore_minio, restore_postgres, restore_qdrant, verify_restore

    drill = DrillEnvironment(workdir=workdir, keep=keep, minio_image=minio_image)
    app = AppProcess(drill)
    backup_dir = workdir / "backup"
    try:
        drill.require_isolated()
        print("[drill] 1/7 levantando Postgres/MinIO/Qdrant vacios en puertos propios…")
        drill.up()

        print("[drill] 2/7 sembrando datos deterministas…")
        seed_all(drill)

        print("[drill] 3/7 backup de los tres pilares…")
        backup_id = new_backup_id()
        # Modo docker con el contenedor PROPIO del drill: igual que produccion
        # (los scripts en bash usan `docker compose exec postgres`) y sin
        # depender de que el host tenga un cliente Postgres instalado, que
        # ademas tendria que ser >= 17 para no fallar a mitad del dump.
        pg_container = drill.containers["postgres"]
        # Se usan las MISMAS funciones que la CLI, no `main(argv)`: el codigo de
        # salida no es la prueba y aqui no hay que parsearlo. Un `FailClosedError`
        # en cualquier fase detiene el drill con su motivo.
        backup_args = backup_all.build_parser().parse_args(
            [
                "--out",
                str(backup_dir),
                "--backup-id",
                backup_id,
                "--pg-mode",
                "docker",
                "--pg-container",
                pg_container,
                "--pg-user",
                PG_USER,
                "--pg-database",
                "cavaai_drill",
                "--minio-endpoint",
                f"127.0.0.1:{drill.minio_port}",
                "--minio-access-key",
                MINIO_USER,
                "--minio-secret-key",
                MINIO_PASSWORD,
                "--minio-bucket",
                SEED_BUCKET,
                "--qdrant-url",
                f"http://127.0.0.1:{drill.qdrant_port}",
            ]
        )
        builder, backup_dir = backup_all.run_all(backup_args)
        manifest_path = builder.write()
        print(f"[backup] completo: {manifest_path}")

        print("[drill] 4/7 DESTRUYENDO el entorno (contenedores + volumenes)…")
        drill.destroy()
        pg_container = drill.containers["postgres"]

        print("[drill] 5/7 restore en destino limpio…")
        for pillar, report in (
            (
                "postgres",
                restore_postgres.run_restore(
                    backup_dir, mode="docker", container=pg_container, user=PG_USER
                ),
            ),
            (
                "minio",
                restore_minio.run_restore(
                    backup_dir,
                    endpoint=f"127.0.0.1:{drill.minio_port}",
                    access_key=MINIO_USER,
                    secret_key=MINIO_PASSWORD,
                ),
            ),
            (
                "qdrant",
                restore_qdrant.run_restore(backup_dir, url=f"http://127.0.0.1:{drill.qdrant_port}"),
            ),
        ):
            print(f"[drill] restore:{pillar} -> {json.dumps(report, sort_keys=True)}")

        print("[drill] 6/7 verificacion de DATOS (antes de arrancar la app)…")
        # Antes de arrancar la app a proposito: su lifespan llama a
        # `ensure_company_master()` cuando APP_ENV != production e inserta filas
        # (companies 12 -> 35). Comparar los conteos con la app ya en marcha
        # daria un falso positivo de "restore incompleto".
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
        print(format_table(data_results, heading="Verificacion de datos (fail-closed)"))
        data_report_path = workdir / "verify_report_data.json"
        data_report_path.write_text(
            json.dumps(data_report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"{data_report['checks_passed']}/{data_report['checks_total']} comprobaciones superadas")
        require(
            data_ok,
            "los datos restaurados no coinciden con el manifiesto: el informe de la "
            f"fase de datos ({data_report_path}) tiene el motivo exacto de cada comprobacion",
        )

        print("[drill] 7/7 arrancando la app y verificando que SIRVE…")
        app_base_url = app.start()
        verify_config = replace(verify_config, app_base_url=app_base_url)
        app_ok, app_results, app_report = verify_restore.verify(
            verify_config, phase=verify_restore.PHASE_APP
        )
        print(format_table(app_results, heading="Verificacion de la aplicacion (fail-closed)"))
        app_report_path = workdir / "verify_report_app.json"
        app_report_path.write_text(
            json.dumps(app_report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        require(
            app_ok,
            f"la app no arranca o no sirve contra la base restaurada; informe: {app_report_path}",
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        _assert_seed_counts(manifest, backup_dir)
        print("\n[drill] DRILL COMPLETO: backup -> destruccion -> restore -> 6/6 verificaciones OK")
        print(f"[drill] backup_id={manifest['backup_id']} dir={backup_dir}")
        return 0
    except FailClosedError as exc:
        print(f"\n[drill] FALLO: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - un error inesperado tambien es un fallo
        # Fail-closed igual: el drill no termina en verde porque una fase haya
        # lanzado algo que nadie anticipated. Se imprime el traceback para que
        # el motivo sea diagnosticable, no solo la clase de la excepcion.
        traceback.print_exc()
        print(f"\n[drill] FALLO (inesperado): {type(exc).__name__}: {redact(str(exc))}", file=sys.stderr)
        return 1
    finally:
        app.stop()
        drill.cleanup()


def _assert_seed_counts(manifest: dict[str, Any], backup_dir: Path) -> None:
    """Segunda red: los conteos del backup tienen que ser los que se sembraron.

    Con esto, un backup que declare 0 companies y 0 objetos no puede pasar el
    drill por mucho que el verify las diera por buenas, y se comprueba que los
    checksums del manifiesto casan con lo que hay en disco.
    """
    require(
        int(manifest["postgres"]["tables"].get("companies", -1)) == SEED_COMPANIES,
        f"el backup declara {manifest['postgres']['tables'].get('companies')} companies; "
        f"la siembra dejo {SEED_COMPANIES}",
    )
    require(
        int(manifest["minio"]["object_count"]) == SEED_OBJECTS,
        f"el backup declara {manifest['minio']['object_count']} objetos; "
        f"la siembra dejo {SEED_OBJECTS}",
    )
    require(
        int(manifest["qdrant"]["total_points"]) == SEED_POINTS,
        f"el backup declara {manifest['qdrant']['total_points']} puntos; "
        f"la siembra dejo {SEED_POINTS}",
    )
    require(
        str(manifest["tools"]["qdrant"]["version"]).startswith(REQUIRED_QDRANT_MAJOR_MINOR),
        f"el drill se ejecuto contra Qdrant {manifest['tools']['qdrant']['version']}, "
        f"y el pin del repo es {QDRANT_IMAGE}",
    )
    for artifact in manifest["artifacts"]:
        actual = sha256_file(backup_dir / artifact["path"])
        require(
            actual == artifact["sha256"],
            f"el sha256 del manifiesto no casa con {artifact['path']}: "
            f"{actual} != {artifact['sha256']}",
        )
    print(
        f"[drill] manifiesto coherente con la siembra: {SEED_COMPANIES} companies, "
        f"{SEED_OBJECTS} objetos, {SEED_POINTS} puntos, {len(manifest['artifacts'])} artefactos"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Drill backup -> destruir -> restore -> verificar.")
    parser.add_argument(
        "--workdir",
        default=None,
        help="Directorio de trabajo (por defecto, un temporal que se borra al terminar).",
    )
    parser.add_argument("--keep", action="store_true", help="No borrar contenedores ni el temporal.")
    parser.add_argument(
        "--minio-image",
        default=None,
        help=(
            "Referencia de la imagen de MinIO. Por defecto, el pin del compose "
            f"({MINIO_IMAGE}); override solo para cambiar el REGISTRO en hosts "
            "donde quay.io no responde (mismo release tag)."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    temporary: tempfile.TemporaryDirectory | None = None
    if args.workdir:
        workdir = Path(args.workdir).resolve()
        workdir.mkdir(parents=True, exist_ok=True)
    else:
        temporary = tempfile.TemporaryDirectory(prefix="cavaai-drill-")
        workdir = Path(temporary.name).resolve()
    try:
        code = run_drill(workdir=workdir, keep=args.keep, minio_image=args.minio_image)
    except FailClosedError as exc:
        print(f"[drill] FALLO: {exc}", file=sys.stderr)
        return 1
    finally:
        if temporary is not None and not args.keep:
            temporary.cleanup()
        elif temporary is not None:
            print(f"[drill] --keep: el temporal queda en {workdir}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
