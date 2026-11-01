"""Indice aditivo para /api/insider/filings: filtra por issuer_ticker.

Revision ID: 0116_insider_filings_ticker
Revises: 0115_tenant_nullable
Create Date: 2026-10-31T02:26:00.000Z

MEDIDO: insider_filings solo tenia indice por issuer_cik (y los de
tenant_id/accesion_number), pero GET /api/insider/filings lista y cuenta por
issuer_ticker ordenando por filing_date DESC (insider.py). Sin indice, cada
peticion es Seq Scan sobre todos los filings del tenant.

Aditivo: un CREATE INDEX, sin reescrituras ni cambios de datos. Guard por
inspector: idempotente. La migracion corre en una unica transaccion (env.py),
asi que no se usa CONCURRENTLY; la tabla es pequena (una fila por accession
number SEC ingerido).

NO desplegar en produccion hasta que Nico lo decida.
"""

import sqlalchemy as sa

from alembic import op

revision = "0116_insider_filings_ticker"
down_revision = "0115_tenant_nullable"
branch_labels = None
depends_on = None

_INDICE = "ix_insider_filings_tenant_ticker_date"


def _existe_indice(bind) -> bool:
    return any(
        ix["name"] == _INDICE
        for ix in sa.inspect(bind).get_indexes("insider_filings")
    )


def upgrade() -> None:
    bind = op.get_bind()
    if _existe_indice(bind):
        return
    op.create_index(
        _INDICE,
        "insider_filings",
        ["tenant_id", "issuer_ticker", "filing_date"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if not _existe_indice(bind):
        return
    op.drop_index(_INDICE, table_name="insider_filings")
