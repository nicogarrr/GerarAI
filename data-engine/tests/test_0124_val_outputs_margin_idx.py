"""0124: indice parcial de candidatos a margen para _any_margin_of_safety
y alineacion del modelo (mismo nombre de indice)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic.config import Config

from alembic import command
from tests.test_alembic_chain import VERSIONS_DIR

_NOMBRE = "ix_val_outputs_margin_candidate"


def _sqlite_head(tmp_path, monkeypatch) -> sa.Engine:
    from app.core.config import get_settings

    url = f"sqlite:///{tmp_path}/mig0124.db"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    cfg = Config(str(VERSIONS_DIR.parent.parent / "alembic.ini"))
    cfg.set_main_option("script_location", str(VERSIONS_DIR.parent))
    command.upgrade(cfg, "head")
    get_settings.cache_clear()
    return sa.create_engine(url)


def test_0124_indice_existe_tras_upgrade_head_en_sqlite(tmp_path, monkeypatch) -> None:
    engine = _sqlite_head(tmp_path, monkeypatch)
    with engine.connect() as conn:
        nombres = {
            row[0]
            for row in conn.execute(
                sa.text("select name from sqlite_master where type='index'")
            )
        }
    assert _NOMBRE in nombres


def test_0124_modelo_declara_el_mismo_indice() -> None:
    from app.models.entities import ValuationOutput

    nombres = {ix.name for ix in ValuationOutput.__table__.indexes}
    assert _NOMBRE in nombres


def test_0124_predicado_pg_replica_la_constante_de_convenio() -> None:
    """El literal del indice y el de la sonda salen del mismo convenio."""
    from app.models.entities import ValuationOutput
    from app.services import screener_context_metrics as scm
    from app.valuation.margin_convention import MARGIN_OF_SAFETY_CONVENTION

    indice = next(
        ix for ix in ValuationOutput.__table__.indexes if ix.name == _NOMBRE
    )
    predicado = str(indice.dialect_options["postgresql"]["where"])
    assert f"'{MARGIN_OF_SAFETY_CONVENTION}'" in predicado
    assert f"'{MARGIN_OF_SAFETY_CONVENTION}'" in str(scm._MARGEN_SONDA_PG)
