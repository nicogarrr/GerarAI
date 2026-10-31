"""Crear los indices que los modelos declaran y ninguna migracion creaba.

Revision ID: 0113_add_model_indexes
Revises: 0112_propicks_radar_snapshots
Create Date: 2026-10-31T01:50:00.000Z

Deriva medida por compare_metadata (rachet de tests/test_alembic_chain.py):
app.models declara index=True en estas columnas pero la cadena de
migraciones nunca los creo, asi que las BDs migradas (produccion incluida)
no los tienen y las consultas tenant-scoped de esas tablas hacen seq scan:

- fundamental_valuation_snapshots: model_version_id, company_id,
  market_snapshot_fingerprint, valuation_snapshot_fingerprint, tenant_id
- schedule_13dg_filings: tenant_id
- thesis_projection_years: company_id

CREATE INDEX CONCURRENTLY no es viable aqui: env.py ejecuta toda la corrida
de Alembic en UNA sola transaccion y PostgreSQL prohibe CONCURRENTLY dentro
de un bloque. Son tablas tenant-scoped de bajo volumen (snapshots de
valoracion, filings 13D/G, anos proyectados de tesis), asi que el bloqueo
de escritura del CREATE INDEX normal es breve (SUPUESTO: app monousuario,
miles de filas como mucho). if_not_exists/if_exists: idempotente ante BDs
construidas desde metadata (tests) donde ya existen.

Fulfills: VAL-DB-006 (cierre de deriva de indices declarados)
"""

from alembic import op

revision = "0113_add_model_indexes"
down_revision = "0112_propicks_radar_snapshots"
branch_labels = None
depends_on = None

_INDICES = [
    (
        "ix_fundamental_valuation_snapshots_model_version_id",
        "fundamental_valuation_snapshots",
        ["model_version_id"],
    ),
    ("ix_fundamental_valuation_snapshots_company_id", "fundamental_valuation_snapshots", ["company_id"]),
    (
        "ix_fundamental_valuation_snapshots_market_snapshot_fingerprint",
        "fundamental_valuation_snapshots",
        ["market_snapshot_fingerprint"],
    ),
    (
        "ix_fundamental_valuation_snapshots_valuation_fp",
        "fundamental_valuation_snapshots",
        ["valuation_snapshot_fingerprint"],
    ),
    ("ix_fundamental_valuation_snapshots_tenant_id", "fundamental_valuation_snapshots", ["tenant_id"]),
    ("ix_schedule_13dg_filings_tenant_id", "schedule_13dg_filings", ["tenant_id"]),
    ("ix_thesis_projection_years_company_id", "thesis_projection_years", ["company_id"]),
]


def upgrade() -> None:
    for nombre, tabla, columnas in _INDICES:
        op.create_index(nombre, tabla, columnas, unique=False, if_not_exists=True)


def downgrade() -> None:
    for nombre, tabla, _columnas in reversed(_INDICES):
        op.drop_index(nombre, table_name=tabla, if_exists=True)
