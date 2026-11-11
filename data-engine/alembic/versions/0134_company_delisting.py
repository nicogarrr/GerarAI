"""companies: delisted_at (+ indice parcial) y listing_note — baja probada.

Revision ID: 0134_company_delisting
Revises: 0133_watch_auto_analysis
Create Date: 2026-11-11T11:15:00.000Z

Decision del piloto (11-nov-2026, via main): N sesiones sin barra prueban
ausencia de datos/negociacion (suspension, proveedor caido), NO baja; ese
estado es derivado y reversible (listing_delisting.listing_data_state) y no
se persiste. ``delisted_at`` SOLO se fija con evidencia primaria de la baja
(comunicado del emisor/comprador/bolsa; listing_delisting.mark_delisted la
exige). Caso real: SES.TO — GFL cerro la adquisicion de Secure Energy
Services el 1-sep-2026; Yahoo seguia respondiendo 200 con el ultimo precio
congelado y 0 barras (11-nov-2026).

Aditiva y reversible, mismo patron que 0132: añade SOLO las columnas que
falten y las anota en `migration_added_columns`; el downgrade borra
unicamente lo anotado (una base arrancada con `create_all` del ORM llega
con las columnas ya puestas y sus datos sobreviven al downgrade). El indice
parcial ix_companies_delisted_at lo crea/borra esta revision siempre (es
solo de esta columna). Offline (--sql) no puede inspeccionar: emite el alta
de las 2 columnas, del registro y del indice tal cual.

La tabla `migration_added_columns` es infraestructura compartida (esta en
Base.metadata): el downgrade borra las filas de ESTA revision pero NUNCA la
tabla.
"""
import sqlalchemy as sa

from alembic import op

revision = "0134_company_delisting"
down_revision = "0133_watch_auto_analysis"
branch_labels = None
depends_on = None


_TABLE = "companies"
_LOG = "migration_added_columns"
_INDEX = "ix_companies_delisted_at"
_COLUMNS = (
    sa.Column("delisted_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("listing_note", sa.String(length=200), nullable=True),
)


def _is_offline() -> bool:
    import sqlalchemy.engine.mock

    return isinstance(op.get_bind(), sqlalchemy.engine.mock.MockConnection)


def _copy(column: sa.Column) -> sa.Column:
    return sa.Column(column.name, column.type, server_default=column.server_default, nullable=column.nullable)


def _create_log_table() -> None:
    op.create_table(
        _LOG,
        sa.Column("revision", sa.String(64), nullable=False),
        sa.Column("table_name", sa.String(128), nullable=False),
        sa.Column("column_name", sa.String(128), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("revision", "table_name", "column_name"),
    )


def _create_index() -> None:
    op.create_index(
        _INDEX,
        _TABLE,
        ["delisted_at"],
        postgresql_where=sa.text("delisted_at IS NOT NULL"),
    )


def upgrade() -> None:
    if _is_offline():
        _create_log_table()
        for column in _COLUMNS:
            op.add_column(_TABLE, _copy(column))
            op.execute(
                f"INSERT INTO {_LOG} (revision, table_name, column_name) VALUES ('{revision}', '{_TABLE}', '{column.name}')"
            )
        _create_index()
        return
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(_LOG):
        _create_log_table()
    existing = {col["name"] for col in sa.inspect(bind).get_columns(_TABLE)}
    for column in _COLUMNS:
        if column.name in existing:
            continue
        op.add_column(_TABLE, _copy(column))
        bind.execute(
            sa.text(
                f"INSERT INTO {_LOG} (revision, table_name, column_name)"
                " VALUES (:revision, :table_name, :column_name)"
            ),
            {"revision": revision, "table_name": _TABLE, "column_name": column.name},
        )
    if _INDEX not in {ix["name"] for ix in sa.inspect(bind).get_indexes(_TABLE)}:
        _create_index()


def downgrade() -> None:
    if _is_offline():
        op.drop_index(_INDEX, table_name=_TABLE)
        for column in reversed(_COLUMNS):
            op.drop_column(_TABLE, column.name)
        op.execute(f"DELETE FROM {_LOG} WHERE revision = '{revision}' AND table_name = '{_TABLE}'")
        return
    bind = op.get_bind()
    if _INDEX in {ix["name"] for ix in sa.inspect(bind).get_indexes(_TABLE)}:
        op.drop_index(_INDEX, table_name=_TABLE)
    if not sa.inspect(bind).has_table(_LOG):
        # Nada registrado: esta migracion no añadio columnas aqui (p. ej.
        # SQL offline aplicado a mano). No se toca ninguna columna.
        return
    rows = bind.execute(
        sa.text(f"SELECT column_name FROM {_LOG} WHERE revision = :revision AND table_name = :table"),
        {"revision": revision, "table": _TABLE},
    ).fetchall()
    owned = {row[0] for row in rows}
    existing = {col["name"] for col in sa.inspect(bind).get_columns(_TABLE)}
    for column in reversed(_COLUMNS):
        if column.name in owned and column.name in existing:
            op.drop_column(_TABLE, column.name)
    bind.execute(
        sa.text(f"DELETE FROM {_LOG} WHERE revision = :revision AND table_name = :table"),
        {"revision": revision, "table": _TABLE},
    )
    # La tabla de registro NO se borra: es compartida y esta en Base.metadata.
