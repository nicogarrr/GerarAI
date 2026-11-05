"""Contratos de los scripts ops de disco (sin servicios ni docker).

rotate-predeploy-snapshots.sh: retencion de los snapshots predeploy-*.json
del volumen duckdb (~40 MB por deploy, nunca rotaban - medido 5-nov-2026).
check-disk-space.sh: alerta al 85% para no redescubrir el disco al 90%.

Ambos los ejecuta un operador, nunca un agente ni un cron ciego. Estos
tests fijan el contrato: confirmacion explicita, alcance limitado a
predeploy-*.json (la cache de modelos del volumen NO se toca), bash valido
y comportamiento real del chequeo de disco con umbrales forzados.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ROTATE = REPO_ROOT / "scripts" / "ops" / "rotate-predeploy-snapshots.sh"
DISK = REPO_ROOT / "scripts" / "ops" / "check-disk-space.sh"


def test_scripts_bash_validos():
    subprocess.run(["bash", "-n", str(ROTATE)], check=True)
    subprocess.run(["bash", "-n", str(DISK)], check=True)


def test_rotacion_exige_confirmacion_y_limita_alcance():
    src = ROTATE.read_text(encoding="utf-8")
    assert "--confirm-rotate" in src
    # Solo predeploy-*.json del nivel raiz del volumen: la cache de modelos
    # (fastembed-cache, docling-artifacts) y el resto del volumen no se tocan.
    assert "predeploy-*.json" in src
    assert "fastembed" not in src.split("set -euo pipefail", 1)[1].replace("#", " ")
    # Conserva los KEEP mas recientes por fecha de modificacion.
    assert "ls -1t" in src and "tail -n +" in src


def test_rotacion_sin_flag_no_hace_nada():
    r = subprocess.run(["bash", str(ROTATE)], capture_output=True, text=True)
    assert r.returncode == 1
    assert "confirm-rotate" in r.stdout


def test_disco_umbral_85_por_defecto_y_sale_1_en_alerta():
    src = DISK.read_text(encoding="utf-8")
    assert '"${1:-85}"' in src
    ok = subprocess.run(["bash", str(DISK), "99"], capture_output=True, text=True)
    assert ok.returncode == 0 and "[disk] OK" in ok.stdout
    alerta = subprocess.run(["bash", str(DISK), "1"], capture_output=True, text=True)
    assert alerta.returncode == 1 and "ALERTA" in alerta.stdout
    mal = subprocess.run(["bash", str(DISK), "abc"], capture_output=True, text=True)
    assert mal.returncode == 2
