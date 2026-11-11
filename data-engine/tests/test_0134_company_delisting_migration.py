"""0134: ``companies.delisted_at`` (+ indice parcial) y ``companies.listing_note``.

Baja de un listado SOLO con evidencia primaria (decision del piloto,
11-nov-2026): 5 sesiones sin barra son ausencia de datos (derivada y
reversible), nunca baja. Caso real: SES.TO, adquisicion cerrada por GFL el
1-sep-2026. Migracion aditiva y reversible (patron ``migration_added_columns``
de 0132): cuelga de 0133_watch_auto_analysis (revision del piloto); el ciclo
completo corre cuando esa revision exista en ``alembic/versions``.
"""

from __future__ import annotations

import importlib.util

import pytest
import sqlalchemy as sa
from alembic.config import Config

from alembic import command
from tests.test_alembic_chain import VERSIONS_DIR

TABLE = "companies"
REVISION = "0134_company_delisting"
PREVIOUS = "0133_watch_auto_analysis"
NEW_COLUMNS = {"delisted_at", "listing_note"}
INDEX = "ix_companies_delisted_at"


def _module():
    spec = importlib.util.spec_from_file_location("migration0134", VERSIONS_DIR / f"{REVISION}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _cfg(url: str, monkeypatch) -> Config:
    from app.core.config import get_settings

    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    cfg = Config(str(VERSIONS_DIR.parent.parent / "alembic.ini"))
    cfg.set_main_option("script_location", str(VERSIONS_DIR.parent))
    return cfg


def test_0134_es_el_siguiente_de_0133() -> None:
    module = _module()
    assert module.revision == REVISION
    assert module.down_revision == PREVIOUS
    assert len(module.revision) <= 32


def test_0134_modelo_declara_las_mismas_columnas_e_indice() -> None:
    from app.models import Company

    table = Company.__table__
    assert {c.name for c in table.columns} >= NEW_COLUMNS
    assert table.c.delisted_at.nullable
    assert table.c.listing_note.nullable
    assert INDEX in {ix.name for ix in table.indexes}


def test_0134_upgrade_downgrade_upgrade_en_sqlite(tmp_path, monkeypatch) -> None:
    if not (VERSIONS_DIR / f"{PREVIOUS}.py").exists():
        pytest.skip("0133_watch_auto_analysis (piloto) aun no esta en versions/")
    url = f"sqlite:///{tmp_path}/mig0134.db"
    cfg = _cfg(url, monkeypatch)
    try:
        command.upgrade(cfg, "head")
        engine = sa.create_engine(url)
        inspector = sa.inspect(engine)
        columns = {c["name"] for c in inspector.get_columns(TABLE)}
        assert columns >= NEW_COLUMNS
        assert INDEX in {ix["name"] for ix in inspector.get_indexes(TABLE)}
        engine.dispose()

        command.downgrade(cfg, PREVIOUS)
        engine = sa.create_engine(url)
        inspector = sa.inspect(engine)
        assert not NEW_COLUMNS & {c["name"] for c in inspector.get_columns(TABLE)}
        assert INDEX not in {ix["name"] for ix in inspector.get_indexes(TABLE)}
        assert "ticker" in {c["name"] for c in inspector.get_columns(TABLE)}
        engine.dispose()

        command.upgrade(cfg, "head")
        engine = sa.create_engine(url)
        assert {c["name"] for c in sa.inspect(engine).get_columns(TABLE)} >= NEW_COLUMNS
        engine.dispose()
    finally:
        from app.core.config import get_settings

        get_settings.cache_clear()
