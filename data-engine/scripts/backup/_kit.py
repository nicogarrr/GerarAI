"""Primitivas fail-closed compartidas por el backup y el restore de GerarAI.

Este modulo es la unica fuente de verdad del formato del manifiesto, de los
pins de herramientas y del contrato "fail-closed": una comprobacion que no se
puede ejecutar es un FALLO con motivo, nunca un "omitido" que deja el pipeline
en verde. Es el mismo principio que el gate de RAG de `.github/workflows/ci.yml`
("RAG activation tests skipped -> exit 1").

Los scripts de este arbol se ejecutan de dos formas equivalentes:

    python -m scripts.backup.backup_all          (desde data-engine/)
    python scripts/backup/backup_all.py

Por eso el bootstrap de `sys.path` va antes de los imports de `scripts.*`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# --- Paths ------------------------------------------------------------------

# data-engine/
DATA_ENGINE_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = DATA_ENGINE_ROOT.parent
ALEMBIC_VERSIONS_DIR = DATA_ENGINE_ROOT / "alembic" / "versions"
COMPOSE_FILES = ("docker-compose.yml", "docker-compose.prod.yml")

# --- Contrato del manifiesto ------------------------------------------------

MANIFEST_VERSION = 1
MANIFEST_FILENAME = "manifest.json"
BACKUP_KINDS = ("full", "incremental")
PILLARS = ("postgres", "minio", "qdrant")

#: Campos de primer nivel que un restore necesita para no ser arqueologia.
REQUIRED_MANIFEST_FIELDS = (
    "manifest_version",
    "backup_id",
    "created_at_utc",
    "backup_kind",
    "alembic_head",
    "alembic_head_source",
    "tools",
    "artifacts",
    "postgres",
    "minio",
    "qdrant",
)

#: Sub-bloques de `tools` que el manifiesto siempre declara, con su version.
REQUIRED_TOOL_KEYS = ("pg_dump", "pg_restore", "minio", "qdrant")

# --- Pins de herramientas ---------------------------------------------------
#
# Derivados de las imagenes de docker-compose.yml / docker-compose.prod.yml y
# fijados aqui para que un `pg_dump` de una version cliente incompatible no se
# descubra en el momento del restore (que es cuando ya no hay margen).

POSTGRES_IMAGE = "postgres:17"
REQUIRED_PG_CLIENT_MAJOR = 17
QDRANT_IMAGE = "qdrant/qdrant:v1.19.2"
REQUIRED_QDRANT_MAJOR_MINOR = "1.19"
# La imagen oficial de quay.io ya no es publica: prod construye MinIO desde
# fuente (docker/minio/Dockerfile, PR #776) y etiqueta la imagen asi.
MINIO_IMAGE = "cavaai-minio:RELEASE.2025-10-15T17-29-55Z"
MINIO_SERVER_RELEASE = "RELEASE.2025-10-15T17-29-55Z"
#: Rango declarado en data-engine/pyproject.toml para el SDK de MinIO.
MINIO_SDK_REQUIREMENT = "minio>=7.2.7,<8"

#: Formatos de artefacto. Un dump plano de Postgres no es restaurable de forma
#: fiable: el custom format (-Fc) es comprimido y, sobre todo, SELECCIONABLE,
#: que es lo que hace `pg_restore` rapido y parcial.
PG_DUMP_FORMAT = "pg_dump_custom"
PG_DUMP_FORMAT_FLAG = "-Fc"

#: Endpoints que el verify_restore usa como prueba de que la app arranca y
#: SIRVE datos contra la base restaurada. `/health/ready` es el unico
#: hard-required (la BD); `/api/health` es publico y expone `schema`, que es
#: como se detecta un dump anterior al head de Alembic.
APP_READY_PATH = "/health/ready"
APP_PUBLIC_HEALTH_PATH = "/api/health"
APP_DATA_PATH = "/api/companies"
APP_DATA_LIMIT = 500
APP_DATA_PROBE_FIELD = "ticker"


class FailClosedError(RuntimeError):
    """Una verificacion no se pudo ejecutar, o se ejecuto y no cuadro.

    Nunca se usa para "no applicable": si algo no se puede comprobar, el
    resultado es fallo con motivo (ver verify_restore.py).
    """


def require(condition: object, reason: str) -> None:
    """`assert` con mensaje, pero que no desaparece con `python -O`."""
    if not condition:
        raise FailClosedError(reason)


# --- Redaccion de secretos -------------------------------------------------

_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\b(password|passwd|pwd|secret[_-]?key|access[_-]?key)\s*[=:]\s*\S+"), r"\1=***"),
    (re.compile(r"(?i)\b(postgresql(?:\+\w+)?://[^:/@\s]+):[^@/\s]+@"), r"\1:***@"),
    (re.compile(r"(?i)(--password[= ])\S+"), r"\1***"),
)


def redact(text: str) -> str:
    """Quita credenciales de un texto destined a un log o a un motivo de fallo."""
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


# --- Ejecucion de comandos --------------------------------------------------


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


def run(
    argv: Sequence[str],
    *,
    stdin: str | None = None,
    timeout: int = 900,
    check: bool = True,
    what: str = "",
    env: Mapping[str, str] | None = None,
    cwd: str | Path | None = None,
) -> CommandResult:
    """Ejecuta un comando y falla con el motivo si no sale con 0.

    El motivo incluye argv, codigo de salida y las ultimas lineas de stderr
    (redactadas): "fallo con motivo" y no "el comando fallo".
    """
    label = what or argv[0]
    require(bool(argv), f"{label}: comando vacio")
    process_env = dict(os.environ)
    if env:
        process_env.update(env)
    try:
        proc = subprocess.run(  # noqa: S603 - argv explicito, sin shell
            list(argv),
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=process_env,
            cwd=str(cwd) if cwd else None,
        )
    except FileNotFoundError as exc:
        raise FailClosedError(f"{label}: herramienta ausente ({argv[0]}): {exc}") from exc
    except PermissionError as exc:
        # EACCES al hacer exec: el binario no es ejecutable, un directorio del
        # PATH es inaccesible o el entorno restringe exec (sandboxes). Es el
        # mismo fallo operativo que "ausente": fail-closed con motivo, no un
        # traceback sin redactar.
        raise FailClosedError(
            f"{label}: herramienta ausente o no ejecutable ({argv[0]}): {exc}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise FailClosedError(f"{label}: timeout de {timeout}s en {argv[0]}") from exc
    result = CommandResult(tuple(argv), proc.returncode, proc.stdout, proc.stderr)
    if check and proc.returncode != 0:
        raise FailClosedError(_failure_reason(label, result))
    return result


def _failure_reason(label: str, result: CommandResult) -> str:
    tail = redact(result.stderr.strip() or result.stdout.strip())
    tail = "\n".join(tail.splitlines()[-6:])
    return (
        f"{label}: {' '.join(result.argv[:3])} salio con codigo {result.returncode}"
        f"{': ' + tail if tail else ''}"
    )


def require_tool(name: str, *, what: str = "") -> str:
    """Devuelve la ruta de una herramienta o falla (nunca 'no encontrada' -> skip)."""
    found = shutil.which(name)
    if not found:
        raise FailClosedError(
            f"{what or name}: herramienta '{name}' no esta en PATH; "
            "instala el cliente o fija el modo docker para no depender del host"
        )
    return found


def tool_version(argv: Sequence[str]) -> str:
    """Primera linea de `<tool> --version`, sin el prefijo del nombre."""
    try:
        result = run([*argv, "--version"], timeout=60, what="version de herramienta")
    except FailClosedError as exc:
        return f"unknown ({redact(str(exc))})"
    line = (result.stdout or result.stderr).strip().splitlines()
    return redact(line[0]) if line else "unknown"


# --- Checksums y artefactos -------------------------------------------------


def sha256_file(path: Path, *, chunk: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def tar_directory(source: Path, target: Path, *, prefix: str = "") -> None:
    """`tar.gz` DETERMINISTA de un directorio (nombres ordenados, mtime a 0).

    Determinista para que dos backups del mismo contenido produzcan el mismo
    sha256 y el checksum del manifiesto signifique algo. El orden de recorrido
    de `os.listdir` no lo es, y sin `sorted()` el mismo contenido da checksums
    distintos en cada ejecucion.
    """
    import tarfile

    target.parent.mkdir(parents=True, exist_ok=True)
    members = sorted(path for path in source.rglob("*") if path.is_file())
    with tarfile.open(target, "w:gz", compresslevel=6) as archive:
        for path in members:
            info = archive.gettarinfo(str(path), arcname=f"{prefix}{path.relative_to(source).as_posix()}")
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            with path.open("rb") as handle:
                archive.addfile(info, handle)


def untar_to(source_tar: Path, destination: Path, *, what: str = "restaurar un tar") -> int:
    """Extrae un tar en un directorio y devuelve el numero de ficheros.

    `filter="data"` es la default de Python 3.12 pero no de 3.11 (el objetivo de
    despliegue): sin el, una entrada con ruta absoluta o `..` escribe fuera del
    directorio de destino.
    """
    import tarfile

    require(source_tar.is_file(), f"{what}: no existe {source_tar}")
    require(destination.is_dir(), f"{what}: no existe el directorio de destino {destination}")
    extracted = 0
    with tarfile.open(source_tar, "r:gz") as archive:
        for member in archive.getmembers():
            require(not member.name.startswith("/"), f"{what}: ruta absoluta en {member.name}")
            require(
                ".." not in Path(member.name).parts,
                f"{what}: traversal de ruta en {member.name}",
            )
            archive.extract(member, path=destination, filter="data")
            if member.isfile():
                extracted += 1
    return extracted


@dataclass(frozen=True)
class Artifact:
    pillar: str
    path: str
    format: str
    sha256: str
    bytes: int
    kind: str = "full"
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "pillar": self.pillar,
            "path": self.path,
            "format": self.format,
            "sha256": self.sha256,
            "bytes": self.bytes,
            "kind": self.kind,
        }
        if self.detail:
            payload["detail"] = self.detail
        return payload


def artifact_for_file(
    backup_dir: Path,
    pillar: str,
    relative: str,
    fmt: str,
    *,
    kind: str = "full",
    detail: str = "",
) -> Artifact:
    """Construye el descriptor de un artefacto ya escrito en disco."""
    absolute = backup_dir / relative
    require(absolute.is_file(), f"artefacto ausente: {absolute}")
    return Artifact(
        pillar=pillar,
        path=relative.replace("\\", "/"),
        format=fmt,
        sha256=sha256_file(absolute),
        bytes=absolute.stat().st_size,
        kind=kind,
        detail=detail,
    )


def verify_artifact(backup_dir: Path, artifact: Mapping[str, Any]) -> None:
    """Comprueba que el artefacto existe y casa con su sha256 del manifiesto."""
    relative = str(artifact.get("path", ""))
    require(bool(relative), "artefacto sin 'path' en el manifiesto")
    absolute = backup_dir / relative
    require(absolute.is_file(), f"artefacto ausente en disco: {relative}")
    declared = str(artifact.get("sha256", ""))
    require(
        bool(re.fullmatch(r"[0-9a-f]{64}", declared)),
        f"artefacto {relative}: sha256 del manifiesto no es un hex de 64",
    )
    actual = sha256_file(absolute)
    require(
        actual == declared,
        f"artefacto {relative}: sha256 {actual} != manifiesto {declared} (backup corrupto)",
    )
    declared_bytes = artifact.get("bytes")
    if isinstance(declared_bytes, int):
        actual_bytes = absolute.stat().st_size
        require(
            actual_bytes == declared_bytes,
            f"artefacto {relative}: {actual_bytes} bytes != manifiesto {declared_bytes}",
        )


# --- Alembic ----------------------------------------------------------------

_REVISION_RE = re.compile(r"^revision(?::\s*str)?\s*=\s*[\"']([^\"']+)[\"']", re.MULTILINE)
_DOWN_REVISION_RE = re.compile(
    r"^down_revision(?::[^=]+)?\s*=\s*(None|[\"']([^\"']+)[\"']|\(([^)]*)\))",
    re.MULTILINE,
)


def parse_alembic_script(path: Path) -> tuple[str, tuple[str, ...]]:
    """`(revision, down_revisions)` de un fichero de migracion.

    Se parsea el fuente en vez de importar Alembic: el head se necesita para
    escribir el manifiesto y para un test, sin base de datos ni `alembic` en el
    PATH.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    revision_match = _REVISION_RE.search(text)
    require(
        revision_match is not None,
        f"{path.name}: no se encuentra la asignacion 'revision' (migracion ilegible)",
    )
    parents: list[str] = []
    down_match = _DOWN_REVISION_RE.search(text)
    if down_match is not None:
        raw = down_match.group(1) or ""
        if "None" not in raw:
            parents = re.findall(r"[\"']([^\"']+)[\"']", raw)
    return revision_match.group(1), tuple(parents)


def alembic_revisions(versions_dir: Path | None = None) -> dict[str, tuple[str, ...]]:
    directory = versions_dir or ALEMBIC_VERSIONS_DIR
    require(directory.is_dir(), f"no existe el directorio de migraciones: {directory}")
    graph: dict[str, tuple[str, ...]] = {}
    for script in sorted(directory.glob("*.py")):
        if script.name.startswith("__"):
            continue
        revision, parents = parse_alembic_script(script)
        graph[revision] = parents
    require(bool(graph), f"sin migraciones en {directory}: no se puede declarar el head")
    return graph


def alembic_head(versions_dir: Path | None = None) -> str:
    """Revision HEAD del codigo.

    Un head multiple (ramas sin fusionar) es un fallo: un backup etiquetado con
    un head ambiguo se restauraria a un esquema que el codigo no reconoce.
    """
    graph = alembic_revisions(versions_dir)
    referenced = {parent for parents in graph.values() for parent in parents}
    heads = sorted(set(graph) - referenced)
    require(
        len(heads) == 1,
        f"el arbol de Alembic tiene {len(heads)} heads ({', '.join(heads)}): "
        "no se puede etiquetar el backup con un esquema unico",
    )
    return heads[0]


# --- Herramientas: Postgres -------------------------------------------------

_PG_VERSION_RE = re.compile(r"(?P<major>\d+)(?:\.(?P<minor>\d+))?")


def parse_pg_tool_version(text: str) -> int:
    """`pg_dump (PostgreSQL) 17.4` -> 17."""
    match = _PG_VERSION_RE.search(text)
    require(match is not None, f"no se pudo leer la version del cliente Postgres: {text!r}")
    return int(match.group("major"))


def check_pg_client_version(major: int) -> None:
    """Falla si el cliente es ANTERIOR al servidor.

    Un `pg_dump` 16 contra un servidor 17 no escribe un dump: aborta. Se
    comprueba antes de arrancar para que el motivo sea el pin y no un error a
    mitad del backup.
    """
    require(
        major >= REQUIRED_PG_CLIENT_MAJOR,
        f"cliente Postgres {major}.x < servidor {REQUIRED_PG_CLIENT_MAJOR}.x "
        f"({POSTGRES_IMAGE}): un dump de un servidor mas nuevo necesita pg_dump "
        f">= {REQUIRED_PG_CLIENT_MAJOR}",
    )


def discover_postgres_container(image: str = POSTGRES_IMAGE) -> str:
    """Localiza el contenedor de Postgres por imagen (services de CI incluidos)."""
    require_tool("docker", what="descubrir el contenedor de Postgres")
    result = run(
        ["docker", "ps", "--filter", f"ancestor={image}", "--format", "{{.ID}}"],
        timeout=120,
        what="docker ps (Postgres)",
    )
    ids = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    require(
        bool(ids),
        f"no hay ningun contenedor en marcha de la imagen {image}: "
        "levanta Postgres o fija POSTGRES_CONTAINER",
    )
    require(
        len(ids) == 1,
        f"hay {len(ids)} contenedores de {image} en marcha ({', '.join(ids[:4])}): "
        "pasa POSTGRES_CONTAINER explicito para no respaldar el equivocado",
    )
    return ids[0]


# --- Postgres por linea de comandos ----------------------------------------


@dataclass(frozen=True)
class PsqlTarget:
    """Como ejecutar herramientas de Postgres: dentro del contenedor o en el host."""

    mode: str  # "docker" | "local"
    database: str
    user: str
    container: str | None = None
    host: str | None = None
    port: int | None = None
    password: str | None = None

    def argv(self, *tool: str, stdin: bool = False) -> list[str]:
        """`docker exec` en modo contenedor, o el cliente local con PGPASSWORD.

        `--username`/`--dbname` los aceptan por igual psql, pg_dump, pg_restore,
        pg_dumpall, createdb y dropdb, asi que el mismo argv vale para los dos
        modos y no hay que mantener dos rutas de codigo. `-i` solo se anade
        cuando de verdad se va a escribir por stdin: `docker exec -i` sin
        entrada hereda el stdin del proceso y puede dejar el comando colgado.
        """
        connection = [f"--username={self.user}"]
        if self.database:
            connection.append(f"--dbname={self.database}")
        if self.mode == "docker":
            require(bool(self.container), "modo docker sin POSTGRES_CONTAINER")
            # El socket unix del contenedor es de confianza: sin PGPASSWORD.
            prefix = ["docker", "exec", "-i"] if stdin else ["docker", "exec"]
            return [*prefix, str(self.container), *tool, *connection]
        require(bool(self.host), "modo local sin POSTGRES_HOST")
        port = f" -p {self.port}" if self.port else ""
        # La contrasena viaja por PGPASSWORD en el entorno, nunca en argv.
        return [
            *tool,
            f"--host={self.host}{port}",
            *connection,
        ]

    def cluster_wide(self) -> PsqlTarget:
        """El mismo destino SIN `--dbname`.

        Para `pg_dumpall --globals-only`, que es de cluster: su `--dbname`
        espera una cadena de conexion, no el nombre de una base, y pasa
        `--dbname=cavaai_research` aborta con 'missing "=" after ...'.
        """
        return replace(self, database="")

    def env(self) -> dict[str, str]:
        env = {"PGCONNECT_TIMEOUT": "15"}
        if self.mode == "local" and self.password:
            env["PGPASSWORD"] = self.password
        return env

    def run_tool(
        self,
        *tool: str,
        stdin: str | None = None,
        timeout: int = 900,
        what: str = "",
        check: bool = True,
    ) -> CommandResult:
        return run(
            self.argv(*tool, stdin=stdin is not None),
            stdin=stdin,
            timeout=timeout,
            check=check,
            what=what or " ".join(tool),
            env=self.env(),
        )

    def psql_value(self, sql: str, *, timeout: int = 120) -> str:
        result = self.run_tool(
            "psql",
            "-tAc",
            sql,
            timeout=timeout,
            what="psql",
        )
        return result.stdout.strip()

    def client_version(self) -> str:
        """Texto completo de `pg_dump --version` (p.ej. "pg_dump (PostgreSQL) 17.11")."""
        result = self.run_tool("pg_dump", "--version", timeout=120, what="pg_dump --version")
        return f"{result.stdout} {result.stderr}".strip()

    def client_major(self) -> int:
        return parse_pg_tool_version(self.client_version())


def wait_until_ready(
    target: PsqlTarget,
    *,
    timeout: int = 180,
    interval: int = 2,
    what: str = "",
) -> None:
    """Espera a que la base ACEPTE UNA CONSULTA real, no solo a que `pg_isready` responda.

    `pg_isready` da ok durante la fase de servidor temporal del initdb, y justo
    despues Postgres reinicia: un restore que empieza en esa ventana falla con
    "the database system is shutting down" sin motivo aparente. Tras un
    desastre (contenedor recien creado, WAL recovery larga) esa ventana es la
    norma, no la excepcion.
    """
    import time

    label = what or f"{target.database}@{target.mode}"
    deadline = time.monotonic() + timeout
    last = "sin respuesta"
    while time.monotonic() < deadline:
        result = target.run_tool(
            "psql", "-tAc", "SELECT 1", timeout=30, check=False, what=f"{label}: SELECT 1"
        )
        if result.returncode == 0 and result.stdout.strip() == "1":
            return
        lines = (result.stderr or result.stdout).strip().splitlines()
        last = redact(lines[-1]) if lines else f"codigo {result.returncode}"
        time.sleep(interval)
    raise FailClosedError(
        f"{label}: la base no acepta consultas en {timeout}s ({last}); "
        "sin base operativa no hay restore posible"
    )


# --- MinIO / Qdrant: settings ---------------------------------------------


def minio_endpoint_config(endpoint: str) -> tuple[str, bool]:
    """`(host:port, secure)` a partir de `MINIO_ENDPOINT`.

    Mismo criterio que app/services/document_store.py: el prefijo decide el
    esquema y el resto es host:port.
    """
    secure = endpoint.startswith("https://")
    host = endpoint.replace("https://", "").replace("http://", "").strip("/")
    require(bool(host), f"MINIO_ENDPOINT vacio: {endpoint!r}")
    return host, secure


def qdrant_base_url(url: str) -> str:
    return url.rstrip("/")


# --- Manifiesto -------------------------------------------------------------


def new_backup_id(moment: datetime | None = None) -> str:
    """`20261002T101500Z`: ordenable lexicograficamente y sin separadores."""
    stamp = (moment or datetime.now(UTC)).astimezone(UTC)
    return stamp.strftime("%Y%m%dT%H%M%SZ")


def git_commit(repo_root: Path | None = None) -> str:
    try:
        result = run(
            ["git", "-C", str(repo_root or REPO_ROOT), "rev-parse", "--short", "HEAD"],
            timeout=60,
            check=False,
            what="git rev-parse",
        )
        return result.stdout.strip() or "unknown"
    except FailClosedError:
        return "unknown"


def compose_image(service: str, compose_file: str = COMPOSE_FILES[0]) -> str:
    """Extrae `image:` de un servicio del compose (para validar los pins)."""
    text = (REPO_ROOT / compose_file).read_text(encoding="utf-8")
    lines = text.splitlines()
    in_service = False
    for line in lines:
        stripped = line.strip()
        if line.startswith("  ") and not line.startswith("    ") and stripped.endswith(":"):
            in_service = stripped[:-1] == service
            continue
        if in_service and stripped.startswith("image:"):
            return stripped.split(":", 1)[1].strip()
    raise FailClosedError(f"{compose_file}: no se encuentra la imagen del servicio '{service}'")


@dataclass
class ManifestBuilder:
    """Acumula el manifiesto de un backup y lo escribe validado."""

    backup_dir: Path
    backup_kind: str = "full"
    backup_id: str = field(default_factory=new_backup_id)
    tools: dict[str, dict[str, Any]] = field(default_factory=dict)
    artifacts: list[Artifact] = field(default_factory=list)
    postgres: dict[str, Any] = field(default_factory=dict)
    minio: dict[str, Any] = field(default_factory=dict)
    qdrant: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    versions_dir: Path | None = None

    def add_tool(self, name: str, version: str, **extra: Any) -> None:
        require(bool(name), "nombre de herramienta vacio")
        require(bool(version), f"herramienta '{name}' sin version en el manifiesto")
        require(
            "version" not in extra,
            f"tools.{name}: 'version' es un argumento propio, no un extra",
        )
        self.tools[name] = {"version": version, **extra}

    def add_artifact(self, artifact: Artifact) -> None:
        require(artifact.pillar in PILLARS, f"pilar desconocido: {artifact.pillar}")
        require(
            artifact.kind in BACKUP_KINDS,
            f"artefacto {artifact.path}: kind '{artifact.kind}' no es full ni incremental",
        )
        self.artifacts.append(artifact)

    def declare_postgres(self, **payload: Any) -> None:
        self.postgres.update(payload)

    def declare_minio(self, **payload: Any) -> None:
        self.minio.update(payload)

    def declare_qdrant(self, **payload: Any) -> None:
        self.qdrant.update(payload)

    def build(self) -> dict[str, Any]:
        require(
            self.backup_kind in BACKUP_KINDS,
            f"backup_kind '{self.backup_kind}' no es full ni incremental",
        )
        moment = datetime.strptime(self.backup_id, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        head = alembic_head(self.versions_dir)
        data: dict[str, Any] = {
            "manifest_version": MANIFEST_VERSION,
            "backup_id": self.backup_id,
            "created_at_utc": moment.isoformat().replace("+00:00", "Z"),
            "backup_kind": self.backup_kind,
            "alembic_head": head,
            "alembic_head_source": str(self.versions_dir or ALEMBIC_VERSIONS_DIR),
            "git_commit": git_commit(),
            "tools": self.tools,
            "artifacts": [artifact.as_dict() for artifact in self.artifacts],
            "postgres": self.postgres,
            "minio": self.minio,
            "qdrant": self.qdrant,
        }
        if self.notes:
            data["notes"] = list(self.notes)
        validate_manifest(data)
        return data

    def write(self) -> Path:
        data = self.build()
        target = self.backup_dir / MANIFEST_FILENAME
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return target


def load_manifest(backup_dir: Path) -> dict[str, Any]:
    """Lee y valida el manifiesto de un directorio de backup."""
    path = backup_dir if backup_dir.is_file() else backup_dir / MANIFEST_FILENAME
    require(path.is_file(), f"no existe el manifiesto: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FailClosedError(f"manifiesto ilegible {path}: {exc}") from exc
    validate_manifest(data)
    return data


def validate_manifest(data: Mapping[str, Any]) -> None:
    """Valida la forma del manifiesto. Cualquier hueco es un fallo, no un default."""
    for field_name in REQUIRED_MANIFEST_FIELDS:
        require(field_name in data, f"manifiesto incompleto: falta '{field_name}'")
    require(
        data["manifest_version"] == MANIFEST_VERSION,
        f"manifest_version {data['manifest_version']} != {MANIFEST_VERSION} "
        "(regenera el backup: el formato cambio)",
    )
    require(
        bool(re.fullmatch(r"\d{8}T\d{6}Z", str(data["backup_id"]))),
        f"backup_id con formato invalido: {data['backup_id']!r} (se espera YYYYMMDDTHHMMSSZ)",
    )
    try:
        datetime.strptime(str(data["created_at_utc"]), "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise FailClosedError(
            f"created_at_utc no es UTC ISO-8601: {data['created_at_utc']!r}"
        ) from exc
    require(
        data["backup_kind"] in BACKUP_KINDS,
        f"backup_kind '{data['backup_kind']}' no es full ni incremental",
    )
    require(bool(str(data["alembic_head"]).strip()), "alembic_head vacio en el manifiesto")

    tools = data["tools"]
    require(isinstance(tools, Mapping), "'tools' no es un objeto")
    for key in REQUIRED_TOOL_KEYS:
        require(key in tools, f"manifiesto sin la herramienta '{key}'")
        entry = tools[key]
        require(isinstance(entry, Mapping), f"tools.{key} no es un objeto")
        require(bool(str(entry.get("version", "")).strip()), f"tools.{key}.version vacio")

    artifacts = data["artifacts"]
    require(isinstance(artifacts, Sequence) and not isinstance(artifacts, (str, bytes)), "artefactos")
    require(bool(artifacts), "el manifiesto no declara ningun artefacto")
    seen_pillars: set[str] = set()
    for artifact in artifacts:
        require(isinstance(artifact, Mapping), "cada artefacto debe ser un objeto")
        pillar = str(artifact.get("pillar", ""))
        require(pillar in PILLARS, f"artefacto con pilar desconocido: {pillar!r}")
        seen_pillars.add(pillar)
        for key in ("path", "format", "sha256", "kind"):
            require(
                bool(str(artifact.get(key, "")).strip()),
                f"artefacto {artifact.get('path')}: campo '{key}' vacio",
            )
        require(
            bool(re.fullmatch(r"[0-9a-f]{64}", str(artifact["sha256"]))),
            f"artefacto {artifact['path']}: sha256 no es un hex de 64 caracteres",
        )
        require(
            artifact["kind"] in BACKUP_KINDS,
            f"artefacto {artifact['path']}: kind invalido {artifact['kind']!r}",
        )
        require(
            isinstance(artifact.get("bytes"), int) and artifact["bytes"] >= 0,
            f"artefacto {artifact['path']}: 'bytes' debe ser un entero >= 0",
        )
    missing = [pillar for pillar in PILLARS if pillar not in seen_pillars]
    require(not missing, f"el manifiesto no cubre los pilares: {', '.join(missing)}")

    postgres = data["postgres"]
    require(isinstance(postgres, Mapping), "'postgres' no es un objeto")
    require(
        bool(str(postgres.get("database", "")).strip()),
        "postgres.database vacio: un restore necesita saber que base se creo",
    )
    require(
        isinstance(postgres.get("tables"), Mapping) and bool(postgres["tables"]),
        "postgres.tables vacio: la base no tiene ninguna tabla. "
        "¿Se ha ejecutado `python -m alembic upgrade head`?",
    )
    require(
        bool(str(postgres.get("alembic_version", "")).strip()),
        "postgres.alembic_version vacio: sin el no se puede validar el esquema restaurado",
    )
    require(
        str(postgres.get("alembic_version")) == str(data["alembic_head"]),
        f"la base esta en {postgres.get('alembic_version')} pero el codigo esta en "
        f"{data['alembic_head']}: el backup restauraria un esquema anterior al head",
    )

    minio = data["minio"]
    require(isinstance(minio, Mapping), "'minio' no es un objeto")
    require(bool(str(minio.get("source_bucket", "")).strip()), "minio.source_bucket vacio")
    require(
        isinstance(minio.get("objects"), Sequence) and not isinstance(minio["objects"], (str, bytes)),
        "minio.objects debe ser una lista",
    )

    qdrant = data["qdrant"]
    require(isinstance(qdrant, Mapping), "'qdrant' no es un objeto")
    collections = qdrant.get("collections")
    require(
        isinstance(collections, Sequence) and not isinstance(collections, (str, bytes)),
        "qdrant.collections debe ser una lista",
    )
    require(bool(collections), "qdrant.collections vacio: no hay nada que restaurar")
    for collection in collections:
        require(isinstance(collection, Mapping), "cada coleccion debe ser un objeto")
        require(bool(str(collection.get("name", "")).strip()), "coleccion sin nombre")
        require(
            isinstance(collection.get("points"), int) and collection["points"] >= 0,
            f"coleccion {collection.get('name')}: 'points' debe ser un entero >= 0",
        )
        require(
            isinstance(collection.get("dimensions"), Mapping) and bool(collection["dimensions"]),
            f"coleccion {collection.get('name')}: 'dimensions' vacio; "
            "un indice con otra dimension no es el mismo indice",
        )


def artifacts_by_pillar(manifest: Mapping[str, Any], pillar: str) -> list[dict[str, Any]]:
    require(pillar in PILLARS, f"pilar desconocido: {pillar!r}")
    return [dict(a) for a in manifest["artifacts"] if a["pillar"] == pillar]


def format_table(
    checks: Iterable[Any],
    *,
    heading: str,
) -> str:
    """Tabla legible de `CheckResult` para consola y runbook."""
    lines = [heading, "-" * len(heading)]
    for check in checks:
        mark = "OK  " if check.passed else "FALLO"
        lines.append(f"  [{mark}] {check.name}: {check.detail}")
    return "\n".join(lines)


def exit_with(report: str, ok: bool) -> int:
    print(report)
    if not ok:
        print("RESULTADO: FALLO (fail-closed)", file=sys.stderr)
    return 0 if ok else 1
