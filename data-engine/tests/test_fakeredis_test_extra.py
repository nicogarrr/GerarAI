"""fakeredis declarado en el extra test: sin el, los tests de Redis se saltan en silencio.

Hueco medido (9-nov-2026, auditor): app/services/queue_watchdog.py al 39,4%
de cobertura en CI frente al 88% local. Causa: tests/test_queue_watchdog.py
(y otros del carril de colas) hacen ``pytest.importorskip("fakeredis")``,
pero fakeredis NO estaba declarado en el extra ``test`` de pyproject.toml:
existia solo en venvs locales donde alguien lo habia instalado a mano.
Los jobs de CI (``uv sync --frozen --extra test --extra dev``) no lo traian,
los tests se saltaban sin ruido y la cobertura real del modulo se hundia.

El extra ``test`` no rompe la paridad dep-parity: sync_requirements.py solo
inspecciona [project].dependencies contra requirements.txt (ver el comentario
de pyproject). Este guard fija la declaracion y el lock para que el hueco
no vuelva a abrirse si alguien mueve o recorta el extra.
"""
from __future__ import annotations

import re
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"
UV_LOCK = Path(__file__).resolve().parents[1] / "uv.lock"


def test_fakeredis_declarado_en_extra_test() -> None:
    contenido = PYPROJECT.read_text()
    extra = re.search(r"(?m)^test = \[(.*?)\]", contenido)
    assert extra, "pyproject.toml: no se encuentra el extra 'test'"
    assert re.search(r'"fakeredis[^"]*"', extra.group(1)), (
        "fakeredis no esta en el extra 'test': los tests de Redis del carril "
        "de colas vuelven a saltarse en silencio fuera de los venvs locales"
    )


def test_fakeredis_en_uv_lock() -> None:
    assert re.search(r'(?m)^name = "fakeredis"$', UV_LOCK.read_text()), (
        "fakeredis no esta resuelto en uv.lock: falta `uv lock` tras declararlo"
    )
