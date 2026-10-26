"""privacy_audit_events: auditoria que sobrevive al borrado de la cuenta.

Aditiva y reversible. No guarda email ni contenido: solo tipo de evento,
identificadores externos y un detalle agregado.

Misma situacion que 0079_fact_anchors: el arranque del backend ejecuta
`create_all` del ORM en `init_db`, asi que la tabla puede existir ya
en prod antes de que Alembic llegue a esta revision. Si existe, se valida el
esquema completo contra la definicion congelada de esta migracion (columnas
con tipo y nullability, PK, ausencia de FK/unique); cualquier divergencia
FALLA la migracion sin tocar nada (origen no confirmado: reconciliacion
manual). Si es compatible, se adopta: solo se crean los indices que falten y
se registra la adopcion en `migration_adoption_log` para que downgrade no
destruya una tabla preexistente. La columna `documents.retention_tombstoned_at`
y su indice se anaden si faltan; el registro anota exactamente lo que esta
migracion creo para que downgrade solo retire eso.
"""

import sqlalchemy as sa
import sqlalchemy.engine.mock

from alembic import op

revision = "0080_privacy_audit_events"
down_revision = "0079_fact_anchors"
branch_labels = None
depends_on = None

_TABLE = "privacy_audit_events"
_DOC_TABLE = "documents"
_DOC_COLUMN = "retention_tombstoned_at"
_DOC_INDEX = "ix_documents_retention_tombstoned_at"
_INDEXES = {
    "ix_privacy_audit_events_event_type": ("event_type",),
    "ix_privacy_audit_events_tenant_external_id": ("tenant_external_id",),
    "ix_privacy_audit_events_user_id": ("user_id",),
    "ix_privacy_audit_events_created_at": ("created_at",),
}
_ADOPTION_TABLE = "migration_adoption_log"


def _expected_columns() -> list[tuple[str, sa.types.TypeEngine, bool]]:
    return [
        ("id", sa.Integer(), False),
        ("event_type", sa.String(60), False),
        ("tenant_external_id", sa.String(160), True),
        ("user_id", sa.String(160), True),
        ("detail", sa.JSON(), False),
        ("created_at", sa.DateTime(timezone=True), False),
    ]


def _is_offline() -> bool:
    return isinstance(op.get_bind(), sa.engine.mock.MockConnection)


def _create_privacy_audit_events() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=60), nullable=False),
        sa.Column("tenant_external_id", sa.String(length=160), nullable=True),
        sa.Column("user_id", sa.String(length=160), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
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

    reflected_fks = inspector.get_foreign_keys(_TABLE)
    if reflected_fks:
        divergences.append(f"no se esperaban FK y hay {len(reflected_fks)}")
    reflected_uniques = inspector.get_unique_constraints(_TABLE)
    if reflected_uniques:
        divergences.append(f"no se esperaban restricciones UNIQUE y hay {len(reflected_uniques)}")

    existing_indexes = inspector.get_indexes(_TABLE)
    existing_names = {ix["name"] for ix in existing_indexes}
    for name, cols in _INDEXES.items():
        covered = any(not ix["unique"] and tuple(ix["column_names"]) == cols for ix in existing_indexes)
        if covered:
            continue
        if name in existing_names:
            divergences.append(f"indice {name} existe pero no cubre {list(cols)}: nombre ocupado")
    return divergences


def _record_adoption(created_tags: list[str]) -> None:
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
            "created_indexes": ",".join(created_tags),
        },
    )


def _ensure_documents_column() -> list[str]:
    """Anade la columna de retencion y su indice si faltan.

    Devuelve los tags de lo creado ("doccol" / "docidx") para que downgrade
    solo retire lo que esta migracion anadio.
    """
    inspector = sa.inspect(op.get_bind())
    created: list[str] = []
    doc_columns = {col["name"] for col in inspector.get_columns(_DOC_TABLE)}
    if _DOC_COLUMN not in doc_columns:
        op.add_column(
            _DOC_TABLE,
            sa.Column(_DOC_COLUMN, sa.DateTime(timezone=True), nullable=True),
        )
        created.append("doccol")
    doc_indexes = inspector.get_indexes(_DOC_TABLE)
    covered = any(not ix["unique"] and tuple(ix["column_names"]) == (_DOC_COLUMN,) for ix in doc_indexes)
    name_taken = any(ix["name"] == _DOC_INDEX for ix in doc_indexes)
    if not covered and name_taken:
        raise RuntimeError(
            f"0080_privacy_audit_events: el indice {_DOC_INDEX} existe en documents"
            f" pero no cubre ({_DOC_COLUMN}); reconciliar manualmente"
        )
    if not covered:
        op.create_index(_DOC_INDEX, _DOC_TABLE, [_DOC_COLUMN])
        created.append("docidx")
    return created


def _drop_documents_column(created_tags: list[str]) -> None:
    inspector = sa.inspect(op.get_bind())
    doc_indexes = {ix["name"] for ix in inspector.get_indexes(_DOC_TABLE)}
    if "docidx" in created_tags and _DOC_INDEX in doc_indexes:
        op.drop_index(_DOC_INDEX, table_name=_DOC_TABLE)
    doc_columns = {col["name"] for col in inspector.get_columns(_DOC_TABLE)}
    if "doccol" in created_tags and _DOC_COLUMN in doc_columns:
        op.drop_column(_DOC_TABLE, _DOC_COLUMN)


def upgrade() -> None:
    if _is_offline():
        # Sin conexion no se puede inspeccionar: se emite el alta completa.
        op.add_column(
            _DOC_TABLE,
            sa.Column(_DOC_COLUMN, sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(_DOC_INDEX, _DOC_TABLE, [_DOC_COLUMN])
        _create_privacy_audit_events()
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_preexists = inspector.has_table(_TABLE)

    if table_preexists:
        divergences = _validate_existing(inspector, bind.dialect)
        if divergences:
            raise RuntimeError(
                "0080_privacy_audit_events: la tabla privacy_audit_events"
                " preexistente NO coincide con el esquema esperado; no se adopta"
                " ni se modifica nada. El origen de la tabla no esta confirmado:"
                " reconciliar manualmente antes de reintentar. Divergencias: " + "; ".join(divergences)
            )

    created_tags = _ensure_documents_column()

    if not table_preexists:
        _create_privacy_audit_events()
        return

    existing = sa.inspect(bind).get_indexes(_TABLE)
    existing_names = {ix["name"] for ix in existing}
    for name, cols in _INDEXES.items():
        covered = any(not ix["unique"] and tuple(ix["column_names"]) == cols for ix in existing)
        if not covered and name not in existing_names:
            op.create_index(name, _TABLE, list(cols))
            created_tags.append(f"idx:{name}")
    _record_adoption(created_tags)


def downgrade() -> None:
    if _is_offline():
        op.drop_index(_DOC_INDEX, table_name=_DOC_TABLE)
        op.drop_column(_DOC_TABLE, _DOC_COLUMN)
        for name in reversed(list(_INDEXES)):
            op.drop_index(name, table_name=_TABLE)
        op.drop_table(_TABLE)
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    adopted_tags: str | None = None
    if inspector.has_table(_ADOPTION_TABLE):
        row = bind.execute(
            sa.text(
                f"SELECT created_indexes FROM {_ADOPTION_TABLE}"
                " WHERE revision = :revision AND table_name = :table_name"
            ),
            {"revision": revision, "table_name": _TABLE},
        ).fetchone()
        adopted_tags = None if row is None else str(row[0])

    if adopted_tags is None:
        # Todo lo creo ESTA migracion: downgrade completo, como siempre.
        if inspector.has_table(_TABLE):
            existing = {ix["name"] for ix in inspector.get_indexes(_TABLE)}
            for name in reversed(list(_INDEXES)):
                if name in existing:
                    op.drop_index(name, table_name=_TABLE)
            op.drop_table(_TABLE)
        _drop_documents_column(["doccol", "docidx"])
        return

    # Tabla adoptada: NUNCA se borra. Solo se retira lo que la adopcion anadio.
    tags = [tag for tag in adopted_tags.split(",") if tag]
    if inspector.has_table(_TABLE):
        existing = {ix["name"] for ix in inspector.get_indexes(_TABLE)}
        for tag in tags:
            if tag.startswith("idx:") and tag[4:] in existing:
                op.drop_index(tag[4:], table_name=_TABLE)
    _drop_documents_column(tags)
    bind.execute(
        sa.text(f"DELETE FROM {_ADOPTION_TABLE} WHERE revision = :revision AND table_name = :table_name"),
        {"revision": revision, "table_name": _TABLE},
    )
    remaining = bind.execute(sa.text(f"SELECT COUNT(*) FROM {_ADOPTION_TABLE}")).scalar_one()
    if remaining == 0:
        op.drop_table(_ADOPTION_TABLE)
