"""Añadir índices críticos para optimizar consultas de alto tráfico.

Índices compuestos en tablas principales para mejorar el rendimiento:
- dca_evaluation_runs: índice por tenant, status y fecha (recent runs)
- portfolio_daily_snapshots: índice por tenant y fecha (cross-portfolio charts)
- position_daily_snapshots: índice por company/tenant y fecha (time-series)
- documents: índice por company/tenant y fecha publicación (recent docs)
- insider_transactions: índice por tenant y fecha (recent insider activity)
- cash_balances: índice por tenant y currency (multi-currency queries)
- fx_rates: índice por tenant y fecha (recent FX rates)
- earnings_dates: índice por ticker y fecha (upcoming earnings)

Nota: Algunos índices ya existen en el esquema actual y se omiten.
Los downgrade eliminan los índices creados.
"""
import sqlalchemy as sa

from alembic import op

revision = "0106_add_critical_indexes"
down_revision = "0105_optimize_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # dca_evaluation_runs: tenant + status + started_at DESC for recent runs by status
    op.create_index(
        "ix_dca_evaluation_runs_tenant_status_started",
        "dca_evaluation_runs",
        ["tenant_id", "status", sa.text("started_at DESC")],
        unique=False,
    )

    # portfolio_daily_snapshots: tenant + snapshot_date DESC for cross-portfolio charts
    op.create_index(
        "ix_portfolio_snapshots_tenant_date",
        "portfolio_daily_snapshots",
        ["tenant_id", sa.text("snapshot_date DESC")],
        unique=False,
    )

    # position_daily_snapshots: company + snapshot_date DESC for time-series queries
    op.create_index(
        "ix_position_snapshots_company_date",
        "position_daily_snapshots",
        ["company_id", sa.text("snapshot_date DESC")],
        unique=False,
    )

    # position_daily_snapshots: tenant + snapshot_date DESC for tenant-wide time-series
    op.create_index(
        "ix_position_snapshots_tenant_date",
        "position_daily_snapshots",
        ["tenant_id", sa.text("snapshot_date DESC")],
        unique=False,
    )

    # documents: company + published_at DESC for recent company documents
    op.create_index(
        "ix_documents_company_published",
        "documents",
        ["company_id", sa.text("published_at DESC")],
        unique=False,
    )

    # documents: tenant + published_at DESC for recent tenant documents
    op.create_index(
        "ix_documents_tenant_published",
        "documents",
        ["tenant_id", sa.text("published_at DESC")],
        unique=False,
    )

    # insider_transactions: tenant + tx_date DESC for recent insider activity
    op.create_index(
        "ix_insider_transactions_tenant_date",
        "insider_transactions",
        ["tenant_id", sa.text("tx_date DESC")],
        unique=False,
    )

    # insider_transactions: issuer_ticker + tx_date DESC (improve existing index)
    op.create_index(
        "ix_insider_transactions_ticker_date_desc",
        "insider_transactions",
        ["issuer_ticker", sa.text("tx_date DESC")],
        unique=False,
    )

    # cash_balances: tenant + currency for multi-currency balance queries
    op.create_index(
        "ix_cash_balances_tenant_currency",
        "cash_balances",
        ["tenant_id", "currency"],
        unique=False,
    )

    # fx_rates: tenant + rate_date DESC for recent FX rates
    op.create_index(
        "ix_fx_rates_tenant_date",
        "fx_rates",
        ["tenant_id", sa.text("rate_date DESC")],
        unique=False,
    )

    # earnings_dates: ticker + event_date DESC for upcoming earnings
    op.create_index(
        "ix_earnings_dates_ticker_date_desc",
        "earnings_dates",
        ["ticker", sa.text("event_date DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_earnings_dates_ticker_date_desc", table_name="earnings_dates")
    op.drop_index("ix_fx_rates_tenant_date", table_name="fx_rates")
    op.drop_index("ix_cash_balances_tenant_currency", table_name="cash_balances")
    op.drop_index("ix_insider_transactions_ticker_date_desc", table_name="insider_transactions")
    op.drop_index("ix_insider_transactions_tenant_date", table_name="insider_transactions")
    op.drop_index("ix_documents_tenant_published", table_name="documents")
    op.drop_index("ix_documents_company_published", table_name="documents")
    op.drop_index("ix_position_snapshots_tenant_date", table_name="position_daily_snapshots")
    op.drop_index("ix_position_snapshots_company_date", table_name="position_daily_snapshots")
    op.drop_index("ix_portfolio_snapshots_tenant_date", table_name="portfolio_daily_snapshots")
    op.drop_index("ix_dca_evaluation_runs_tenant_status_started", table_name="dca_evaluation_runs")
