"""Materializa ON DELETE en las 5 FK entrantes de financial_facts (Postgres).

entities.py declara SET NULL / CASCADE en estas FK, pero 0032 documenta que las
migraciones nunca las crearon: en Postgres son NO ACTION. Hoy lo compensa
``fact_deletion.delete_financial_facts`` (desvincula y borra a mano); esta
migracion deja la BD haciendo lo que el modelo promete. El codigo de aplicacion
sigue siendo valido con o sin ella.

Solo Postgres (SQLite no aplica FK). Idempotente: si la FK ya tiene la accion
deseada no se toca. En Postgres no hay ``ALTER ... ON DELETE``: se suelta y se
recrea la FK (bloqueo breve; ``lock_timeout`` evita esperar indefinidamente).
El downgrade vuelve a NO ACTION.
"""
import sqlalchemy as sa

from alembic import op

revision = "0062_financial_fact_fk_ondelete"
down_revision = "0061_manager_holding_value_scale"
branch_labels = None
depends_on = None

# (tabla, columna, accion deseada)
FKS = (
    ("kpi_extraction_candidates", "canonical_fact_id", "SET NULL"),
    ("call_claims", "linked_result_id", "SET NULL"),
    ("expectation_reviews", "actual_fact_id", "SET NULL"),
    ("management_promises", "actual_fact_id", "SET NULL"),
    ("fact_revisions", "financial_fact_id", "CASCADE"),
)
CODES = {"NO ACTION": "a", "SET NULL": "n", "CASCADE": "c"}


def _current(bind, table: str, column: str):
    """Devuelve (nombre, confdeltype) de la FK table.column -> financial_facts.id."""
    return bind.execute(
        sa.text(
            """
            SELECT c.conname, c.confdeltype
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_class r ON r.oid = c.confrelid
            JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
            WHERE c.contype = 'f' AND t.relname = :table AND r.relname = 'financial_facts'
              AND a.attname = :column AND t.relnamespace = current_schema()::regnamespace
            """
        ),
        {"table": table, "column": column},
    ).first()


def _apply(action_for) -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("SET LOCAL lock_timeout = '10s'")
    for table, column, desired in FKS:
        action = action_for(desired)
        row = _current(bind, table, column)
        if row is None:
            continue  # la tabla no tiene esa FK en este entorno: nada que cambiar
        name, code = row
        if code == CODES[action]:
            continue
        op.execute(sa.text(f'ALTER TABLE "{table}" DROP CONSTRAINT "{name}"'))
        op.execute(
            sa.text(
                f'ALTER TABLE "{table}" ADD CONSTRAINT "{name}" FOREIGN KEY ("{column}") '
                f"REFERENCES financial_facts (id) ON DELETE {action}"
            )
        )


def upgrade() -> None:
    _apply(lambda desired: desired)


def downgrade() -> None:
    _apply(lambda desired: "NO ACTION")
