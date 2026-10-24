"""Rehidrata el titular de news_events desde metadata.source_headline (aditiva)."""
import sqlalchemy as sa

from alembic import op

revision = "0071_news_source_headline_titles"
down_revision = "0070_calendar_feed_tokens"
branch_labels = None
depends_on = None

_WHERE = (
    "metadata->>'source_headline' IS NOT NULL "
    "AND btrim(metadata->>'source_headline') <> '' "
    "AND title <> metadata->>'source_headline'"
)


def upgrade() -> None:
    # Migracion de DATOS con SQL solo-Postgres (btrim, ->>, jsonb, regexp_replace): en
    # otros dialectos (SQLite de tests/dev) no hay filas de prod que corregir y el SQL
    # no existe. Mismo patron que 0059/0062.
    if op.get_bind().dialect.name != "postgresql":
        return
    # El titular íntegro del medio ya estaba guardado en metadata.source_headline
    # mientras title quedaba como prefijo del resumen cortado a media frase
    # («…rivals scrambling, and one»). Se restaura el del medio: no se inventa
    # texto, solo se copia lo que la fuente ya trajo. El título anterior queda
    # preservado en metadata.title_before_headline_rehydrate para poder revertir.
    conn = op.get_bind()
    total = conn.execute(sa.text(f"SELECT count(*) FROM news_events WHERE {_WHERE}")).scalar()
    print(f"0071: rehidratando {total} titulares desde metadata.source_headline")
    op.execute(
        f"""
        UPDATE news_events
        SET metadata = (metadata::jsonb || jsonb_build_object('title_before_headline_rehydrate', to_jsonb(title)))::json,
            title = metadata->>'source_headline'
        WHERE {_WHERE}
        """
    )


def downgrade() -> None:
    # Migracion de DATOS con SQL solo-Postgres (btrim, ->>, jsonb, regexp_replace): en
    # otros dialectos (SQLite de tests/dev) no hay filas de prod que corregir y el SQL
    # no existe. Mismo patron que 0059/0062.
    if op.get_bind().dialect.name != "postgresql":
        return
    # Restaura el título anterior donde se preservó y limpia la marca.
    op.execute(
        """
        UPDATE news_events
        SET title = metadata->>'title_before_headline_rehydrate',
            metadata = (metadata::jsonb - 'title_before_headline_rehydrate')::json
        WHERE metadata->>'title_before_headline_rehydrate' IS NOT NULL
        """
    )
