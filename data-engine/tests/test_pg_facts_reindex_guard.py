"""Contratos del script ops de reclaim de financial_facts (sin servicios).

scripts/ops/pg-facts-reindex.sh recupera el bloat historico de
financial_facts (1,36 GB de indices medidos el 5-nov-2026) SIN tocar una
fila. Es una herramienta de operador con backup previo, nunca automatica.
Estos tests fijan ese contrato:

  * exige --confirm-reindex (sin flag no hace nada);
  * REINDEX va CONCURRENTLY (no bloquea la tabla en produccion) y fuera de
    transaccion (psql -c por sentencia);
  * NO hay VACUUM FULL ni DELETE/DROP/TRUNCATE: ninguna forma de perder datos;
  * mide e imprime el antes/despues (bloat y tamano por indice);
  * bash -n valido.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ops" / "pg-facts-reindex.sh"


def _src() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_el_script_es_bash_valido():
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_exige_confirmacion_explicita():
    src = _src()
    assert "--confirm-reindex" in src
    # Sin el flag, sale antes de tocar nada.
    assert re.search(r'case "\$\{1:-\}" in\s*\n\s*--confirm-reindex\)', src)


def test_reindex_es_concurrently_y_sin_transaccion():
    src = _src()
    assert "REINDEX TABLE CONCURRENTLY" in src
    # Cada sentencia en su propio psql -c: REINDEX CONCURRENTLY no puede ir
    # en bloque de transaccion.
    assert re.search(r'psql [^\n]*-c "REINDEX TABLE CONCURRENTLY', src) or (
        '-c "REINDEX TABLE CONCURRENTLY' in src
    )


def _code() -> str:
    """Solo lineas ejecutables: los comentarios documentan lo prohibido."""
    return "\n".join(
        line for line in _src().splitlines() if not line.lstrip().startswith("#")
    )


def test_no_borra_datos_en_ninguna_forma():
    src = _code()
    assert "VACUUM FULL" not in src
    for prohibido in ("DELETE FROM", "DROP TABLE", "TRUNCATE"):
        assert prohibido not in src, f"sentencia destructiva en el script: {prohibido}"
    # La unica forma de DROP permitida es la limpieza de restos *_ccnew
    # invalidos (CONCURRENTLY + IF EXISTS: nunca bloquea ni falla si no hay).
    for m in re.finditer(r'DROP INDEX[^"]*', src):
        assert m.group(0).startswith("DROP INDEX CONCURRENTLY IF EXISTS"), m.group(0)
    # VACUUM solo con ANALYZE (recicla tuplas muertas, sin bloqueo).
    assert "VACUUM (ANALYZE)" in src


def test_valida_reindex_table_como_identificador():
    import os
    src = _src()
    # REINDEX_TABLE se interpola en SQL: debe validarse como identificador.
    assert "identificador valido" in src
    # REINDEX_TABLE vacio cae al defecto (financial_facts) por ":-".
    for valor in ("facts; DROP TABLE users", "facts-wrong", "1facts"):
        env = dict(os.environ, REINDEX_TABLE=valor)
        r = subprocess.run(
            ["bash", str(SCRIPT), "--confirm-reindex"],
            capture_output=True, text=True, env=env,
        )
        assert r.returncode == 2, f"REINDEX_TABLE={valor!r} no rechazado: {r}"


def test_gestiona_indices_invalidos_tras_interrupcion():
    src = _code()
    # Detecta indices INVALID de la tabla (pg_index.indisvalid) al arrancar.
    assert "indisvalid" in src
    # Limpia solo los restos *_ccnew de un CONCURRENTLY interrumpido.
    assert re.search(r"\*_ccnew\)", src)
    assert "DROP INDEX CONCURRENTLY IF EXISTS" in src
    # Cualquier otro indice invalido: avisa y sale sin tocar nada mas.
    assert re.search(r"indices INVALID que no son restos _ccnew", src)
    # La cabecera deja claro que --confirm-reindex NO verifica el backup.
    assert "NO comprueba" in _src()


def test_mide_antes_y_despues():
    src = _src()
    assert src.count("pg_total_relation_size") >= 2
    assert src.count("n_dead_tup") >= 2
    assert "pg_stat_user_indexes" in src
