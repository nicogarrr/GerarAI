"""Columna ticker en knowledge_documents: enlaza un documento de la biblioteca a una empresa.

Aditiva, nullable e indexada. Un libro, una carta o una nota sobre una empresa
concreta puede llevar su ticker (normalizado: strip + upper) para aparecer en
la ficha ``/research/[ticker]``. Los documentos existentes quedan en NULL: no
se adivina el ticker a partir del titulo (un enlace inventado es peor que
ninguno); el usuario lo asigna desde la biblioteca.

Idempotente: si la columna ya existe (BD creada con ``create_all``), solo se
asegura el indice. El downgrade quita indice y columna.
"""
import sqlalchemy as sa

from alembic import op

revision = "0084_knowledge_document_ticker"
down_revision = "0082_financial_facts_filed"
branch_labels = None
depends_on = None

TABLE = "knowledge_documents"
COLUMN = "ticker"
INDEX = "ix_knowledge_documents_ticker"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns(TABLE)}
    if COLUMN not in columns:
        op.add_column(TABLE, sa.Column(COLUMN, sa.String(length=32), nullable=True))
    indexes = {index["name"] for index in inspector.get_indexes(TABLE)}
    if INDEX not in indexes:
        op.create_index(INDEX, TABLE, [COLUMN])


def downgrade() -> None:
    op.drop_index(INDEX, table_name=TABLE)
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_column(COLUMN)
