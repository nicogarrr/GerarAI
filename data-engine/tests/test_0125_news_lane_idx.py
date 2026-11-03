"""0125: indices parciales de carril (macro/gobierno) para el feed de noticias
y alineacion del predicado literal de la ruta con el del indice."""

from __future__ import annotations

import sqlalchemy as sa
from alembic.config import Config

from alembic import command
from tests.test_alembic_chain import VERSIONS_DIR

_NOMBRES = {"ix_news_lane_macro", "ix_news_lane_gobierno"}


def _sqlite_head(tmp_path, monkeypatch) -> sa.Engine:
    from app.core.config import get_settings

    url = f"sqlite:///{tmp_path}/mig0125.db"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    cfg = Config(str(VERSIONS_DIR.parent.parent / "alembic.ini"))
    cfg.set_main_option("script_location", str(VERSIONS_DIR.parent))
    command.upgrade(cfg, "head")
    get_settings.cache_clear()
    return sa.create_engine(url)


def test_0125_indices_existen_tras_upgrade_head_en_sqlite(tmp_path, monkeypatch) -> None:
    engine = _sqlite_head(tmp_path, monkeypatch)
    with engine.connect() as conn:
        nombres = {
            row[0]
            for row in conn.execute(
                sa.text("select name from sqlite_master where type='index'")
            )
        }
    assert nombres >= _NOMBRES


def test_0125_modelo_declara_los_mismos_indices() -> None:
    from app.models.entities import NewsEvent

    nombres = {ix.name for ix in NewsEvent.__table__.indexes}
    assert nombres >= _NOMBRES


def test_0125_predicado_de_la_ruta_es_literal_y_cubre_los_indexados() -> None:
    """El literal de la consulta tiene que casar con el del indice parcial:
    un parametro bound jamas matchea el predicado del indice."""
    from app.api.routes.news import _NEWS_LANES_INDEXADOS, _lane_predicado

    for lane in _NEWS_LANES_INDEXADOS:
        sql = str(_lane_predicado(lane).compile(compile_kwargs={"literal_binds": True}))
        assert sql == f"(news_events.metadata ->> 'news_lane') = '{lane}'"
