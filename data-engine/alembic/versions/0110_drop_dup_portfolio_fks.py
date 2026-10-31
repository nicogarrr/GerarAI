"""Eliminar claves foraneas duplicadas en tablas de cartera.

Revision ID: 0110_drop_dup_portfolio_fks
Revises: 0109_add_audit_log_table
Create Date: 2026-10-31T00:30:00.000Z

0107_add_fk_cascades creo una SEGUNDA FK con ON DELETE CASCADE sobre
portfolio_id sin retirar la FK original (sin cascade) que ya existia en
positions, transactions, portfolio_daily_snapshots, position_daily_snapshots,
cash_daily_snapshots, tax_reports e investment_plans. Medido sobre una BD
limpia migrada desde base en PostgreSQL 16: cada tabla quedo con dos FKs
equivalentes sobre la misma columna (la antigua NO ACTION y la nueva
CASCADE), redundantes y divergentes con app.models, que declara una unica
FK con ondelete="CASCADE".

Esta migracion retira la FK antigua (la sin cascade) y deja la *_cascade,
de modo que instalaciones nuevas y BDs ya migradas convergen al esquema
declarado en los modelos. El downgrade recrea las FKs antiguas.

Fulfills: VAL-DB-001 (limpieza de la deuda dejada por VAL-SEC-007)
"""

import sqlalchemy as sa

from alembic import op

revision = "0110_drop_dup_portfolio_fks"
down_revision = "0109_add_audit_log_table"
branch_labels = None
depends_on = None

# (tabla, FK antigua sin cascade que sobra, FK cascade que se queda)
_FKS_DUPLICADAS = [
    ("positions", "fk_positions_portfolio_id", "fk_positions_portfolio_id_cascade"),
    ("transactions", "fk_transactions_portfolio_id", "fk_transactions_portfolio_id_cascade"),
    (
        "portfolio_daily_snapshots",
        "portfolio_daily_snapshots_portfolio_id_fkey",
        "fk_portfolio_daily_snapshots_portfolio_id_cascade",
    ),
    (
        "position_daily_snapshots",
        "position_daily_snapshots_portfolio_id_fkey",
        "fk_position_daily_snapshots_portfolio_id_cascade",
    ),
    (
        "cash_daily_snapshots",
        "cash_daily_snapshots_portfolio_id_fkey",
        "fk_cash_daily_snapshots_portfolio_id_cascade",
    ),
    ("tax_reports", "tax_reports_portfolio_id_fkey", "fk_tax_reports_portfolio_id_cascade"),
    (
        "investment_plans",
        "investment_plans_portfolio_id_fkey",
        "fk_investment_plans_portfolio_id_cascade",
    ),
]


def upgrade() -> None:
    # Solo se retira si existe con ese nombre: PostgreSQL nombro las FKs al
    # crearlas (explicita fk_* o sufijo _fkey por defecto), pero en SQLite las
    # FKs sin nombre de las migraciones antiguas quedan anonimas y batch no
    # puede retirarlas; ahi no hay duplicado retirable y no se toca nada.
    inspector = sa.inspect(op.get_bind())
    for tabla, fk_antigua, _fk_cascade in _FKS_DUPLICADAS:
        nombres = {fk["name"] for fk in inspector.get_foreign_keys(tabla) if fk.get("name")}
        if fk_antigua not in nombres:
            continue
        with op.batch_alter_table(tabla, schema=None) as batch_op:
            batch_op.drop_constraint(fk_antigua, type_="foreignkey")


def downgrade() -> None:
    for tabla, fk_antigua, _fk_cascade in _FKS_DUPLICADAS:
        with op.batch_alter_table(tabla, schema=None) as batch_op:
            batch_op.create_foreign_key(
                fk_antigua,
                "portfolios",
                ["portfolio_id"],
                ["id"],
            )
