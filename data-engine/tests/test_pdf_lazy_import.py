"""matplotlib es un import perezoso del servicio de PDF.

El arranque del API lo pagaba entero en cada despliegue/reinicio del
contenedor (medido en laboratorio: ``import main`` 5,3 s -> 3,6 s con la caché
de fuentes fría, font_manager escanea las fuentes del sistema; en el primer
arranque del sandbox, 9,9 s -> 3,6 s) aunque el PDF se exporta una vez al día.
El primer PDF de un proceso frío paga el import; el hilo de calentado de
``main._start_pdf_warmup`` (solo producción) lo adelanta tras el arranque para
que la descarga siga dentro de su presupuesto de <5 s.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

DATA_ENGINE_DIR = Path(__file__).resolve().parents[1]


def _run(code: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "APP_ENV": "test",
        "WORKERS_ENABLED": "false",
        "MPLBACKEND": "Agg",
        "DATABASE_URL": "sqlite:///:memory:",
    }
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=DATA_ENGINE_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_importar_main_no_carga_matplotlib():
    code = (
        "import sys\n"
        "import main\n"
        "raise SystemExit(0 if 'matplotlib' not in sys.modules else 1)\n"
    )
    result = _run(code)
    assert result.returncode == 0, result.stderr


def test_primer_pdf_importa_matplotlib_y_genera_bytes():
    code = (
        "import sys\n"
        "from app.services.thesis_pdf_service import ThesisPdfData, build_thesis_pdf\n"
        "assert 'matplotlib' not in sys.modules\n"
        "pdf = build_thesis_pdf(ThesisPdfData(ticker='SAN', company_name='Banco Santander', version=1, sections=[]))\n"
        "assert pdf.startswith(b'%PDF-') and len(pdf) > 1000\n"
        "assert 'matplotlib' in sys.modules\n"
    )
    result = _run(code)
    assert result.returncode == 0, result.stderr
