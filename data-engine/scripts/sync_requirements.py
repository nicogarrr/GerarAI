#!/usr/bin/env python3
"""Paridad pyproject.toml <-> requirements.txt (stdlib only).

Fuente unica: ``[project].dependencies`` de ``pyproject.toml``.
``requirements.txt`` es un artefacto generado para pip/Docker/CI.

Uso:
    python scripts/sync_requirements.py --check   # CI: falla si derivan
    python scripts/sync_requirements.py --write   # regenera specs en requirements.txt

Reglas:
- Cada paquete de pyproject debe existir en requirements.txt con el MISMO
  especificador de version (se comparan normalizados: lower + -/_).
- ``torch`` es especial: pyproject declara el rango portable (``torch>=2.5``)
  y requirements.txt fija el pin CPU-only (``torch==X.Y.Z+cpu``) que solo
  existe en el indice de PyTorch (--extra-index-url de la cabecera).
- ``torchvision`` es transitiva (docling) y no sale aqui: su pin CPU-only
  (``TORCHVISION_CPU_PIN``) vive en ``[tool.uv] constraint-dependencies`` y lo
  verifica ``verify_lockfile.py``, no este script.
- Paquetes solo en requirements.txt (o viceversa) => error en --check.
"""
from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
REQUIREMENTS = ROOT / "requirements.txt"

# Pin CPU-only verificado (wheels linux amd64/aarch64 + win64 en el indice
# de PyTorch). Al subirlo, actualizar tambien Dockerfile y Dockerfile.prod.
# 2.14.1: combo verificado con docling 2.132 + fastembed 0.8.1 (Fase B).
TORCH_CPU_PIN = "torch==2.14.1+cpu"

# torchvision NO es dependencia directa (entra transitiva via docling), asi que
# no aparece en requirements.txt: pip prefiere siempre la wheel +cpu del indice
# de PyTorch (misma version con sufijo local ordena por encima). uv no: sin
# constraint la resolvia de PyPI, compilada contra el torch de PyPI, y el
# import reventaba con RuntimeError "operator torchvision::nms does not exist"
# (run 41259298388 del job Evals, 2026-11-01). El pin vive en
# pyproject.toml [tool.uv] constraint-dependencies; verify_lockfile.py lo exige
# en el lock. Al subir torch, subir torchvision a la pareja de su matriz de
# compatibilidad (torch 2.N.x <-> torchvision 0.(N+15).x).
TORCHVISION_CPU_PIN = "torchvision==0.29.1+cpu"

_REQ_RE = re.compile(
    r"^\s*([A-Za-z0-9_.\-]+(?:\[[A-Za-z0-9_.\-, ]+\])?)"
    r"(?:\s*(===|==|~=|!=|>=|<=|>|<)\s*([^;\s#]+))?"
    r"\s*(;[^\#]*)?\s*(\#.*)?$"
)


def norm(name: str) -> str:
    return name.lower().replace("_", "-").split("[")[0]


def split_req(dep: str) -> tuple[str, str]:
    dep = dep.strip().strip("\"'")
    m = re.match(r"^([A-Za-z0-9_.\-\[\]]+)\s*(.*)$", dep)
    if not m:
        raise ValueError(f"Dependencia no parseable: {dep!r}")
    return norm(m.group(1)), m.group(2).strip()


def load_pyproject() -> dict[str, str]:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for dep in data["project"]["dependencies"]:
        name, spec = split_req(dep)
        out[name] = spec
    return out


def load_requirements() -> tuple[dict[str, str], list[str]]:
    specs: dict[str, str] = {}
    lines = REQUIREMENTS.read_text(encoding="utf-8").splitlines()
    for line in lines:
        s = line.strip()
        if not s or s.startswith(("#", "-", " ")):
            continue
        if s.startswith("--"):
            continue
        m = _REQ_RE.match(line)
        if not m:
            continue
        name = norm(m.group(1))
        op, ver = m.group(2) or "", (m.group(3) or "").strip()
        specs[name] = f"{op}{ver}".strip()
    return specs, lines


def check() -> int:
    py = load_pyproject()
    req, _ = load_requirements()
    errors: list[str] = []
    for name, spec in sorted(py.items()):
        if name == "torch":
            got = req.get(name, "")
            want = TORCH_CPU_PIN[len("torch"):]
            if got != want:
                errors.append(f"torch: requirements.txt tiene {got!r}, se exige {TORCH_CPU_PIN!r}")
            continue
        if name not in req:
            errors.append(f"{name}: falta en requirements.txt (pyproject: {spec!r})")
        elif req[name] != spec:
            errors.append(f"{name}: requirements.txt={req[name]!r} != pyproject={spec!r}")
    for name in sorted(req):
        if name not in py:
            errors.append(f"{name}: solo en requirements.txt, falta en pyproject.toml")
    if errors:
        print("Paridad pyproject<->requirements ROTA:")
        for e in errors:
            print(f"  - {e}")
        print("Regenera con: python data-engine/scripts/sync_requirements.py --write")
        return 1
    print(f"Paridad OK ({len(py)} paquetes).")
    return 0


def write() -> int:
    py = load_pyproject()
    _, lines = load_requirements()
    out: list[str] = []
    seen: set[str] = set()
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("--"):
            out.append(line)
            continue
        m = _REQ_RE.match(line)
        if not m:
            out.append(line)
            continue
        name = norm(m.group(1))
        if name == "torch":
            out.append(TORCH_CPU_PIN + ("  # " + m.group(5).lstrip("# ") if m.group(5) else ""))
            seen.add(name)
            continue
        if name in py:
            marker = f" {m.group(4).strip()}" if m.group(4) else ""
            comment = f"  {m.group(5)}" if m.group(5) else ""
            out.append(f"{m.group(1)}{py[name]}{marker}{comment}".rstrip())
            seen.add(name)
        else:
            out.append(line)
    missing = sorted(set(py) - seen - {"torch"})
    if missing:
        out.append("")
        out.append("# Anadidas por sync_requirements.py (estaban en pyproject, no aqui):")
        for name in missing:
            out.append(f"{name}{py[name]}")
    REQUIREMENTS.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"requirements.txt actualizado ({len(py)} paquetes en pyproject).")
    return check()


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "--check"
    if mode == "--check":
        raise SystemExit(check())
    if mode == "--write":
        raise SystemExit(write())
    print(__doc__)
    raise SystemExit(2)
