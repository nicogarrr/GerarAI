"""Corrige la fuente de news_events etiquetada con granjas de contenido (aditiva)."""
import sqlalchemy as sa

from alembic import op

revision = "0072_news_junk_publisher_sources"
down_revision = "0071_news_source_headline_titles"
branch_labels = None
depends_on = None

# Copia fija de JUNK_PUBLISHER_LABELS (ticker_news_lane.py) al estado de esta
# migración: las migraciones no deben depender del código vivo. Ampliar solo
# con evidencia de prod, como la lista original.
_JUNK = ("bitcoin foundation",)

_WHERE = "lower(btrim(source)) IN (" + ", ".join(f"'{label}'" for label in _JUNK) + ")"


def upgrade() -> None:
    # Migracion de DATOS con SQL solo-Postgres (btrim, ->>, jsonb, regexp_replace): en
    # otros dialectos (SQLite de tests/dev) no hay filas de prod que corregir y el SQL
    # no existe. Mismo patron que 0059/0062.
    if op.get_bind().dialect.name != "postgresql":
        return
    # La corrección de label_google (#1814) solo aplica a ingestas nuevas: las
    # filas ya guardadas seguían mostrando la granja como medio («Bitcoin
    # Foundation» para una noticia de JPM, visto en prod 19-oct-2026). Se
    # muestra el agregador, igual que en la ingesta nueva. La fuente anterior
    # queda en metadata.source_before_junk_label_fix para poder revertir.
    conn = op.get_bind()
    total = conn.execute(sa.text(f"SELECT count(*) FROM news_events WHERE {_WHERE}")).scalar()
    print(f"0072: corrigiendo {total} fuentes de granja de contenido a «Google News»")
    op.execute(
        f"""
        UPDATE news_events
        SET metadata = (metadata::jsonb || jsonb_build_object('source_before_junk_label_fix', to_jsonb(source)))::json,
            source = 'Google News'
        WHERE {_WHERE}
          AND source <> 'Google News'
        """
    )


def downgrade() -> None:
    # Migracion de DATOS con SQL solo-Postgres (btrim, ->>, jsonb, regexp_replace): en
    # otros dialectos (SQLite de tests/dev) no hay filas de prod que corregir y el SQL
    # no existe. Mismo patron que 0059/0062.
    if op.get_bind().dialect.name != "postgresql":
        return
    # Restaura la fuente anterior donde se preservó y limpia la marca.
    op.execute(
        """
        UPDATE news_events
        SET source = metadata->>'source_before_junk_label_fix',
            metadata = (metadata::jsonb - 'source_before_junk_label_fix')::json
        WHERE metadata->>'source_before_junk_label_fix' IS NOT NULL
        """
    )
