"""Regresion: un upgrade alembic EN PROCESO no puede tumbar el logging del resto.

env.py aplica fileConfig(alembic.ini); con el default disable_existing_loggers=True
todo logger ya creado (los modulos app se importan durante la coleccion) quedaba
deshabilitado, y las aserciones sobre caplog del resto de la suite fallaban en
cadena con capturas vacias (firma del Backend quality del 31-oct: alerts_timing,
redis_outage_503, pool_probe, async_offload, task_trace...). La proteccion por
subproceso de test_0121/test_migrations sorteaba el sintoma; esto fija la raiz.

El handler propio (no caplog) es a proposito: fileConfig reconfigura root a
mitad de test y caplog no es la victima que se mide aqui, sino los tests que
corren DESPUES del upgrade en el mismo worker.
"""

import io
import logging

from alembic.config import Config

from alembic import command
from app.core.config import get_settings
from tests.test_alembic_chain import VERSIONS_DIR


def test_upgrade_en_proceso_conserva_los_loggers_previos(tmp_path, monkeypatch):
    logger = logging.getLogger("tests.migraciones.logging_vivo")
    logger.setLevel(logging.INFO)
    logger.info("calienta")  # el logger existe ANTES del fileConfig de env.py

    url = f"sqlite:///{tmp_path}/mig_logging.db"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    try:
        cfg = Config(str(VERSIONS_DIR.parent.parent / "alembic.ini"))
        cfg.set_main_option("script_location", str(VERSIONS_DIR.parent))
        command.upgrade(cfg, "head")
    finally:
        get_settings.cache_clear()

    assert logger.isEnabledFor(logging.INFO), "fileConfig deshabilito un logger previo"
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)
    try:
        logger.info("sigue vivo tras el upgrade")
    finally:
        logger.removeHandler(handler)
    assert "sigue vivo tras el upgrade" in stream.getvalue()
