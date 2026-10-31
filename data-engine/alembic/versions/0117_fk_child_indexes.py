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
ENTERA para localizar las filas afectadas (Seq Scan por hija y por padre
borrado). El borrado de cuenta (privacy delete_account) borra documents en
lote: multiplica el coste.

Aditivo: 9 CREATE INDEX con los mismos nombres que autogenera el modelo
(index=True), guard por inspector, idempotente. Sin CONCURRENTLY: env.py
migra en una unica transaccion. Modelos alineados para que el rachet de
deriva no crezca.

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


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existentes = {
        ix["name"]
        for tabla in {t for _, t, _ in _INDICES}
        for ix in inspector.get_indexes(tabla)
    }
    for nombre, tabla, columnas in _INDICES:
        if nombre in existentes:
            continue
        op.create_index(nombre, tabla, columnas)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existentes = {
        ix["name"]
        for tabla in {t for _, t, _ in _INDICES}
        for ix in inspector.get_indexes(tabla)
    }
    for nombre, tabla, _ in _INDICES:
        if nombre not in existentes:
            continue
        op.drop_index(nombre, table_name=tabla)
