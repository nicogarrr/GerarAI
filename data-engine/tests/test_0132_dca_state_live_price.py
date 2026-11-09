"""0132 dca_signal_states live: propiedad registrada de columnas y downgrade.

Tres caminos hasta 0132: prod (0083 antigua, tabla sin columnas live y con
filas), base nueva (0083 crea la tabla y 0132 añade las columnas) y base
arrancada con create_all del ORM (la tabla adoptada ya trae las columnas).
0132 registra en migration_added_columns SOLO lo que añade y su downgrade
borra solo eso: las columnas del ORM y sus datos sobreviven.
"""

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from app.models.entities import DcaAlertOverride, DcaSignalState

DATA_ENGINE_DIR = Path(__file__).resolve().parents[1]
REV_0083_DOWN = "0085_thesis_invalidation_rules"
REV_0131 = "0131_documents_ingest_idx"
LIVE_COLUMNS = {"close_kind", "live_price", "live_session", "live_at"}
_BASE_SENTINEL = (
    "INSERT INTO dca_signal_states (symbol, level, status, period, signal_date, close,"
    " metrics, level_prices, sources, params_version, evaluated_at, data_source, created_at, updated_at"
)


def _alembic(database_url: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": database_url}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=DATA_ENGINE_DIR, env=env, capture_output=True, text=True, timeout=300,
    )


def _columns(url: str, table: str = "dca_signal_states") -> set[str]:
    engine = create_engine(url)
    try:
        return {col["name"] for col in inspect(engine).get_columns(table)}
    finally:
        engine.dispose()


def _exec(url: str, sql: str) -> None:
    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(text(sql))
    finally:
        engine.dispose()


def _fetchone(url: str, sql: str):
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            return conn.execute(text(sql)).first()
    finally:
        engine.dispose()


def _insert_sentinel(url: str, *, with_live: bool) -> None:
    if with_live:
        sql = _BASE_SENTINEL + ", close_kind, live_price, live_session, live_at) VALUES ("
        sql += "'NVDA', 2, 'forming', '2026-11', '2026-11-06', 186.64, '{}', '{}', '[]', 'v1',"
        sql += " '2026-11-06 21:00:00', 'yahoo', '2026-11-06 21:00:00', '2026-11-06 21:00:00',"
        sql += " 'live', 175.75, 'pre', '2026-11-09 13:30:00')"
    else:
        sql = _BASE_SENTINEL + ") VALUES ("
        sql += "'NVDA', 2, 'forming', '2026-11', '2026-11-06', 186.64, '{}', '{}', '[]', 'v1',"
        sql += " '2026-11-06 21:00:00', 'yahoo', '2026-11-06 21:00:00', '2026-11-06 21:00:00')"
    _exec(url, sql)


def test_prod_legacy_path_rows_survive_upgrade_and_downgrade(tmp_path: Path) -> None:
    """Prod: la tabla llega a 0131 sin columnas live y con filas. 0132 las
    añade (y lo registra), la fila queda intacta con close_kind='close'; el
    downgrade borra lo añadido y conserva los datos del resto de columnas."""
    url = f"sqlite:///{(tmp_path / 'prod.db').as_posix()}"
    result = _alembic(url, "upgrade", REV_0131)
    assert result.returncode == 0, result.stderr
    assert not (LIVE_COLUMNS & _columns(url))
    _insert_sentinel(url, with_live=False)
    result = _alembic(url, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    assert _columns(url) >= LIVE_COLUMNS
    row = _fetchone(url, "SELECT close, close_kind FROM dca_signal_states WHERE symbol='NVDA'")
    assert float(row[0]) == 186.64 and row[1] == "close"
    result = _alembic(url, "downgrade", REV_0131)
    assert result.returncode == 0, result.stderr
    assert not (LIVE_COLUMNS & _columns(url))
    row = _fetchone(url, "SELECT close, period FROM dca_signal_states WHERE symbol='NVDA'")
    assert float(row[0]) == 186.64 and row[1] == "2026-11"


def test_fresh_chain_0132_owns_columns_and_downgrade_keeps_base_data(tmp_path: Path) -> None:
    """Base nueva por Alembic: las columnas live las añade 0132 (registradas),
    asi que su downgrade las borra; los datos de las columnas base sobreviven."""
    url = f"sqlite:///{(tmp_path / 'fresh.db').as_posix()}"
    result = _alembic(url, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    assert _columns(url) >= LIVE_COLUMNS
    _insert_sentinel(url, with_live=True)
    result = _alembic(url, "downgrade", REV_0131)
    assert result.returncode == 0, result.stderr
    assert not (LIVE_COLUMNS & _columns(url))
    row = _fetchone(url, "SELECT close, signal_date FROM dca_signal_states WHERE symbol='NVDA'")
    assert float(row[0]) == 186.64 and str(row[1]) == "2026-11-06"
    # Re-subir las repone sin error (idempotente sobre lo registrado).
    result = _alembic(url, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    assert _columns(url) >= LIVE_COLUMNS


def test_orm_adopted_live_columns_and_data_survive_downgrade(tmp_path: Path) -> None:
    """ORM (create_all): la tabla adoptada ya trae las columnas live con
    datos. 0132 no añade ni registra nada; su downgrade NO toca las columnas
    ni la fila centinela con live_price."""
    url = f"sqlite:///{(tmp_path / 'adopt.db').as_posix()}"
    assert _alembic(url, "upgrade", REV_0083_DOWN).returncode == 0
    engine = create_engine(url)
    try:
        DcaSignalState.__table__.create(engine)
        DcaAlertOverride.__table__.create(engine)
    finally:
        engine.dispose()
    _insert_sentinel(url, with_live=True)
    result = _alembic(url, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    assert _columns(url) >= LIVE_COLUMNS
    logged = _fetchone(
        url,
        "SELECT COUNT(*) FROM migration_added_columns WHERE revision='0132_dca_state_live_price'",
    )
    assert logged[0] == 0
    result = _alembic(url, "downgrade", REV_0131)
    assert result.returncode == 0, result.stderr
    assert _columns(url) >= LIVE_COLUMNS
    row = _fetchone(url, "SELECT live_price, live_session, close FROM dca_signal_states WHERE symbol='NVDA'")
    assert float(row[0]) == 175.75 and row[1] == "pre" and float(row[2]) == 186.64
    # Y 0083 sigue sin borrar la tabla adoptada al bajar.
    result = _alembic(url, "downgrade", REV_0083_DOWN)
    assert result.returncode == 0, result.stderr
    assert _columns(url) >= LIVE_COLUMNS


def test_offline_sql_coherent_no_duplicate_live_columns(tmp_path: Path) -> None:
    """--sql desde 0085: 0083 crea la tabla SIN las columnas live y 0132 las
    añade exactamente una vez (sin CREATE duplicado ni ADD doble)."""
    url = f"sqlite:///{(tmp_path / 'offline.db').as_posix()}"
    # Salto 0083: la tabla se crea SIN las columnas live (definicion congelada).
    result = _alembic(url, "upgrade", f"{REV_0083_DOWN}:0083_dca_signal_states", "--sql")
    assert result.returncode == 0, result.stderr
    sql = result.stdout
    create_pos = sql.find("CREATE TABLE dca_signal_states")
    assert create_pos != -1
    create_stmt = sql[create_pos : sql.find(";", create_pos)]
    assert "close_kind" not in create_stmt and "live_price" not in create_stmt
    # Salto 0132: las añade exactamente una vez, con su registro.
    result = _alembic(url, "upgrade", f"{REV_0131}:0132_dca_state_live_price", "--sql")
    assert result.returncode == 0, result.stderr
    sql = result.stdout
    assert sql.count("ADD COLUMN close_kind") == 1
    assert sql.count("ADD COLUMN live_price") == 1
    assert sql.count("CREATE TABLE migration_added_columns") == 1
    # El downgrade offline emite los DROP de columna y limpia SU registro,
    # pero nunca borra la tabla compartida (esta en Base.metadata).
    result = _alembic(url, "downgrade", "0132_dca_state_live_price:0131_documents_ingest_idx", "--sql")
    assert result.returncode == 0, result.stderr
    assert "DROP COLUMN close_kind" in result.stdout
    assert "DELETE FROM migration_added_columns" in result.stdout
    assert "DROP TABLE migration_added_columns" not in result.stdout


def test_migration_added_columns_matches_base_metadata(tmp_path: Path) -> None:
    """La tabla de registro esta en Base.metadata con el MISMO esquema que
    crea la cadena de migraciones: si faltara o difiriese, el ratchet de
    deriva (compare_metadata sobre el Postgres de CI) la marcaria como
    remove_table nueva, y create_all divergiria de la cadena Alembic."""
    import sqlalchemy as sa

    from app.models.entities import Base

    table = Base.metadata.tables.get("migration_added_columns")
    assert table is not None, "migration_added_columns debe estar en Base.metadata"
    # Esquema exacto que crea 0132 (y que create_all debe reproducir).
    expected = {"revision": 64, "table_name": 128, "column_name": 128}
    for name, length in expected.items():
        col = table.columns[name]
        assert isinstance(col.type, sa.String) and col.type.length == length
        assert col.primary_key and not col.nullable
    added = table.columns["added_at"]
    assert isinstance(added.type, sa.DateTime) and added.type.timezone is True
    assert not added.nullable and added.server_default is not None
    assert len(table.columns) == 4
    # Y la cadena fresca migrada a head crea la misma tabla con la misma PK.
    url = f"sqlite:///{(tmp_path / 'meta.db').as_posix()}"
    result = _alembic(url, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    engine = create_engine(url)
    try:
        reflected = sa.Table("migration_added_columns", sa.MetaData(), autoload_with=engine)
    finally:
        engine.dispose()
    assert {c.name for c in reflected.columns} == {c.name for c in table.columns}
    assert {c.name for c in reflected.primary_key.columns} == set(expected)
    for col in table.columns:
        assert str(reflected.columns[col.name].type) == str(col.type)
