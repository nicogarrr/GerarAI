"""La familia torch del lock sale entera del indice CPU de PyTorch.

Regresion del run 41259298388 (job Evals de ci.yml, 2026-11-01): uv.lock
fijaba ``torch==2.14.1+cpu`` (indice de PyTorch) pero ``torchvision==0.29.1``
de PyPI, compilada contra el torch de PyPI. La cadena de import real
``sentence_transformers`` -> ``transformers.image_utils`` -> ``torchvision``
reventaba con ``RuntimeError: operator torchvision::nms does not exist`` y
run_rag_evals caia cerrado (sin stub). Estos tests fijan la invariante sin
instalar nada: pin, indice y constraint, sobre el lock real y sobre locks
sinteticos (positivo y negativos).
"""

import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sync_requirements as sr  # noqa: E402
import verify_lockfile as vl  # noqa: E402


def _lock_real() -> dict:
    return tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _pkg(lock: dict, name: str) -> dict | None:
    for pkg in lock.get("package", []):
        if sr.norm(pkg["name"]) == name:
            return pkg
    return None


def _constraints(lock: dict) -> dict:
    return {sr.norm(c["name"]): c for c in (lock.get("manifest") or {}).get("constraints") or []}


def _lock_sintetico(
    tv_version: str = "0.29.1+cpu",
    tv_registry: str = vl.TORCH_INDEX,
    tv_constraint: str | None = "==0.29.1+cpu",
) -> dict:
    constraints = [
        {"name": "torch", "specifier": f"=={vl.TORCH_PINNED}", "index": vl.TORCH_INDEX},
    ]
    if tv_constraint is not None:
        constraints.append({"name": "torchvision", "specifier": tv_constraint, "index": vl.TORCH_INDEX})
    return {
        "manifest": {"constraints": constraints},
        "package": [
            {"name": "torch", "version": vl.TORCH_PINNED, "source": {"registry": vl.TORCH_INDEX}},
            {"name": "torchvision", "version": tv_version, "source": {"registry": tv_registry}},
        ],
    }


# ---------------------------------------------------------------- lock real
def test_lock_real_torch_cpu():
    pkg = _pkg(_lock_real(), "torch")
    assert pkg is not None, "torch ausente del lock"
    assert pkg["version"] == vl.TORCH_PINNED
    assert (pkg.get("source") or {}).get("registry") == vl.TORCH_INDEX


def test_lock_real_torchvision_cpu():
    """La regresion del run 41259298388: torchvision fijada desde PyPI."""
    pkg = _pkg(_lock_real(), "torchvision")
    assert pkg is not None, "torchvision ausente del lock (la trae docling)"
    assert pkg["version"] == vl.TORCHVISION_PINNED, (
        f"torchvision=={pkg['version']} no es el pin CPU-only {vl.TORCHVISION_PINNED}: "
        "la wheel de PyPI esta compilada contra el torch de PyPI y revienta "
        "con 'operator torchvision::nms does not exist' sobre torch +cpu"
    )
    src = (pkg.get("source") or {}).get("registry")
    assert src == vl.TORCH_INDEX, f"torchvision sale de {src!r}, no del indice CPU de PyTorch"


def test_lock_real_constraints_registradas():
    constraints = _constraints(_lock_real())
    assert constraints.get("torch", {}).get("specifier") == f"=={vl.TORCH_PINNED}"
    assert constraints.get("torchvision", {}).get("specifier") == f"=={vl.TORCHVISION_PINNED}"


def test_pyproject_declara_constraint_y_source_de_torchvision():
    """Sin las dos piezas en pyproject, el siguiente `uv lock` la recoloca mal."""
    tool_uv = _pyproject().get("tool", {}).get("uv", {})
    constraints = tool_uv.get("constraint-dependencies", [])
    assert sr.TORCHVISION_CPU_PIN in constraints, (
        f"falta {sr.TORCHVISION_CPU_PIN!r} en [tool.uv] constraint-dependencies"
    )
    sources = tool_uv.get("sources", {})
    assert sources.get("torchvision", {}).get("index") == "pytorch-cpu"


def test_pins_torch_y_torchvision_son_pareja_de_la_matriz():
    """torch 2.N.x va con torchvision 0.(N+15).x; subir uno sin el otro rompe la ABI."""
    torch_v = vl.release_tuple(vl.TORCH_PINNED)
    tv_v = vl.release_tuple(vl.TORCHVISION_PINNED)
    assert torch_v[0] == 2 and tv_v[0] == 0
    assert tv_v[1] == torch_v[1] + 15, (
        f"torch {vl.TORCH_PINNED} va con torchvision 0.{torch_v[1] + 15}.x, no con {vl.TORCHVISION_PINNED}"
    )
    assert tv_v[2] == torch_v[2]


# -------------------------------------------------------- check sintetico
def test_check_torch_cpu_acepta_lock_sano():
    errors: list[str] = []
    vl.check_torch_cpu(_lock_sintetico(), errors)
    assert errors == []


def test_check_torch_cpu_caza_torchvision_de_pypi():
    """El caso exacto del run 41259298388: version y registry de PyPI."""
    errors: list[str] = []
    vl.check_torch_cpu(
        _lock_sintetico(tv_version="0.29.1", tv_registry="https://pypi.org/simple", tv_constraint=None),
        errors,
    )
    assert any("torchvision" in e and "pypi.org" in e for e in errors)
    assert any("torchvision" in e and "0.29.1" in e for e in errors)
    assert any("torchvision" in e and "constraint" in e for e in errors)


def test_check_torch_cpu_caza_constraint_ausente():
    errors: list[str] = []
    vl.check_torch_cpu(_lock_sintetico(tv_constraint=None), errors)
    assert len(errors) == 1 and "torchvision" in errors[0] and "constraint" in errors[0]


def test_check_torch_cpu_caza_version_flotada():
    """Un `uv lock --upgrade` sin constraint subiria torchvision sobre el pin."""
    errors: list[str] = []
    vl.check_torch_cpu(_lock_sintetico(tv_version="0.30.0+cpu", tv_constraint="==0.29.1+cpu"), errors)
    assert any("torchvision" in e and "0.30.0+cpu" in e for e in errors)


def test_check_torch_cpu_caza_torchvision_ausente():
    lock = _lock_sintetico()
    lock["package"] = [p for p in lock["package"] if p["name"] != "torchvision"]
    errors: list[str] = []
    vl.check_torch_cpu(lock, errors)
    assert any("torchvision" in e and "AUSENTE" in e for e in errors)


def test_check_torch_cpu_no_rompe_el_chequeo_de_torch():
    """El chequeo original de torch sigue intacto tras generalizarlo."""
    lock = _lock_sintetico()
    lock["package"][0]["source"] = {"registry": "https://pypi.org/simple"}
    errors: list[str] = []
    vl.check_torch_cpu(lock, errors)
    assert any(e.startswith("torch:") and "pypi.org" in e for e in errors)
    assert not any(e.startswith("torchvision:") for e in errors)
