"""Alinear FKs con lo que los modelos declaran: ondelete y FKs de tenant.

Revision ID: 0114_fk_ondelete_tenants
Revises: 0113_add_model_indexes
Create Date: 2026-10-31T02:07:00.000Z

MEDIDO (BD limpia migrada a 0113, reconciliacion Base.metadata vs pg_constraint):

- 53 FKs cuyo ondelete declarado (CASCADE o SET NULL) nunca se migro: en la BD
  son NO ACTION. La 0107_add_fk_cascades solo cubrio las 7 de portfolio. En prod,
  borrar un document/thesis_version/model_version daba error de FK donde el modelo
  espera CASCADE, y dejaba el hijo apuntando donde espera SET NULL.
- 6 FKs de tenant_id que ninguna migracion creo (misma clase que los indices de
  la 0113): la era fundamental-model los olvido.

Patron prod-seguro: en PostgreSQL se (re)crean NOT VALID, asi el deploy no
escanea las filas existentes y un huerfano legado no lo rompe. OJO (corregido
tras revision del piloto): las acciones ON DELETE CASCADE/SET NULL rigen
INMEDIATAMENTE al aplicar el DDL, sin necesidad de VALIDATE — el deploy de esta
migracion YA cambia el comportamiento de los borrados. VALIDATE solo verifica
las filas heredadas (detecta huerfanos); queda como paso operativo aparte, a
decidir por Nico (lista en el PR). Los ondelete se recrean con el MISMO nombre
que tenga el constraint en la BD (resuelto en runtime por tabla+columna) para
no mover el ruido de nombres de la baseline del rachet. En sqlite no se puede
recrear un FK sin nombre: el cambio de ondelete se omite (los tests hermeticos
no lo enforzan) y los FKs de tenant si se crean (no existian en ninguna BD).
Guard por inspector/consulta en cada paso: idempotente.

NO desplegar en produccion hasta que Nico lo decida.
"""

import sqlalchemy as sa

from alembic import op

revision = "0114_fk_ondelete_tenants"
down_revision = "0113_add_model_indexes"
branch_labels = None
depends_on = None

_FK_SQL = (
    "select c.conname, c.confdeltype from pg_constraint c "
    "join pg_attribute a on a.attrelid = c.conrelid and a.attnum = c.conkey[1] "
    "where c.contype = 'f' and array_length(c.conkey, 1) = 1 "
    "and c.conrelid = cast(:tabla as regclass) and a.attname = :columna limit 1"
)

# (tabla, columna, tabla_ref, columna_ref, ondelete)
_ONDELETE = [
    ("call_claims", "transcript_id", "transcripts", "id", "CASCADE"),
    ("cash_daily_snapshots", "portfolio_snapshot_id", "portfolio_daily_snapshots", "id", "CASCADE"),
    ("catalysts", "source_id", "documents", "id", "SET NULL"),
    ("claim_evidence", "claim_id", "claims", "id", "CASCADE"),
    ("claim_evidence", "document_chunk_id", "document_chunks", "id", "SET NULL"),
    ("claim_evidence", "document_id", "documents", "id", "SET NULL"),
    ("claims", "thesis_version_id", "thesis_versions", "id", "SET NULL"),
    ("connector_states", "company_id", "companies", "id", "SET NULL"),
    ("decision_journal_entries", "model_version_id", "fundamental_model_versions", "id", "SET NULL"),
    ("decision_journal_entries", "thesis_version_id", "thesis_versions", "id", "SET NULL"),
    ("document_chunks", "document_id", "documents", "id", "CASCADE"),
    ("documents", "company_id", "companies", "id", "SET NULL"),
    ("earnings_runs", "thesis_change_id", "thesis_changes", "id", "SET NULL"),
    ("evidence_suggestions", "document_chunk_id", "document_chunks", "id", "SET NULL"),
    ("evidence_suggestions", "document_id", "documents", "id", "SET NULL"),
    ("evidence_suggestions", "suggested_claim_id", "claims", "id", "SET NULL"),
    ("expectation_reviews", "actual_metric_id", "calculated_metrics", "id", "SET NULL"),
    ("expectation_reviews", "model_version_id", "fundamental_model_versions", "id", "CASCADE"),
    ("external_claims", "company_id", "companies", "id", "SET NULL"),
    ("external_claims", "source_id", "documents", "id", "SET NULL"),
    ("financial_facts", "source_id", "documents", "id", "SET NULL"),
    ("financial_statements", "source_id", "documents", "id", "SET NULL"),
    ("fundamental_assumptions", "model_version_id", "fundamental_model_versions", "id", "CASCADE"),
    ("fundamental_drivers", "model_version_id", "fundamental_model_versions", "id", "CASCADE"),
    ("fundamental_forecasts", "model_version_id", "fundamental_model_versions", "id", "CASCADE"),
    ("fundamental_valuation_snapshots", "model_version_id", "fundamental_model_versions", "id", "CASCADE"),
    ("insider_transactions", "filing_id", "insider_filings", "id", "CASCADE"),
    ("management_promises", "call_claim_id", "call_claims", "id", "SET NULL"),
    ("management_promises", "source_document_id", "documents", "id", "SET NULL"),
    ("memory_items", "research_session_id", "research_sessions", "id", "SET NULL"),
    ("news_events", "company_id", "companies", "id", "SET NULL"),
    ("plan_contributions", "plan_id", "investment_plans", "id", "CASCADE"),
    ("position_daily_snapshots", "portfolio_snapshot_id", "portfolio_daily_snapshots", "id", "CASCADE"),
    ("red_team_runs", "thesis_version_id", "thesis_versions", "id", "SET NULL"),
    ("research_alerts", "review_id", "research_reviews", "id", "SET NULL"),
    ("research_reviews", "claim_id", "claims", "id", "SET NULL"),
    ("research_reviews", "news_event_id", "news_events", "id", "SET NULL"),
    ("research_reviews", "thesis_change_id", "thesis_changes", "id", "SET NULL"),
    ("risk_events", "company_id", "companies", "id", "SET NULL"),
    ("saved_screen_matches", "saved_screen_id", "saved_screens", "id", "CASCADE"),
    ("source_audits", "thesis_version_id", "thesis_versions", "id", "SET NULL"),
    ("thesis_changes", "from_version_id", "thesis_versions", "id", "SET NULL"),
    ("thesis_changes", "to_version_id", "thesis_versions", "id", "SET NULL"),
    ("thesis_diffs", "from_version_id", "thesis_versions", "id", "SET NULL"),
    ("thesis_diffs", "to_version_id", "thesis_versions", "id", "SET NULL"),
    ("thesis_edges", "from_node_id", "thesis_nodes", "id", "CASCADE"),
    ("thesis_edges", "to_node_id", "thesis_nodes", "id", "CASCADE"),
    ("thesis_nodes", "thesis_version_id", "thesis_versions", "id", "CASCADE"),
    ("thesis_sections", "thesis_version_id", "thesis_versions", "id", "CASCADE"),
    ("transactions", "company_id", "companies", "id", "SET NULL"),
    ("transcripts", "source_id", "documents", "id", "SET NULL"),
    ("valuation_assumptions", "valuation_model_id", "valuation_models", "id", "CASCADE"),
    ("valuation_outputs", "valuation_model_id", "valuation_models", "id", "CASCADE"),
]

# FKs de tenant_id ausentes: (tabla, columna, tabla_ref, columna_ref)
_TENANT = [
    ("decision_journal_entries", "tenant_id", "tenants", "id"),
    ("expectation_reviews", "tenant_id", "tenants", "id"),
    ("fundamental_assumptions", "tenant_id", "tenants", "id"),
    ("fundamental_drivers", "tenant_id", "tenants", "id"),
    ("fundamental_forecasts", "tenant_id", "tenants", "id"),
    ("fundamental_model_versions", "tenant_id", "tenants", "id"),
]

_DELTYPE = {"CASCADE": "c", "SET NULL": "n"}


def _fk_actual(bind, tabla, columna):
    """(nombre, confdeltype) del FK de (tabla, columna) en PG, o (None, None)."""
    row = bind.execute(sa.text(_FK_SQL), {"tabla": tabla, "columna": columna}).first()
    return (row[0], row[1]) if row else (None, None)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for tabla, columna, ref_tabla, ref_columna, ondelete in _ONDELETE:
            nombre, deltype = _fk_actual(bind, tabla, columna)
            if deltype == _DELTYPE[ondelete]:
                continue
            if nombre is not None:
                bind.execute(sa.text(f'alter table "{tabla}" drop constraint "{nombre}"'))
            else:
                nombre = f"{tabla}_{columna}_fkey"
            bind.execute(sa.text(
                f'alter table "{tabla}" add constraint "{nombre}" foreign key ("{columna}") '
                f'references "{ref_tabla}" ("{ref_columna}") on delete {ondelete} not valid'
            ))
        for tabla, columna, ref_tabla, ref_columna in _TENANT:
            nombre, _deltype = _fk_actual(bind, tabla, columna)
            if nombre is not None:
                continue
            bind.execute(sa.text(
                f'alter table "{tabla}" add constraint "fk_{tabla}_{columna}" foreign key '
                f'("{columna}") references "{ref_tabla}" ("{ref_columna}") not valid'
            ))
    else:
        # sqlite: no se puede recrear un FK sin nombre; solo los de tenant, que
        # no existen en ninguna BD. batch los crea con nombre explicito.
        inspector = sa.inspect(bind)
        for tabla, columna, ref_tabla, ref_columna in _TENANT:
            existentes = {tuple(fk["constrained_columns"]) for fk in inspector.get_foreign_keys(tabla)}
            if (columna,) in existentes:
                continue
            with op.batch_alter_table(tabla, schema=None) as batch_op:
                batch_op.create_foreign_key(
                    f"fk_{tabla}_{columna}", ref_tabla, [columna], [ref_columna],
                )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for tabla, columna, _ref_tabla, _ref_columna in _TENANT:
            nombre, _deltype = _fk_actual(bind, tabla, columna)
            if nombre is not None:
                bind.execute(sa.text(f'alter table "{tabla}" drop constraint "{nombre}"'))
        for tabla, columna, ref_tabla, ref_columna, _ondelete in _ONDELETE:
            nombre, deltype = _fk_actual(bind, tabla, columna)
            if nombre is None or deltype == "a":
                continue
            bind.execute(sa.text(f'alter table "{tabla}" drop constraint "{nombre}"'))
            bind.execute(sa.text(
                f'alter table "{tabla}" add constraint "{nombre}" foreign key ("{columna}") '
                f'references "{ref_tabla}" ("{ref_columna}") not valid'
            ))
    else:
        inspector = sa.inspect(bind)
        for tabla, columna, _ref_tabla, _ref_columna in _TENANT:
            nombre = f"fk_{tabla}_{columna}"
            nombres = {fk.get("name") for fk in inspector.get_foreign_keys(tabla)}
            if nombre in nombres:
                with op.batch_alter_table(tabla, schema=None) as batch_op:
                    batch_op.drop_constraint(nombre, type_="foreignkey")
