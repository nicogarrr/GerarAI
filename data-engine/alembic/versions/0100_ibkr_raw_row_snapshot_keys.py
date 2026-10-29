"""Claves indexadas de las filas crudas de IBKR (symbol, report_date).

Las filas crudas se guardan todas como prueba fiscal y nunca se borran; la
carga de posiciones leia la tabla entera en cada GET. Con estas dos columnas
(copias de payload.symbol y payload.reportDate/asOfDate) y su indice, la
conciliacion de costes lee solo el extracto del dia de cada posicion.

Upgrade: añade columnas e indice y las rellena desde payload, por lotes; el
payload no se toca. Downgrade: quita indice y columnas; ninguna fila se borra.
"""
from datetime import datetime

import sqlalchemy as sa

from alembic import op

revision = "0100_ibkr_raw_row_snapshot_keys"
down_revision = "0099_paper_trade_thesis_version"
branch_labels = None
depends_on = None

_TABLE = "ibkr_raw_rows"
_INDEX = "ix_ibkr_raw_rows_snapshot"
_BATCH = 1000


def _keys(payload):
    # Mismo parseo que app.models.entities.ibkr_raw_row_keys (congelado aqui).
    payload = payload or {}
    symbol = payload.get("symbol")
    symbol = symbol if isinstance(symbol, str) and 0 < len(symbol) <= 64 else None
    day = str(payload.get("reportDate") or payload.get("asOfDate") or "").split(";", 1)[0]
    try:
        report_date = datetime.strptime(day.replace("-", ""), "%Y%m%d").date()
    except ValueError:
        report_date = None
    return symbol, report_date


def _columns(bind) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns(_TABLE)}


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_TABLE):
        return
    if "report_date" not in _columns(bind):
        with op.batch_alter_table(_TABLE) as batch:
            batch.add_column(sa.Column("symbol", sa.String(64), nullable=True))
            batch.add_column(sa.Column("report_date", sa.Date(), nullable=True))
    if _INDEX not in {ix["name"] for ix in sa.inspect(bind).get_indexes(_TABLE)}:
        op.create_index(_INDEX, _TABLE, ["tenant_id", "report_date", "symbol"])
    table = sa.table(_TABLE, sa.column("id", sa.Integer()), sa.column("payload", sa.JSON()),
                     sa.column("symbol", sa.String(64)), sa.column("report_date", sa.Date()))
    last_id = 0
    while True:
        rows = bind.execute(
            sa.select(table.c.id, table.c.payload)
            .where(table.c.id > last_id, table.c.report_date.is_(None), table.c.symbol.is_(None))
            .order_by(table.c.id).limit(_BATCH)
        ).all()
        if not rows:
            break
        for row_id, payload in rows:
            symbol, report_date = _keys(payload)
            if symbol is not None or report_date is not None:
                bind.execute(table.update().where(table.c.id == row_id)
                             .values(symbol=symbol, report_date=report_date))
        last_id = rows[-1][0]


def downgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_TABLE):
        return
    if _INDEX in {ix["name"] for ix in sa.inspect(bind).get_indexes(_TABLE)}:
        op.drop_index(_INDEX, table_name=_TABLE)
    if "report_date" in _columns(bind):
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_column("report_date")
            batch.drop_column("symbol")
