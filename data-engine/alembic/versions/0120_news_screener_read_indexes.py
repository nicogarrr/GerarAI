"""Indices de lectura para el feed de /research/news y el screener.

Revision ID: 0120_news_screener_read_indexes
Revises: 0119_cold_endpoint_indexes
Create Date: 2026-10-31T15:00:00.000Z

Motivo: feed de /research/news ~7 s de backend y /screeners ~15 s (medido
por UX movil en prod). Medido con EXPLAIN sobre copia, nunca en prod. Sin
solape con 0119 (data-health y metric-coverage): ni mismas tablas-columnas
ni mismo proposito.

MEDIDO (EXPLAIN (ANALYZE, BUFFERS), PG 16.2 local, BD scratch migrada a
head con volumenes con forma de prod LEIDO del docstring de 0119: 5
tenants, 2.132 empresas, 255.840 market_prices, 255.840 financial_facts,
102.336 calculated_metrics; news_events 200.000 es SUPUESTO, sin conteo
de prod registrado; prod corre PG 17, la forma del plan es la que cuenta):

- Portada del feed (ORDER BY date DESC, id DESC con filtro de carril sobre
  metadata): Parallel Seq Scan de toda la tabla + top-N heapsort para
  servir 200 filas, 72,3 ms y 5.807 buffers -> Index Scan con parada
  temprana, 0,65 ms y 371 buffers (111x). Con OFFSET 1800 (scroll
  profundo): 74,6 ms -> 3,2 ms.
- Carril macro (lane='macro' + frescura 72 h): el indice por fecha no
  bastaba (22,9 ms; bitmap sobre la ventana fresca salia peor, 43,9 ms
  forzado): indice parcial por carril -> 0,35 ms de scan. Sirve tambien al
  fallback de archivo (misma lane sin corte de fecha).
- Screener, ventana row_number de calculated_metrics: Incremental Sort de
  78.360 filas, 71,0 ms y 1.714 buffers en la subconsulta -> Index Only
  Scan sin sort, 46,1 ms y 439 buffers. financial_facts auditado y
  DESCARTADO para indice: tenant_id = 1 abarca el 80% de la tabla, ningun
  indice lo mejora (43,5 -> 43,2 ms); su mejora es la reescritura
  single-pass de _facts_by_company (43,5 -> 5,9 ms, conjunto de filas
  identico verificado por md5), que va en el mismo PR como codigo.

Mismo patron que 0117: CREATE INDEX CONCURRENTLY dentro de
autocommit_block (los Dockerfiles migran al arrancar), IF NOT EXISTS,
INVALID propio por tabla detectado y recreado; sqlite con guard por
inspector y sqlite_where en los parciales (sqlite 3.53 soporta ->>,
DESC y NULLS LAST).

Modelos alineados (Index con postgresql_where, mismos nombres): el rachet
no crece.

"""

import sqlalchemy as sa

from alembic import op

revision = "0120_news_screener_read_indexes"
down_revision = "0119_cold_endpoint_indexes"
branch_labels = None
depends_on = None

_INDICES = [
    (
        "ix_news_events_date_id",
        "news_events",
        [sa.text("date DESC"), sa.text("id DESC")],
        None,
    ),
    (
        "ix_news_events_macro_date_id",
        "news_events",
        [sa.text("date DESC"), sa.text("id DESC")],
        "(metadata ->> 'news_lane') = 'macro'",
    ),
    (
        "ix_calc_metrics_screener_window",
        "calculated_metrics",
        [
            "tenant_id",
            "company_id",
            "metric",
            sa.text("fiscal_year DESC NULLS LAST"),
            sa.text("id DESC"),
        ],
        "status = 'ok' AND value IS NOT NULL",
    ),
]

# sqlite no acepta NULLS LAST en CREATE INDEX ("unsupported use"); la
# variante sqlite usa DESC plano: mismas columnas, mismo orden de filas no
# nulas; los tests no dependen de la posicion de nulos en el indice.
_SQLITE_COLS = {
    "ix_calc_metrics_screener_window": [
        "tenant_id",
        "company_id",
        "metric",
        sa.text("fiscal_year DESC"),
        sa.text("id DESC"),
    ],
}


def _es_invalido(bind, nombre: str, tabla: str) -> bool:
    """True si EXISTE un indice INVALID llamado ``nombre`` sobre ESA tabla
    (mismo criterio que 0117: indrelid via search_path)."""
    return bool(
        bind.execute(
            sa.text(
                "select 1 from pg_index i "
                "join pg_class idx on idx.oid = i.indexrelid "
                "where i.indrelid = cast(:tabla as regclass) "
                "and idx.relname = :nombre and not i.indisvalid"
            ),
            {"tabla": tabla, "nombre": nombre},
        ).first()
    )


def _crear(nombre, tabla, columnas, where, **kwargs) -> None:
    opciones = dict(kwargs)
    if where is not None:
        key = "postgresql_where" if "postgresql_concurrently" in kwargs else "sqlite_where"
        opciones[key] = sa.text(where)
    op.create_index(nombre, tabla, columnas, **opciones)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            for nombre, tabla, columnas, where in _INDICES:
                if _es_invalido(bind, nombre, tabla):
                    op.drop_index(
                        nombre,
                        table_name=tabla,
                        postgresql_concurrently=True,
                        if_exists=True,
                    )
                _crear(
                    nombre,
                    tabla,
                    columnas,
                    where,
                    postgresql_concurrently=True,
                    if_not_exists=True,
                )
        return
    inspector = sa.inspect(bind)
    existentes = {
        ix["name"]
        for tabla in {t for _, t, _, _ in _INDICES}
        for ix in inspector.get_indexes(tabla)
    }
    for nombre, tabla, columnas, where in _INDICES:
        if nombre not in existentes:
            _crear(nombre, tabla, _SQLITE_COLS.get(nombre, columnas), where)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            for nombre, tabla, _, _ in _INDICES:
                op.drop_index(
                    nombre,
                    table_name=tabla,
                    postgresql_concurrently=True,
                    if_exists=True,
                )
        return
    inspector = sa.inspect(bind)
    existentes = {
        ix["name"]
        for tabla in {t for _, t, _, _ in _INDICES}
        for ix in inspector.get_indexes(tabla)
    }
    for nombre, tabla, _, _ in _INDICES:
        if nombre in existentes:
            op.drop_index(nombre, table_name=tabla)
