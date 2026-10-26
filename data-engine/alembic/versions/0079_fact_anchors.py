"""Tabla fact_anchors: anclas de dato con provenance verificada (aditiva).

Reproduce exactamente `FactAnchor` (entities.py): columnas, nullability, los
tres indices implicados/declarados y el unique tenant-scoped. Las FK van sin
ON DELETE, igual que el mixin `TenantOwnedMixin` y el propio modelo. El
append-only se garantiza en el ORM (eventos before_update/before_delete y DML
masivo), no con triggers de base de datos.

Adopcion no destructiva: en prod la tabla puede existir ya (el arranque del
backend ejecuta `create_all` del ORM en `init_db`, que crea las tablas
del ORM aunque Alembic no haya llegado a esta revision). Si la tabla existe:

- se valida el esquema completo reflejado (las 16 columnas con tipo y
  nullability, la PK, las dos FK, el unique de 6 columnas) contra la
  definicion congelada de ESTA migracion, no solo el nombre de la tabla;
- los indices se aceptan por columnas, no solo por nombre; solo se crean los
  que falten, y se registra cuales creo esta migracion;
- si el esquema diverge en algo, la migracion FALLA con la lista de
  divergencias y sin tocar la tabla: el origen de la tabla preexistente no
  esta confirmado y adoptar un esquema distinto en silencio esconderia el
  problema. La reconciliacion manual es la salida honesta.

La adopcion se anota en la tabla de registro `migration_adoption_log` para
que `downgrade` sea simetrico: si esta migracion creo la tabla, downgrade la
elimina; si la adopto, downgrade solo quita lo que la adopcion anadio (los
indices que creo) y NUNCA borra una tabla que ya existia.
"""

import sqlalchemy as sa
import sqlalchemy.engine.mock

from alembic import op

revision = "0079_fact_anchors"
down_revision = "0078_position_valuation_hold"
branch_labels = None
depends_on = None

_TABLE = "fact_anchors"
_UNIQUE_NAME = "uq_fact_anchors_tenant_point"
_UNIQUE_COLUMNS = (
    "tenant_id",
    "accession_number",
    "filename",
    "field",
    "quote_offset",
    "body_sha256",
)
# name -> columnas, en orden. Un indice existente vale si cubre exactamente
# esas columnas (no unico), lleve el nombre que lleve.
_INDEXES = {
    "ix_fact_anchors_tenant_id": ("tenant_id",),
    "ix_fact_anchors_accession_number": ("accession_number",),
    "ix_fact_anchors_company": ("company_id",),
}
# columnas locales -> (tabla referida, columnas referidas). Sin ON DELETE.
_FKS = {
    ("company_id",): ("companies", ("id",)),
    ("tenant_id",): ("tenants", ("id",)),
}
_ADOPTION_TABLE = "migration_adoption_log"


def _expected_columns() -> list[tuple[str, sa.types.TypeEngine, bool]]:
    """Definicion congelada: la misma que crea la tabla en instalaciones nuevas."""
    return [
        ("id", sa.Integer(), False),
        ("accession_number", sa.String(40), False),
        ("filename", sa.String(255), False),
        ("body_sha256", sa.String(64), False),
        ("field", sa.String(80), False),
        ("value_text", sa.String(2000), False),
        ("label", sa.String(10), False),
        ("quote", sa.Text(), False),
        ("quote_offset", sa.Integer(), False),
        ("item", sa.String(40), True),
        ("extractor", sa.String(120), False),
        ("derivation", sa.Text(), True),
        ("company_id", sa.Integer(), True),
        ("tenant_id", sa.Integer(), True),
        ("created_at", sa.DateTime(timezone=True), False),
        ("updated_at", sa.DateTime(timezone=True), False),
    ]


def _create_fact_anchors() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("accession_number", sa.String(40), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("body_sha256", sa.String(64), nullable=False),
        sa.Column("field", sa.String(80), nullable=False),
        sa.Column("value_text", sa.String(2000), nullable=False),
        sa.Column("label", sa.String(10), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("quote_offset", sa.Integer(), nullable=False),
        sa.Column("item", sa.String(40), nullable=True),
        sa.Column("extractor", sa.String(120), nullable=False),
        sa.Column("derivation", sa.Text(), nullable=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(*_UNIQUE_COLUMNS, name=_UNIQUE_NAME),
    )
    for name, cols in _INDEXES.items():
        op.create_index(name, _TABLE, list(cols))


def _validate_existing(inspector: sa.Inspector, dialect: sa.engine.Dialect) -> list[str]:
    """Compara la tabla preexistente con la definicion congelada.

    Devuelve la lista de divergencias (vacia = adoptable). No modifica nada.
    """
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
    wanted_fks = {(cols, ref_table, ref_cols, None) for cols, (ref_table, ref_cols) in _FKS.items()}
    if reflected_fks != wanted_fks:
        divergences.append(f"FK esperadas {sorted(wanted_fks)!r}, reflejadas {sorted(reflected_fks)!r}")

    unique_ok = any(
        set(uc["column_names"]) == set(_UNIQUE_COLUMNS) for uc in inspector.get_unique_constraints(_TABLE)
    ) or any(
        ix["unique"] and set(ix["column_names"]) == set(_UNIQUE_COLUMNS)
        for ix in inspector.get_indexes(_TABLE)
    )
    if not unique_ok:
        divergences.append(f"falta restriccion UNIQUE sobre {sorted(_UNIQUE_COLUMNS)}")

    existing_indexes = inspector.get_indexes(_TABLE)
    existing_names = {ix["name"] for ix in existing_indexes}
    for name, cols in _INDEXES.items():
        covered = any(not ix["unique"] and tuple(ix["column_names"]) == cols for ix in existing_indexes)
        if covered:
            continue
        if name in existing_names:
            divergences.append(f"indice {name} existe pero no cubre {list(cols)}: nombre ocupado")
        # Si no esta cubierto y el nombre esta libre, upgrade lo crea: no es divergencia.
    return divergences


def _ensure_indexes() -> list[str]:
    """Crea los indices que falten en una tabla adoptada; devuelve los creados."""
    inspector = sa.inspect(op.get_bind())
    existing = inspector.get_indexes(_TABLE)
    existing_names = {ix["name"] for ix in existing}
    created: list[str] = []
    for name, cols in _INDEXES.items():
        covered = any(not ix["unique"] and tuple(ix["column_names"]) == cols for ix in existing)
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
    """created_indexes registrado si ESTA revision adopto la tabla; None si no."""
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
        sa.text(f"DELETE FROM {_ADOPTION_TABLE} WHERE revision = :revision AND table_name = :table_name"),
        {"revision": revision, "table_name": _TABLE},
    )
    remaining = bind.execute(sa.text(f"SELECT COUNT(*) FROM {_ADOPTION_TABLE}")).scalar_one()
    if remaining == 0:
        op.drop_table(_ADOPTION_TABLE)


def _is_offline() -> bool:
    return isinstance(op.get_bind(), sa.engine.mock.MockConnection)


def _drop_fact_anchors() -> None:
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
        # Sin conexion no se puede inspeccionar: se emite el alta completa,
        # la unica interpretacion sensata para generar SQL.
        _create_fact_anchors()
        return
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(_TABLE):
        _create_fact_anchors()
        return

    bind = op.get_bind()
    divergences = _validate_existing(inspector, bind.dialect)
    if divergences:
        raise RuntimeError(
            "0079_fact_anchors: la tabla fact_anchors preexistente NO coincide con"
            " el esquema esperado; no se adopta ni se modifica nada. El origen de"
            " la tabla no esta confirmado: reconciliar manualmente antes de"
            " reintentar. Divergencias: " + "; ".join(divergences)
        )
    created = _ensure_indexes()
    _record_adoption(created)


def downgrade() -> None:
    if _is_offline():
        _drop_fact_anchors()
        return
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(_TABLE):
        return

    adopted = _adopted_index_names(bind)
    if adopted is None:
        # La tabla la creo ESTA migracion: downgrade completo, como siempre.
        _drop_fact_anchors()
        return

    # Adoptada: la tabla era preexistente y NO se toca. Solo se quitan los
    # indices que creo la adopcion y se retira el registro.
    if adopted:
        existing = {ix["name"] for ix in inspector.get_indexes(_TABLE)}
        for name in adopted.split(","):
            if name in existing:
                op.drop_index(name, table_name=_TABLE)
    _drop_adoption_marker(bind)
