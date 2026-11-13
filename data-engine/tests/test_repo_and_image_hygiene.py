"""El repositorio y las imagenes no pueden volver a crecer con datos.

Cuatro invariantes, todas con un coste ya medido cuando se incumplieron:

1. data-engine/data/ son 2.008 ficheros de snapshots SEC/ESEF (~870 MB) con
   un blob de un solo ESEF de 59 MB, el 59% del limite de push de GitHub. Se
   regeneran con los scripts build_*_snapshots.py y en produccion viajan como
   volumen montado. Versionarlos hacia que el siguiente ESEF rompia `git push`.
2. Los .dockerignore se escribieron 423 commits antes que los directorios de
   datos que tenian que excluir. Ambas imagenes del engine hacen `COPY . .`, asi
   que el contexto eran 835 MB y el del frontend 1,7 GB.
3. .env.production no estaba en el .dockerignore enumerado. Con `COPY . .` y
   output:'standalone', `next build` lo mete en required-server-files.json.
4. Los contenedores del engine corrian como root con los volumenes montados en
   modo lectura-escritura, y `sh -c` dejaba a uvicorn como hijo de sh (sin
   SIGTERM ni teardown del lifespan).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# El test vive en data-engine/tests/, asi que la raiz del repo es parents[2].
ROOT = Path(__file__).resolve().parents[2]


def _gitignore_lines() -> list[str]:
    return [
        line.strip()
        for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _dockerignore_entries(name: str) -> list[str]:
    return [
        line.strip()
        for line in (ROOT / name).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


# --------------------------------------------------------------------------
# 1. Los datos de mercado no se versionan
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "data-engine/data/sec_snapshots/companyfacts/CIK0001376321.json",
        "data-engine/data/esef_snapshots/manifest.json",
        "data-engine/storage/analytics.duckdb",
        "data-esef-snapshots/some-filing.json",
    ],
)
def test_market_data_paths_are_ignored(path):
    import subprocess

    result = subprocess.run(
        ["git", "check-ignore", "-q", "--no-index", "--", path],
        cwd=ROOT,
        capture_output=True,
    )
    assert result.returncode == 0, f"{path} es versionable: acabaria en el repo"


def test_gitignore_covers_data_and_derived_dbs():
    patterns = _gitignore_lines()
    joined = "\n".join(patterns)
    assert "/data-engine/data/" in joined
    assert "/data-esef-snapshots/" in joined
    assert "*.duckdb" in patterns


# --------------------------------------------------------------------------
# 2 y 3. Los contextos de build
# --------------------------------------------------------------------------


@pytest.mark.parametrize("ignore", [".dockerignore", "data-engine/.dockerignore"])
def test_dockerignore_excludes_market_data(ignore):
    joined = "\n".join(_dockerignore_entries(ignore))
    assert "data/" in joined, f"{ignore} no excluye data/: 835 MB de snapshots"
    assert "storage/" in joined or "data-engine/storage/" in joined


def test_root_dockerignore_excludes_every_env_variant():
    """El listado enumerado dejaba fuera .env.production."""
    joined = "\n".join(_dockerignore_entries(".dockerignore"))
    assert ".env.*" in joined, "falta el glob .env* (solo hay entradas sueltas)"
    assert ".env.production" in joined or ".env.*" in joined


def test_root_dockerignore_excludes_the_whole_frontend_source():
    joined = "\n".join(_dockerignore_entries(".dockerignore"))
    for entry in ("node_modules", ".next", ".git", "data-engine/data/", "storage/"):
        assert entry in joined, f".dockerignore no excluye {entry}"


# --------------------------------------------------------------------------
# 4. La imagen del engine no corre como root y uvicorn recibe SIGTERM
# --------------------------------------------------------------------------


@pytest.mark.parametrize("dockerfile", ["data-engine/Dockerfile", "data-engine/Dockerfile.prod"])
def test_engine_image_drops_root(dockerfile):
    text = (ROOT / dockerfile).read_text(encoding="utf-8")
    assert re.search(r"^USER\s+(?!root)\S+", text, re.M), (
        f"{dockerfile} no declara USER: el backend corre como root con los "
        "volumenes montados en modo lectura-escritura"
    )


@pytest.mark.parametrize("dockerfile", ["data-engine/Dockerfile", "data-engine/Dockerfile.prod"])
def test_engine_image_execs_uvicorn(dockerfile):
    text = (ROOT / dockerfile).read_text(encoding="utf-8")
    cmd = [ln for ln in text.splitlines() if ln.startswith("CMD")]
    assert cmd, f"{dockerfile} sin CMD"
    assert any("exec uvicorn" in ln for ln in cmd), (
        f"{dockerfile}: sin `exec`, sh queda como PID 1 y el SIGTERM de "
        "`docker stop` no llega a uvicorn (SIGKILL a los 10 s, sin teardown "
        "del lifespan)"
    )


def test_prod_uvicorn_keepalive_outlives_the_client():
    """El front (undici) cierra sockets ociosos a los 4 s; uvicorn debe aguantar mas."""
    text = (ROOT / "data-engine/Dockerfile.prod").read_text(encoding="utf-8")
    cmd = " ".join(ln for ln in text.splitlines() if ln.startswith("CMD"))
    match = re.search(r"--timeout-keep-alive\s+(\d+)", cmd)
    assert match, "Dockerfile.prod: uvicorn sin --timeout-keep-alive (default 5 s, carrera con el cliente)"
    assert int(match.group(1)) > 5
