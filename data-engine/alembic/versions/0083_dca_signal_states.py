"""dca_signal_states + dca_alert_overrides: senales DCA por niveles.

Aditiva y reversible. ``dca_signal_states`` guarda el ultimo veredicto DCA por
(tenant, simbolo) de watchlist + cartera y la memoria del ultimo aviso;
``dca_alert_overrides`` el nivel minimo de aviso por ticker (sin fila = global,
0 = avisos apagados). Sin backfill: la primera evaluacion las rellena.

Misma situacion que 0079/0080: el arranque del backend ejecuta `create_all`
del ORM en `init_db`, asi que las tablas pueden existir antes de que Alembic
llegue aqui. Si existen se validan las columnas (nombre, tipo y nullability)
contra la definicion congelada; cualquier divergencia FALLA sin tocar nada.
Si coinciden se adoptan: solo se crean los indices que falten y se anota la
adopcion en `migration_adoption_log`, para que downgrade no borre una tabla
que esta migracion no creo.
"""

import sqlalchemy as sa
import sqlalchemy.engine.mock

from alembic import op

revision = "0083_dca_signal_states"
down_revision = "0082_financial_facts_filed"
branch_labels = None
depends_on = None

_ADOPTION_TABLE = "migration_adoption_log"
_STATES = "dca_signal_states"
_OVERRIDES = "dca_alert_overrides"


def _state_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=True),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=True),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("previous_level", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("period", sa.String(length=7), nullable=False),
        sa.Column("signal_date", sa.Date(), nullable=False),
        sa.Column("close", sa.Numeric(20, 6), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("level_prices", sa.JSON(), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("hit_rates", sa.JSON(), nullable=True),
        sa.Column("params_version", sa.String(length=40), nullable=False),
        sa.Column("last_alerted_level", sa.Integer(), nullable=True),
        sa.Column("last_alerted_period", sa.String(length=7), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data_source", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def _override_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=True),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("min_level", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


_SPECS = {
    _STATES: {
        "columns": _state_columns,
        "fks": [("tenant_id", "tenants"), ("company_id", "companies")],
        "unique": ("uq_dca_signal_state_tenant_symbol", ("tenant_id", "symbol")),
        "indexes": {
            "ix_dca_signal_states_tenant_id": ("tenant_id",),
            "ix_dca_signal_states_symbol": ("symbol",),
        },
    },
    _OVERRIDES: {
        "columns": _override_columns,
        "fks": [("tenant_id", "tenants")],
        "unique": ("uq_dca_alert_override_tenant_symbol", ("tenant_id", "symbol")),
        "indexes": {
            "ix_dca_alert_overrides_tenant_id": ("tenant_id",),
            "ix_dca_alert_overrides_symbol": ("symbol",),
        },
    },
}


def _is_offline() -> bool:
    return isinstance(op.get_bind(), sa.engine.mock.MockConnection)


def _create(table: str) -> None:
    spec = _SPECS[table]
    unique_name, unique_cols = spec["unique"]
    op.create_table(
        table,
        *spec["columns"](),
        *[sa.ForeignKeyConstraint([col], [f"{ref}.id"]) for col, ref in spec["fks"]],
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(*unique_cols, name=unique_name),
    )
    for name, cols in spec["indexes"].items():
        op.create_index(name, table, list(cols))


def _divergences(inspector: sa.Inspector, dialect: sa.engine.Dialect, table: str) -> list[str]:
    spec = _SPECS[table]
    reflected = {col["name"]: col for col in inspector.get_columns(table)}
    expected = {col.name: col for col in spec["columns"]()}
    out: list[str] = []
    missing = set(expected) - set(reflected)
    extra = set(reflected) - set(expected)
    if missing:
        out.append(f"{table}: columnas ausentes {sorted(missing)}")
    if extra:
        out.append(f"{table}: columnas de mas {sorted(extra)}")
    for name, column in expected.items():
        if name not in reflected:
            continue
        got = reflected[name]["type"].compile(dialect=dialect)
        want = column.type.compile(dialect=dialect)
        if got != want:
            out.append(f"{table}.{name}: tipo {got} != {want}")
        if bool(reflected[name]["nullable"]) != bool(column.nullable):
            out.append(f"{table}.{name}: nullable={reflected[name]['nullable']} != {column.nullable}")
    unique_cols = tuple(spec["unique"][1])
    uniques = [tuple(u["column_names"]) for u in inspector.get_unique_constraints(table)]
    unique_indexes = [tuple(ix["column_names"]) for ix in inspector.get_indexes(table) if ix["unique"]]
    if unique_cols not in uniques and unique_cols not in unique_indexes:
        out.append(f"{table}: falta UNIQUE {list(unique_cols)}")
    return out


def _record_adoption(table: str, created: list[str]) -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_ADOPTION_TABLE):
        op.create_table(
            _ADOPTION_TABLE,
            sa.Column("revision", sa.String(64), primary_key=True),
            sa.Column("table_name", sa.String(128), primary_key=True),
            sa.Column("created_indexes", sa.Text(), nullable=False),
            sa.Column("adopted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
    bind.execute(
        sa.text(
            f"INSERT INTO {_ADOPTION_TABLE} (revision, table_name, created_indexes)"
            " VALUES (:revision, :table_name, :created_indexes)"
        ),
        {"revision": revision, "table_name": table, "created_indexes": ",".join(created)},
    )


def upgrade() -> None:
    if _is_offline():
        for table in _SPECS:
            _create(table)
        return
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    preexisting = [table for table in _SPECS if inspector.has_table(table)]
    problems: list[str] = []
    for table in preexisting:
        problems += _divergences(inspector, bind.dialect, table)
    if problems:
        raise RuntimeError(
            "0083_dca_signal_states: tabla preexistente que NO coincide con el esquema"
            " esperado; no se adopta ni se modifica nada. Reconciliar manualmente."
            " Divergencias: " + "; ".join(problems)
        )
    for table in _SPECS:
        if table not in preexisting:
            _create(table)
            continue
        existing = sa.inspect(bind).get_indexes(table)
        names = {ix["name"] for ix in existing}
        created: list[str] = []
        for name, cols in _SPECS[table]["indexes"].items():
            covered = any(tuple(ix["column_names"]) == cols for ix in existing)
            if not covered and name not in names:
                op.create_index(name, table, list(cols))
                created.append(name)
        _record_adoption(table, created)


def downgrade() -> None:
    if _is_offline():
        for table in reversed(list(_SPECS)):
            for name in _SPECS[table]["indexes"]:
                op.drop_index(name, table_name=table)
            op.drop_table(table)
        return
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    adopted: dict[str, list[str]] = {}
    if inspector.has_table(_ADOPTION_TABLE):
        rows = bind.execute(
            sa.text(f"SELECT table_name, created_indexes FROM {_ADOPTION_TABLE} WHERE revision = :revision"),
            {"revision": revision},
        ).fetchall()
        adopted = {str(row[0]): [tag for tag in str(row[1]).split(",") if tag] for row in rows}
    for table in reversed(list(_SPECS)):
        if not inspector.has_table(table):
            continue
        existing = {ix["name"] for ix in inspector.get_indexes(table)}
        if table in adopted:
            # Tabla adoptada: NUNCA se borra; solo los indices que anadio la adopcion.
            for name in adopted[table]:
                if name in existing:
                    op.drop_index(name, table_name=table)
            continue
        for name in _SPECS[table]["indexes"]:
            if name in existing:
                op.drop_index(name, table_name=table)
        op.drop_table(table)
    if adopted:
        bind.execute(
            sa.text(f"DELETE FROM {_ADOPTION_TABLE} WHERE revision = :revision"),
            {"revision": revision},
        )
        remaining = bind.execute(sa.text(f"SELECT COUNT(*) FROM {_ADOPTION_TABLE}")).scalar_one()
        if remaining == 0:
            op.drop_table(_ADOPTION_TABLE)
