"""Indices del camino caliente de ingesta de documentos (dedup por URL/checksum).
Revision ID: 0131_documents_ingest_idx
Revises: 0130_analyst_notes
Create Date: 2026-11-05T02:30:00.000Z

Causa (leido de codigo, 5-nov-2026): cada process_document empieza con un
dedup por URL exacta en feed_ingestion_service.ingest_document_url
(WHERE source_url = :url AND tenant_id = :t LIMIT 1) y, tras descargar,
document_ingestion_service.ingest_bytes deduplica por
(company_id, source_url) y por (company_id, checksum). Ninguna de las dos
columnas (source_url, checksum) tenia indice: con el backlog de ingesta del
worker default cada documento reintentado hacia un seq scan de documents.
El piloto midio PG al 58,5 % CPU con la ingesta activa (5-nov-2026 02:22).

- ix_documents_tenant_source_url (tenant_id, source_url) parcial: cubre el
  dedup pre-descarga por URL y el de archive_url (company_id es filtro
  adicional sobre pocas filas por tenant+url).
- ix_documents_company_checksum (company_id, checksum) parcial: el dedup
  por contenido salta directo a la empresa.

Sin medida de laboratorio en el sandbox (no hay PG): la mejora la mide el
piloto en prod (CPU de PG antes/despues con la misma ingesta activa).
Mismo patron que 0119/0122: CONCURRENTLY en autocommit_block, IF NOT
EXISTS, INVALID propio por tabla recreado; sqlite con guard por inspector.
Modelos alineados (Index con postgresql_where, mismos nombres).
"""
import sqlalchemy as sa

from alembic import op

revision = "0131_documents_ingest_idx"
down_revision = "0130_analyst_notes"
branch_labels = None
depends_on = None

_INDICES = [
    (
        "ix_documents_tenant_source_url",
        "documents",
        ["tenant_id", "source_url"],
        "source_url IS NOT NULL",
    ),
    (
        "ix_documents_company_checksum",
        "documents",
        ["company_id", "checksum"],
        "checksum IS NOT NULL",
    ),
]


def _es_invalido(bind, nombre: str, tabla: str) -> bool:
    """True si EXISTE un indice INVALID llamado ``nombre`` sobre ESA tabla.

    Un intento CONCURRENTLY interrumpido deja el indice con indisvalid =
    false. Se comprueba por tabla (indrelid via search_path) y no solo por
    nombre: un indice homonimo de otro schema o de otra tabla no se toca.
    """
    return bool(
        bind.execute(
            sa.text(
                "select 1 from pg_index i "
                "join pg_class idx on idx.oid = i.indexrelid "
                "where i.indrelid = cast(:tabla as regclass) "
                "and idx.relname = :nombre and not i.indisvalid"
            ),
            {"tabla": tabla, "nombre": nombre},
        ).first()
    )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            for nombre, tabla, columnas, where in _INDICES:
                if _es_invalido(bind, nombre, tabla):
                    op.drop_index(
                        nombre,
                        table_name=tabla,
                        postgresql_concurrently=True,
                        if_exists=True,
                    )
                op.create_index(
                    nombre,
                    tabla,
                    columnas,
                    postgresql_concurrently=True,
                    if_not_exists=True,
                    postgresql_where=sa.text(where) if where else None,
                )
        return
    inspector = sa.inspect(bind)
    existentes = {ix["name"] for ix in inspector.get_indexes("documents")}
    for nombre, tabla, columnas, where in _INDICES:
        if nombre not in existentes:
            op.create_index(nombre, tabla, columnas)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            for nombre, tabla, _, _ in _INDICES:
                op.drop_index(
                    nombre,
                    table_name=tabla,
                    postgresql_concurrently=True,
                    if_exists=True,
                )
        return
    for nombre, tabla, _, _ in _INDICES:
        op.drop_index(nombre, table_name=tabla, if_exists=True)
