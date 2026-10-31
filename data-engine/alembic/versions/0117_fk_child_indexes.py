"""Indices en 9 FKs hijas sin soporte: borrados de padre hacian Seq Scan.

Revision ID: 0117_fk_child_indexes
Revises: 0116_insider_filings_ticker
Create Date: 2026-10-31T03:08:00.000Z

MEDIDO: 9 constraints FK cuyas columnas no son prefijo de ningun indice
(catalysts.source_id, connector_states.company_id,
dca_signal_states.company_id, external_claims.company_id,
external_claims.source_id, financial_facts.source_id,
financial_statements.source_id, source_audits.thesis_version_id,
transcripts.source_id). 8 son ON DELETE SET NULL y 1 NO ACTION: al borrar
un documents/companies/thesis_versions, Postgres recorre la tabla hija
ENTERA por cada padre borrado. El borrado de cuenta (privacy
delete_account) borra documents en lote: multiplica el coste.

Los Dockerfiles ejecutan `alembic upgrade head` al arrancar: un CREATE
INDEX normal bloquearia escrituras durante el arranque. Por eso en
Postgres se usa CREATE INDEX CONCURRENTLY dentro de op.autocommit_block()
(fuera de la transaccion de migracion), que no bloquea escrituras, con
IF NOT EXISTS como guard. Un intento CONCURRENTLY interrumpido deja un
indice INVALID (pg_index.indisvalid = false) que IF NOT EXISTS saltaria:
se detecta y se recrea (DROP INDEX CONCURRENTLY + CREATE). En sqlite (no
soporta CONCURRENTLY) se crea con CREATE INDEX normal + guard por
inspector: mismo resultado, cadena de tests intacta.

Modelos alineados (index=True, mismos nombres): el rachet no crece.

NO desplegar en produccion hasta que Nico lo decida.
"""

import sqlalchemy as sa

from alembic import op

revision = "0117_fk_child_indexes"
down_revision = "0116_insider_filings_ticker"
branch_labels = None
depends_on = None

_INDICES = [
    ("ix_catalysts_source_id", "catalysts", ["source_id"]),
    ("ix_connector_states_company_id", "connector_states", ["company_id"]),
    ("ix_dca_signal_states_company_id", "dca_signal_states", ["company_id"]),
    ("ix_external_claims_company_id", "external_claims", ["company_id"]),
    ("ix_external_claims_source_id", "external_claims", ["source_id"]),
    ("ix_financial_facts_source_id", "financial_facts", ["source_id"]),
    ("ix_financial_statements_source_id", "financial_statements", ["source_id"]),
    ("ix_source_audits_thesis_version_id", "source_audits", ["thesis_version_id"]),
    ("ix_transcripts_source_id", "transcripts", ["source_id"]),
]

_NOMBRES = [n for n, _, _ in _INDICES]


def _invalidos(bind) -> set[str]:
    """Indices INVALID (intento CONCURRENTLY interrumpido) de nuestra lista."""
    rows = bind.execute(
        sa.text(
            "select c.relname from pg_class c "
            "join pg_index i on i.indexrelid = c.oid "
            "where not i.indisvalid and c.relname = any(:nombres)"
        ),
        {"nombres": _NOMBRES},
    ).all()
    return {r[0] for r in rows}


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            for nombre, tabla, columnas in _INDICES:
                if nombre in _invalidos(bind):
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
                )
        return
    inspector = sa.inspect(bind)
    existentes = {
        ix["name"]
        for tabla in {t for _, t, _ in _INDICES}
        for ix in inspector.get_indexes(tabla)
    }
    for nombre, tabla, columnas in _INDICES:
        if nombre not in existentes:
            op.create_index(nombre, tabla, columnas)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            for nombre, tabla, _ in _INDICES:
                op.drop_index(
                    nombre,
                    table_name=tabla,
                    postgresql_concurrently=True,
                    if_exists=True,
                )
        return
    inspector = sa.inspect(bind)
    existentes = {
        ix["name"]
        for tabla in {t for _, t, _ in _INDICES}
        for ix in inspector.get_indexes(tabla)
    }
    for nombre, tabla, _ in _INDICES:
        if nombre in existentes:
            op.drop_index(nombre, table_name=tabla)
