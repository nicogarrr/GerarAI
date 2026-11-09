"""dca_signal_states: etiqueta del precio actual (premercado/sesion/post).

Revision ID: 0132_dca_state_live_price
Revises: 0131_documents_ingest_idx
Create Date: 2026-11-09T13:30:00.000Z

El nivel DCA oficial puede calcularse con el precio actual en el periodo en
formacion. Invariante: ``close`` y ``signal_date`` siguen siendo SIEMPRE el
cierre asentado; el precio actual nunca se persiste como cierre. Cuatro
columnas nuevas, todas con valor por defecto seguro para las filas existentes:

- close_kind: 'close' (nivel solo con cierres) | 'live' (nivel del periodo en
  formacion calculado con el precio actual etiquetado en live_*).
- live_price / live_session ('pre'|'regular'|'post') / live_at: el precio
  actual usado, su sesion y su hora; NULL cuando el nivel es solo de cierres
  (se limpian en cada evaluacion sin precio actual usable).
"""
import sqlalchemy as sa

from alembic import op

revision = "0132_dca_state_live_price"
down_revision = "0131_documents_ingest_idx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "dca_signal_states",
        sa.Column("close_kind", sa.String(length=8), server_default="close", nullable=False),
    )
    op.add_column("dca_signal_states", sa.Column("live_price", sa.Numeric(20, 6), nullable=True))
    op.add_column("dca_signal_states", sa.Column("live_session", sa.String(length=8), nullable=True))
    op.add_column("dca_signal_states", sa.Column("live_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("dca_signal_states", "live_at")
    op.drop_column("dca_signal_states", "live_session")
    op.drop_column("dca_signal_states", "live_price")
    op.drop_column("dca_signal_states", "close_kind")
