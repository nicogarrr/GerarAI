"""Revierte titulares genéricos de enlace de visor en news_events (aditiva)."""
import sqlalchemy as sa

from alembic import op

revision = "0073_news_generic_titles"
down_revision = "0072_news_junk_publisher_sources"
branch_labels = None
depends_on = None

# Copia fija del patrón de news_service.is_generic_headline al estado de esta
# migración: las migraciones no dependen del código vivo. Solo la frase
# exacta de enlace de visor: «archivo PDF» suelto puede ser un titular real.
_PAT = r"se\s+abre\s+en\s+una\s+nueva\s+ventana|opens?\s+in\s+a\s+new\s+window"


def upgrade() -> None:
    # 0071 rehidrató titles desde metadata.source_headline y algunos eran
    # texto de enlace del visor, no titulares («Comunicado de prensa del Q2
    # 2026, archivo PDF, (se abre en una nueva ventana)», visto en prod con
    # ZETA 19-oct-2026). (A) Donde el title quedó genérico se restaura el
    # título preservado por 0071; sin preservado se replica clip_words
    # (resumen completo si cabe en 180, si no corte en límite de palabra;
    # resumen vacío mantiene el título actual). (B) El source_headline
    # genérico se retira de metadata en todas las filas: original_headline()
    # lo prefiere y seguiría mostrando el texto de enlace en feed y alertas.
    # title_before_headline_rehydrate SE CONSERVA: el downgrade de 0071 lo
    # necesita en estas mismas filas. Los valores sobrescritos quedan
    # preservados para poder revertir esta migración.
    conn = op.get_bind()
    total = conn.execute(sa.text("SELECT count(*) FROM news_events WHERE title ~* :pat"), {"pat": _PAT}).scalar()
    print(f"0073: revirtiendo {total} titulares genéricos de enlace de visor")
    conn.execute(
        sa.text(
            """
            UPDATE news_events
            SET title = CASE
                    WHEN metadata->>'title_before_headline_rehydrate' IS NOT NULL
                        THEN metadata->>'title_before_headline_rehydrate'
                    WHEN btrim(summary) = ''
                        THEN title
                    WHEN length(btrim(summary)) <= 180
                        THEN btrim(summary)
                    ELSE coalesce(
                        nullif(regexp_replace(left(btrim(summary), 180), '\\s+\\S*$', ''), ''),
                        title)
                END,
                metadata = (metadata::jsonb || jsonb_build_object('title_before_generic_headline_fix', to_jsonb(title)))::json
            WHERE title ~* :pat
            """
        ),
        {"pat": _PAT},
    )
    junk_sources = conn.execute(
        sa.text("SELECT count(*) FROM news_events WHERE metadata->>'source_headline' ~* :pat"), {"pat": _PAT}
    ).scalar()
    print(f"0073: retirando {junk_sources} source_headline genéricos de metadata")
    conn.execute(
        sa.text(
            """
            UPDATE news_events
            SET metadata = ((metadata::jsonb || jsonb_build_object('generic_source_headline_removed', metadata->'source_headline'))
                            - 'source_headline')::json
            WHERE metadata->>'source_headline' ~* :pat
            """
        ),
        {"pat": _PAT},
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE news_events
            SET metadata = ((metadata::jsonb || jsonb_build_object('source_headline', metadata->'generic_source_headline_removed'))
                            - 'generic_source_headline_removed')::json
            WHERE metadata->'generic_source_headline_removed' IS NOT NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE news_events
            SET title = metadata->>'title_before_generic_headline_fix',
                metadata = (metadata::jsonb - 'title_before_generic_headline_fix')::json
            WHERE metadata->>'title_before_generic_headline_fix' IS NOT NULL
            """
        )
    )
