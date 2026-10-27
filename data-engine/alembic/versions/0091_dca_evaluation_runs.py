"""dca_evaluation_runs: resumen de cada ejecucion de la evaluacion DCA.

Aditiva. Una fila por ejecucion (job diario o boton manual) para que el panel
distinga "nunca ejecutado" de "la ultima ejecucion fallo". No toca
``dca_signal_states`` ni la logica del motor. Si ``create_all`` creo la tabla
antes, se adopta solo si el esquema es identico; cualquier divergencia FALLA.
El downgrade conserva la tabla (historial de ejecuciones, sin datos sensibles).
"""
import sqlalchemy as sa

from alembic import op

revision = "0091_dca_evaluation_runs"
down_revision = "0090_paper_proposal_currency"
branch_labels = None
depends_on = None

_TABLE = "dca_evaluation_runs"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(_TABLE):
        _adopt(inspector)
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("trigger", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tracked", sa.Integer(), nullable=False),
        sa.Column("evaluated", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("errors_count", sa.Integer(), nullable=False),
        sa.Column("alerted_count", sa.Integer(), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("error", sa.String(300), nullable=True),
        sa.Column("params_version", sa.String(40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_dca_evaluation_runs_tenant_id", _TABLE, ["tenant_id"])
    op.create_index("ix_dca_evaluation_runs_started_at", _TABLE, ["started_at"])


def _adopt(inspector) -> None:
    """Adopta una tabla creada antes por ``create_all`` solo si es identica.

    Se valida el esquema completo: columnas, nullability, tipo, longitud de los
    strings, clave primaria y FK de ``tenant_id``. Los indices que falten se
    crean (operacion segura y aditiva); todo lo demas que difiera FALLA sin
    tocar nada.
    """
    from app.models.entities import DcaEvaluationRun

    columns = {c["name"]: c for c in inspector.get_columns(_TABLE)}
    expected = DcaEvaluationRun.__table__.columns
    if set(columns) != set(expected.keys()):
        raise RuntimeError("dca_evaluation_runs schema mismatch: columnas")
    for name, column in columns.items():
        target = expected[name]
        if column["nullable"] != target.nullable or column["type"]._type_affinity != target.type._type_affinity:
            raise RuntimeError(f"dca_evaluation_runs schema mismatch: {name}")
        if isinstance(target.type, sa.String) and getattr(column["type"], "length", None) != target.type.length:
            raise RuntimeError(f"dca_evaluation_runs schema mismatch: longitud de {name}")
    if inspector.get_pk_constraint(_TABLE).get("constrained_columns") != ["id"]:
        raise RuntimeError("dca_evaluation_runs schema mismatch: clave primaria")
    fks = [
        fk for fk in inspector.get_foreign_keys(_TABLE)
        if fk["constrained_columns"] == ["tenant_id"] and fk["referred_table"] == "tenants"
        and fk["referred_columns"] == ["id"]
    ]
    if not fks:
        raise RuntimeError("dca_evaluation_runs schema mismatch: falta FK tenant_id -> tenants.id")
    present = {tuple(ix["column_names"]) for ix in inspector.get_indexes(_TABLE)}
    if ("tenant_id",) not in present:
        op.create_index("ix_dca_evaluation_runs_tenant_id", _TABLE, ["tenant_id"])
    if ("started_at",) not in present:
        op.create_index("ix_dca_evaluation_runs_started_at", _TABLE, ["started_at"])


def downgrade() -> None:
    # Historial de ejecuciones: se conserva; una version anterior lo ignora.
    pass
