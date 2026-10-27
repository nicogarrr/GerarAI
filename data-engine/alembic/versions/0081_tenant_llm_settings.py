"""tenant_llm_settings: proveedor, modelo y clave cifrada por tenant.

Aditiva y reversible. ``tenant_id`` es unico y su FK borra en cascada con el
tenant. La tabla puede existir ya en produccion porque ``init_db`` ejecuta
``create_all``: si el esquema reflejado coincide se adopta (solo creando los
indices que falten y anotandolo en ``migration_adoption_log``); si diverge, la
migracion falla sin tocar nada. Downgrade nunca destruye una tabla adoptada.
"""

import sqlalchemy as sa
import sqlalchemy.engine.mock

from alembic import op

revision = "0081_tenant_llm_settings"
down_revision = "0080_privacy_audit_events"
branch_labels = None
depends_on = None

_TABLE = "tenant_llm_settings"
_UNIQUE_NAME = "uq_tenant_llm_settings_tenant"
_INDEXES = {
    "ix_tenant_llm_settings_tenant_id": ("tenant_id",),
}
_FKS = {("tenant_id",): ("tenants", ("id",))}
_ADOPTION_TABLE = "migration_adoption_log"


def _expected_columns() -> list[tuple[str, sa.types.TypeEngine, bool]]:
    return [
        ("id", sa.Integer(), False),
        ("tenant_id", sa.Integer(), False),
        ("provider", sa.String(40), False),
        ("base_url", sa.String(500), True),
        ("model", sa.String(200), False),
        ("fallback_model", sa.String(200), True),
        ("reasoning_effort", sa.String(20), True),
        ("api_key_ciphertext", sa.Text(), True),
        ("api_key_last4", sa.String(8), True),
        ("key_version", sa.Integer(), False),
        ("enabled", sa.Boolean(), False),
        ("created_at", sa.DateTime(timezone=True), False),
        ("updated_at", sa.DateTime(timezone=True), False),
    ]


def _create_table() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=True),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("fallback_model", sa.String(200), nullable=True),
        sa.Column("reasoning_effort", sa.String(20), nullable=True),
        sa.Column("api_key_ciphertext", sa.Text(), nullable=True),
        sa.Column("api_key_last4", sa.String(8), nullable=True),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", name=_UNIQUE_NAME),
    )
    for name, cols in _INDEXES.items():
        op.create_index(name, _TABLE, list(cols))


def _validate_existing(inspector: sa.Inspector, dialect: sa.engine.Dialect) -> list[str]:
    divergences: list[str] = []
    reflected = {col["name"]: col for col in inspector.get_columns(_TABLE)}
    expected = _expected_columns()
    expected_names = {name for name, _, _ in expected}
    missing = expected_names - set(reflected)
    extra = set(reflected) - expected_names
    if missing:
        divergences.append(f"columnas ausentes: {sorted(missing)}")
    if extra:
        divergences.append(f"columnas de mas: {sorted(extra)}")
    for name, expected_type, expected_nullable in expected:
        if name not in reflected:
            continue
        column = reflected[name]
        reflected_type = column["type"].compile(dialect=dialect)
        wanted_type = expected_type.compile(dialect=dialect)
        if reflected_type != wanted_type:
            divergences.append(f"columna {name}: tipo {reflected_type} != {wanted_type}")
        if bool(column["nullable"]) != expected_nullable:
            divergences.append(f"columna {name}: nullable={column['nullable']} != {expected_nullable}")

    pk = inspector.get_pk_constraint(_TABLE) or {}
    if list(pk.get("constrained_columns") or []) != ["id"]:
        divergences.append(f"PK esperada (id), reflejada {pk.get('constrained_columns')}")

    reflected_fks = {
        (
            tuple(fk["constrained_columns"]),
            fk["referred_table"],
            tuple(fk["referred_columns"]),
            fk.get("options", {}).get("ondelete"),
        )
        for fk in inspector.get_foreign_keys(_TABLE)
    }
    wanted_fks = {
        (cols, ref_table, ref_cols, "CASCADE")
        for cols, (ref_table, ref_cols) in _FKS.items()
    }
    if reflected_fks != wanted_fks:
        divergences.append(f"FK esperadas {sorted(wanted_fks)!r}, reflejadas {sorted(reflected_fks)!r}")

    unique_ok = any(
        set(uc["column_names"]) == {"tenant_id"}
        for uc in inspector.get_unique_constraints(_TABLE)
    ) or any(
        ix["unique"] and set(ix["column_names"]) == {"tenant_id"}
        for ix in inspector.get_indexes(_TABLE)
    )
    if not unique_ok:
        divergences.append("falta restriccion UNIQUE sobre ['tenant_id']")

    existing_indexes = inspector.get_indexes(_TABLE)
    existing_names = {ix["name"] for ix in existing_indexes}
    for name, cols in _INDEXES.items():
        covered = any(
            not ix["unique"] and tuple(ix["column_names"]) == cols
            for ix in existing_indexes
        )
        if not covered and name in existing_names:
            divergences.append(f"indice {name} existe pero no cubre {list(cols)}: nombre ocupado")
    return divergences


def _ensure_indexes() -> list[str]:
    inspector = sa.inspect(op.get_bind())
    existing = inspector.get_indexes(_TABLE)
    existing_names = {ix["name"] for ix in existing}
    created: list[str] = []
    for name, cols in _INDEXES.items():
        covered = any(
            not ix["unique"] and tuple(ix["column_names"]) == cols
            for ix in existing
        )
        if not covered and name not in existing_names:
            op.create_index(name, _TABLE, list(cols))
            created.append(name)
    return created


def _record_adoption(created_indexes: list[str]) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(_ADOPTION_TABLE):
        op.create_table(
            _ADOPTION_TABLE,
            sa.Column("revision", sa.String(64), primary_key=True),
            sa.Column("table_name", sa.String(128), primary_key=True),
            sa.Column("created_indexes", sa.Text(), nullable=False),
            sa.Column(
                "adopted_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
    bind.execute(
        sa.text(
            f"INSERT INTO {_ADOPTION_TABLE} (revision, table_name, created_indexes)"
            " VALUES (:revision, :table_name, :created_indexes)"
        ),
        {
            "revision": revision,
            "table_name": _TABLE,
            "created_indexes": ",".join(created_indexes),
        },
    )


def _adopted_index_names(bind) -> str | None:
    inspector = sa.inspect(bind)
    if not inspector.has_table(_ADOPTION_TABLE):
        return None
    row = bind.execute(
        sa.text(
            f"SELECT created_indexes FROM {_ADOPTION_TABLE}"
            " WHERE revision = :revision AND table_name = :table_name"
        ),
        {"revision": revision, "table_name": _TABLE},
    ).fetchone()
    return None if row is None else str(row[0])


def _drop_adoption_marker(bind) -> None:
    bind.execute(
        sa.text(
            f"DELETE FROM {_ADOPTION_TABLE}"
            " WHERE revision = :revision AND table_name = :table_name"
        ),
        {"revision": revision, "table_name": _TABLE},
    )
    remaining = bind.execute(sa.text(f"SELECT COUNT(*) FROM {_ADOPTION_TABLE}")).scalar_one()
    if remaining == 0:
        op.drop_table(_ADOPTION_TABLE)


def _is_offline() -> bool:
    return isinstance(op.get_bind(), sa.engine.mock.MockConnection)


def _drop_table() -> None:
    existing: set[str] = set()
    if not _is_offline():
        inspector = sa.inspect(op.get_bind())
        if not inspector.has_table(_TABLE):
            return
        existing = {ix["name"] for ix in inspector.get_indexes(_TABLE) if ix["name"] is not None}
    for name in _INDEXES:
        if _is_offline() or name in existing:
            op.drop_index(name, table_name=_TABLE)
    op.drop_table(_TABLE)


def upgrade() -> None:
    if _is_offline():
        _create_table()
        return
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(_TABLE):
        _create_table()
        return
    bind = op.get_bind()
    divergences = _validate_existing(inspector, bind.dialect)
    if divergences:
        raise RuntimeError(
            "0081_tenant_llm_settings: la tabla tenant_llm_settings preexistente"
            " NO coincide con el esquema esperado; no se adopta ni se modifica"
            " nada. Divergencias: " + "; ".join(divergences)
        )
    _record_adoption(_ensure_indexes())


def downgrade() -> None:
    if _is_offline():
        _drop_table()
        return
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(_TABLE):
        return
    adopted = _adopted_index_names(bind)
    if adopted is None:
        _drop_table()
        return
    if adopted:
        existing = {ix["name"] for ix in inspector.get_indexes(_TABLE)}
        for name in adopted.split(","):
            if name in existing:
                op.drop_index(name, table_name=_TABLE)
    _drop_adoption_marker(bind)
