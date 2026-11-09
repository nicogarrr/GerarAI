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

PROPIEDAD REGISTRADA, no inferida: una base arrancada con `create_all` del
ORM llega aqui con las 4 columnas ya puestas (0083 las adopta con la tabla).
Esta migracion añade SOLO las que falten y anota en `migration_added_columns`
exactamente las que añadio; el downgrade borra unicamente lo anotado, asi
las columnas que venian del ORM (y sus datos) sobreviven al downgrade.
Offline (--sql) no puede inspeccionar: emite el alta de las 4 y del registro
tal cual, coherente con una cadena desde cero (0083 crea la tabla sin ellas).

La tabla `migration_added_columns` es infraestructura compartida (esta en
Base.metadata: la crean create_all y las migraciones, la que llegue primero)
y la escribiran futuras revisiones: el downgrade borra las filas de ESTA
revision pero NUNCA la tabla - hacerlo destruiria registros ajenos y, en
bases ORM, una tabla que el propio create_all repone.
"""
import sqlalchemy as sa

from alembic import op

revision = "0132_dca_state_live_price"
down_revision = "0131_documents_ingest_idx"
branch_labels = None
depends_on = None


_TABLE = "dca_signal_states"
_LOG = "migration_added_columns"
_LIVE_COLUMNS = (
    sa.Column("close_kind", sa.String(length=8), server_default="close", nullable=False),
    sa.Column("live_price", sa.Numeric(20, 6), nullable=True),
    sa.Column("live_session", sa.String(length=8), nullable=True),
    sa.Column("live_at", sa.DateTime(timezone=True), nullable=True),
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


def upgrade() -> None:
    if _is_offline():
        # Sin inspeccion: cadena desde cero (0083 crea la tabla sin estas
        # columnas), asi que el alta de las 4 y del registro es exacta.
        _create_log_table()
        for column in _LIVE_COLUMNS:
            op.add_column(_TABLE, _copy(column))
            op.execute(
                f"INSERT INTO {_LOG} (revision, table_name, column_name) VALUES ('{revision}', '{_TABLE}', '{column.name}')"
            )
        return
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(_LOG):
        _create_log_table()
    existing = {col["name"] for col in sa.inspect(bind).get_columns(_TABLE)}
    for column in _LIVE_COLUMNS:
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


def downgrade() -> None:
    if _is_offline():
        for column in reversed(_LIVE_COLUMNS):
            op.drop_column(_TABLE, column.name)
        op.execute(f"DELETE FROM {_LOG} WHERE revision = '{revision}' AND table_name = '{_TABLE}'")
        return
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_LOG):
        # Nada registrado: esta migracion no añadio nada aqui (p. ej. SQL
        # offline aplicado a mano). No se toca ninguna columna.
        return
    rows = bind.execute(
        sa.text(f"SELECT column_name FROM {_LOG} WHERE revision = :revision AND table_name = :table"),
        {"revision": revision, "table": _TABLE},
    ).fetchall()
    owned = {row[0] for row in rows}
    existing = {col["name"] for col in sa.inspect(bind).get_columns(_TABLE)}
    for column in reversed(_LIVE_COLUMNS):
        if column.name in owned and column.name in existing:
            op.drop_column(_TABLE, column.name)
    bind.execute(
        sa.text(f"DELETE FROM {_LOG} WHERE revision = :revision AND table_name = :table"),
        {"revision": revision, "table": _TABLE},
    )
    # La tabla de registro NO se borra: es compartida y esta en Base.metadata.
