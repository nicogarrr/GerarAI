"""Add foreign key ON DELETE CASCADE rules for portfolio relationships.

Revision ID: 0107_add_fk_cascades
Revises: 0106_add_critical_indexes
Create Date: 2026-10-30T20:30:00.000Z

Adds ON DELETE CASCADE behavior to portfolio foreign keys:
- positions.portfolio_id -> portfolios.id ON DELETE CASCADE
- transactions.portfolio_id -> portfolios.id ON DELETE CASCADE
- portfolio_daily_snapshots.portfolio_id -> portfolios.id ON DELETE CASCADE
- position_daily_snapshots.portfolio_id -> portfolios.id ON DELETE CASCADE
- cash_daily_snapshots.portfolio_id -> portfolios.id ON DELETE CASCADE
- tax_reports.portfolio_id -> portfolios.id ON DELETE CASCADE
- investment_plans.portfolio_id -> portfolios.id ON DELETE CASCADE

Fulfills: VAL-SEC-007, VAL-DB-001
"""

from alembic import op

revision = "0107_add_fk_cascades"
down_revision = "0106_add_critical_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # positions
    with op.batch_alter_table("positions", schema=None) as batch_op:
        batch_op.create_foreign_key(
            "fk_positions_portfolio_id_cascade",
            "portfolios",
            ["portfolio_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # transactions
    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.create_foreign_key(
            "fk_transactions_portfolio_id_cascade",
            "portfolios",
            ["portfolio_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # portfolio_daily_snapshots
    with op.batch_alter_table("portfolio_daily_snapshots", schema=None) as batch_op:
        batch_op.create_foreign_key(
            "fk_portfolio_daily_snapshots_portfolio_id_cascade",
            "portfolios",
            ["portfolio_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # position_daily_snapshots
    with op.batch_alter_table("position_daily_snapshots", schema=None) as batch_op:
        batch_op.create_foreign_key(
            "fk_position_daily_snapshots_portfolio_id_cascade",
            "portfolios",
            ["portfolio_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # cash_daily_snapshots
    with op.batch_alter_table("cash_daily_snapshots", schema=None) as batch_op:
        batch_op.create_foreign_key(
            "fk_cash_daily_snapshots_portfolio_id_cascade",
            "portfolios",
            ["portfolio_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # tax_reports
    with op.batch_alter_table("tax_reports", schema=None) as batch_op:
        batch_op.create_foreign_key(
            "fk_tax_reports_portfolio_id_cascade",
            "portfolios",
            ["portfolio_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # investment_plans
    with op.batch_alter_table("investment_plans", schema=None) as batch_op:
        batch_op.create_foreign_key(
            "fk_investment_plans_portfolio_id_cascade",
            "portfolios",
            ["portfolio_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    # Retira cada FK solo si sigue existiendo con ese nombre. En SQLite los
    # rebuilds de batch posteriores (0108 crea CHECKs sobre transactions y
    # positions) reconstruyen la tabla desde la reflexion y los nombres de
    # las FKs se pierden (PRAGMA foreign_key_list no los devuelve), asi que
    # un drop por nombre reventaria el downgrade. En PostgreSQL los nombres
    # persisten y la retirada es exacta, como antes.
    import sqlalchemy as sa

    inspector = sa.inspect(op.get_bind())
    pares = [
        ("investment_plans", "fk_investment_plans_portfolio_id_cascade"),
        ("tax_reports", "fk_tax_reports_portfolio_id_cascade"),
        ("cash_daily_snapshots", "fk_cash_daily_snapshots_portfolio_id_cascade"),
        ("position_daily_snapshots", "fk_position_daily_snapshots_portfolio_id_cascade"),
        ("portfolio_daily_snapshots", "fk_portfolio_daily_snapshots_portfolio_id_cascade"),
        ("transactions", "fk_transactions_portfolio_id_cascade"),
        ("positions", "fk_positions_portfolio_id_cascade"),
    ]
    for tabla, fk in pares:
        nombres = {f["name"] for f in inspector.get_foreign_keys(tabla) if f.get("name")}
        if fk not in nombres:
            continue
        with op.batch_alter_table(tabla, schema=None) as batch_op:
            batch_op.drop_constraint(fk, type_="foreignkey")
