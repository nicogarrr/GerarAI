"""Contratos de limpieza del drill de verificacion de backups (sin servicios).

Contexto (medido en la VM, 5-nov-2026): las verificaciones de backup/predeploy
crean ~10 GB de volumenes por corrida; cuando la corrida termina bien el
propio script los limpia, pero una interrumpida a la fuerza (kill -9, sin
trap) dejaba contenedores cavaai-verify-* vivos que RETENIAN los volumenes:
el `docker volume rm` del arranque siguiente fallaba en silencio y el drill
media sobre una base restaurada a medias. Ademas cada drill construia la
imagen cavaai-backend:verify (~4,4 GB) y nunca la borraba.

Estos tests fijan estaticamente las defensas de scripts/verify-backup-restore.sh:
  * todo volumen del drill tiene nombre cavaai-verify-* (nada anonimo);
  * al arrancar se barren los contenedores aislados de un drill interrumpido
    ANTES de borrar volumenes;
  * la limpieza (trap EXIT) baja el proyecto, borra los volumenes con nombre,
    el freshduck y la imagen del drill;
  * el script sigue siendo bash valido.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "verify-backup-restore.sh"


def _src() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_el_script_es_bash_valido():
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_todo_volumen_del_drill_tiene_nombre_propio():
    src = _src()
    # docker run -v X:/data: X siempre es un volumen con nombre cavaai-verify-*
    # o una variable que lo contiene; nunca un bind mount ni anonimo.
    for m in re.finditer(r"docker run[^\n]*-v\s+([^\s:]+):", src):
        origen = m.group(1)
        # "${VOL}" es la variable del bucle 4/5: toma MINIO_VOLUME/DUCKDB_VOLUME,
        # ambas cavaai-verify-* (lo fija el export de mas arriba).
        assert (
            "cavaai-verify" in origen or "VOLUME" in origen or origen == '"${VOL}"'
        ), f"mount sin volumen con nombre del drill: {origen}"
    # El sed que deriva el compose mapea TODOS los volumenes prod -> verify.
    assert "s/name: cavaai-prod-/name: cavaai-verify-/" in src


def test_el_arranque_barre_contenedores_de_un_drill_interrumpido():
    src = _src()
    sweep = src.index('docker ps -aq --filter "name=cavaai-verify-"')
    # La limpieza (definida antes en el script) tambien borra volumenes: el
    # rm relevante es el del ARRANQUE, posterior al barrido.
    rm_vols = src.index("docker volume rm ${VERIFY_DATA_VOLUMES}", sweep)
    assert "docker rm -f ${STALE_VERIFY}" in src
    assert sweep < rm_vols, (
        "el barrido de contenedores tiene que ir ANTES del rm de volumenes: "
        "un contenedor vivo retiene el volumen y el rm falla en silencio"
    )


def test_la_limpieza_cubre_proyecto_volumenes_e_imagen():
    src = _src()
    cleanup = src[src.index("cleanup()") : src.index("trap cleanup EXIT")]
    assert "down -v --remove-orphans" in cleanup
    assert "docker volume rm ${VERIFY_DATA_VOLUMES} cavaai-verify-freshduck" in cleanup
    assert "docker image rm cavaai-backend:verify" in cleanup
    assert 'rm -f "${VERIFY_COMPOSE}"' in cleanup


def test_la_trampa_sigue_en_exit():
    assert "trap cleanup EXIT" in _src()
