"""0114: los FKs de la BD migrada coinciden con los modelos (ondelete y tenant).

Corre en el job 'Postgres migration round trip' sobre una BD scratch
desechable que crea y destruye el propio test. En sqlite/local hace skip:
sqlite no puede recrear FKs sin nombre y los tests hermeticos no enforzan
ondelete.
"""

import pytest

from tests.test_alembic_chain import _url_postgres_ci

_TABLAS_TENANT = [
    "decision_journal_entries",
    "expectation_reviews",
    "fundamental_assumptions",
    "fundamental_drivers",
    "fundamental_forecasts",
    "fundamental_model_versions",
]

_DELTYPE = {"c": "CASCADE", "n": "SET NULL", "a": None, "r": "RESTRICT", "d": "SET DEFAULT"}

_FKS_SQL = (
    "select c.conrelid::regclass::text, a.attname, c.conname, c.confdeltype, c.convalidated "
    "from pg_constraint c join pg_attribute a "
    "on a.attrelid = c.conrelid and a.attnum = c.conkey[1] "
    "where c.contype = 'f' and array_length(c.conkey, 1) = 1"
)


# Hosts y BD que el job `migrations` de .github/workflows/ci.yml expone al
# runner: el servicio postgres:17 se mapea a loopback y la BD es
# cavaai_research. Cualquier otra cosa en la URL admin NO es el Postgres de
# CI esperado y el fixture no debe ejecutar CREATE/DROP DATABASE sobre ella.
_HOSTS_CI = frozenset({"localhost", "127.0.0.1", "::1"})
_BD_ADMIN_CI = "cavaai_research"


def _validar_url_admin_ci(url: str) -> None:
    """Exige que la URL admin sea el Postgres del job de migraciones de CI.

    `_url_postgres_ci` solo comprueba CI=true y prefijo `postgresql`: una URL
    de staging o produccion colada en CAVAAI_ORIGINAL_DATABASE_URL pasaria ese
    guard y el CREATE/DROP DATABASE del fixture correria sobre ella. Aqui se
    exige driver postgres, host loopback (GitHub Actions mapea el servicio al
    runner) y la BD exacta del job. Los mensajes no incluyen la URL completa
    para no filtrar credenciales al log.
    """
    from sqlalchemy.engine.url import make_url

    try:
        parsed = make_url(url)
    except Exception as exc:
        raise ValueError(f"URL admin no parseable: {exc}") from exc
    if not parsed.drivername.startswith("postgresql"):
        raise ValueError(f"URL admin no es postgres: driver {parsed.drivername!r}")
    if (parsed.host or "") not in _HOSTS_CI:
        raise ValueError(f"host admin fuera de loopback de CI: {parsed.host!r}")
    if parsed.database != _BD_ADMIN_CI:
        raise ValueError(f"BD admin no es la del job de migraciones: {parsed.database!r}")
    # libpq honra ?host=, ?hostaddr= y ?service= POR ENCIMA de la autoridad de
    # la URL: con query, el destino real puede no ser el host que se acaba de
    # validar. El job de migraciones no usa query ninguna, asi que se bloquea
    # entera. Solo se listan las claves, nunca los valores (podrian ser rutas
    # o nombres internos).
    if parsed.query:
        raise ValueError(f"query no permitida en URL admin de CI: {sorted(parsed.query)}")


def _scratch(url: str):
    """Crea una BD scratch, la migra a head y devuelve (nombre, url, engine).

    Si algo falla entre el CREATE DATABASE y el final de la migracion, la
    scratch se destruye antes de propagar el error: una BD huerfana quedaria
    ocupando el servicio de CI y confundiendo el siguiente run.
    """
    import os
    import re
    import uuid

    import sqlalchemy as sa
    from alembic.config import Config

    from alembic import command
    from app.core.config import get_settings

    _validar_url_admin_ci(url)

    scratch = "fk114_" + uuid.uuid4().hex[:12]
    admin = sa.create_engine(url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(sa.text(f'CREATE DATABASE "{scratch}"'))
        base, sep, query = url.partition("?")
        base = re.sub(r"/[^/]+$", f"/{scratch}", base)
        scratch_url = base + (sep + query if sep else "")

        anterior = os.environ.get("DATABASE_URL", "")
        os.environ["DATABASE_URL"] = scratch_url
        get_settings.cache_clear()
        try:
            from tests.test_alembic_chain import VERSIONS_DIR

            cfg = Config(str(VERSIONS_DIR.parent.parent / "alembic.ini"))
            cfg.set_main_option("script_location", str(VERSIONS_DIR.parent))
            command.upgrade(cfg, "head")
        finally:
            if anterior:
                os.environ["DATABASE_URL"] = anterior
            else:
                # Antes estaba ausente (o vacia): no dejar la scratch sembrada.
                os.environ.pop("DATABASE_URL", None)
            get_settings.cache_clear()
    except BaseException:
        # Limpieza best-effort: si el DROP tambien falla no enmascara el
        # error original, que es el que explica por que fallo el fixture.
        try:
            with admin.connect() as conn:
                conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)'))
        except Exception:
            pass
        finally:
            admin.dispose()
        raise
    return scratch, scratch_url, admin


def _fks(engine_url: str) -> dict:
    import sqlalchemy as sa

    engine = sa.create_engine(engine_url)
    with engine.connect() as conn:
        rows = conn.execute(sa.text(_FKS_SQL)).all()
    engine.dispose()
    return {(r[0], r[1]): (r[2], r[3], r[4]) for r in rows}


def test_0114_fks_coinciden_con_modelos_en_ci_postgres():
    url = _url_postgres_ci()
    if not url:
        pytest.skip("Runs only on the CI Postgres migration service")
    import sqlalchemy as sa

    import app.models  # noqa: F401  (registra las tablas en Base.metadata)
    from app.core.database import Base

    scratch, scratch_url, admin = _scratch(url)
    try:
        fks = _fks(scratch_url)
        # Cada FK declarado en los modelos existe y con el ondelete declarado.
        ausentes = []
        distintos = []
        for tabla in Base.metadata.sorted_tables:
            for fk in tabla.foreign_keys:
                clave = (tabla.name, fk.parent.name)
                if clave not in fks:
                    ausentes.append(clave)
                elif fks[clave][1] != "a" and _DELTYPE[fks[clave][1]] != fk.ondelete or fks[clave][1] == "a" and fk.ondelete:
                    distintos.append((clave, fk.ondelete, fks[clave][1]))
        assert not ausentes, f"FKs de modelos ausentes en la BD migrada: {ausentes}"
        assert not distintos, f"ondelete distinto modelo vs BD: {distintos[:10]}"
        # Los 6 FKs de tenant llegaron con nombre explicito.
        for tabla in _TABLAS_TENANT:
            assert (tabla, "tenant_id") in fks
            assert fks[(tabla, "tenant_id")][0] == f"fk_{tabla}_tenant_id"
        # Patron prod-seguro: los 59 nuevos/reescritos quedan NOT VALID;
        # VALIDATE es paso operativo aparte, a decidir por Nico.
        no_validados = sorted(k for k, v in fks.items() if v[2] is False)
        assert len(no_validados) == 59, no_validados[:5]

        # El downgrade revierte: FKs de tenant fuera y los 53 de vuelta a NO ACTION.
        import os

        from alembic.config import Config

        from alembic import command
        from app.core.config import get_settings
        from tests.test_alembic_chain import VERSIONS_DIR

        anterior = os.environ.get("DATABASE_URL", "")
        os.environ["DATABASE_URL"] = scratch_url
        get_settings.cache_clear()
        try:
            cfg = Config(str(VERSIONS_DIR.parent.parent / "alembic.ini"))
            cfg.set_main_option("script_location", str(VERSIONS_DIR.parent))
            command.downgrade(cfg, "0113_add_model_indexes")
        finally:
            if anterior:
                os.environ["DATABASE_URL"] = anterior
            else:
                # Antes estaba ausente (o vacia): no dejar la scratch sembrada.
                os.environ.pop("DATABASE_URL", None)
            get_settings.cache_clear()
        fks_down = _fks(scratch_url)
        for tabla in _TABLAS_TENANT:
            assert (tabla, "tenant_id") not in fks_down
        rever = [k for k, v in fks_down.items() if v[2] is False]
        assert len(rever) == 53  # los recreados NO ACTION quedan NOT VALID
    finally:
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{scratch}"'))
        admin.dispose()


def test_0114_ondelete_rige_sin_validate_en_ci_postgres():
    """NOT VALID no aplaza la semantica: borrar un padre ya cascada/NULL-ea.

    Fija la afirmacion corregida del body: las acciones ON DELETE estan
    activas desde el DDL, con la constraint todavia NOT VALID.
    """
    url = _url_postgres_ci()
    if not url:
        pytest.skip("Runs only on the CI Postgres migration service")
    import re
    import uuid

    import sqlalchemy as sa

    scratch = "fk114del_" + uuid.uuid4().hex[:12]
    admin = sa.create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{scratch}"'))
    base, sep, query = url.partition("?")
    base = re.sub(r"/[^/]+$", f"/{scratch}", base)
    scratch_url = base + (sep + query if sep else "")
    try:
        import os

        from alembic.config import Config

        from alembic import command
        from app.core.config import get_settings
        from tests.test_alembic_chain import VERSIONS_DIR

        anterior = os.environ.get("DATABASE_URL", "")
        os.environ["DATABASE_URL"] = scratch_url
        get_settings.cache_clear()
        try:
            cfg = Config(str(VERSIONS_DIR.parent.parent / "alembic.ini"))
            cfg.set_main_option("script_location", str(VERSIONS_DIR.parent))
            command.upgrade(cfg, "head")
        finally:
            if anterior:
                os.environ["DATABASE_URL"] = anterior
            else:
                # Antes estaba ausente (o vacia): no dejar la scratch sembrada.
                os.environ.pop("DATABASE_URL", None)
            get_settings.cache_clear()

        engine = sa.create_engine(scratch_url)
        with engine.begin() as conn:
            # CASCADE: documents -> document_chunks (constraint NOT VALID)
            not_valid_antes = conn.execute(sa.text(
                "select convalidated from pg_constraint where conrelid = 'document_chunks'::regclass "
                "and contype = 'f'")).scalar()
            assert not_valid_antes is False
            doc_id = conn.execute(sa.text(
                "insert into documents (title, source_type, metadata, created_at, updated_at) "
                "values ('d114', 'test', '{}', now(), now()) returning id")).scalar()
            conn.execute(sa.text(
                "insert into document_chunks (document_id, chunk_index, text, token_count, metadata, "
                "created_at, updated_at) values (:d, 0, 'c0', 1, '{}', now(), now()), "
                "(:d, 1, 'c1', 1, '{}', now(), now())"), {"d": doc_id})
            conn.execute(sa.text("delete from documents where id = :d"), {"d": doc_id})
            restantes = conn.execute(sa.text(
                "select count(*) from document_chunks where document_id = :d"), {"d": doc_id}).scalar()
            assert restantes == 0, "CASCADE no actuo con la constraint NOT VALID"

            # SET NULL: research_sessions -> memory_items.research_session_id
            rs_id = conn.execute(sa.text(
                "insert into research_sessions (title, question, summary, status, claim_ids, "
                "memory_item_ids, source_ids, metadata, created_at, updated_at) values ('s114', "
                "'q', 'r', 'done', '[]', '[]', '[]', '{}', now(), now()) returning id")).scalar()
            mem_id = conn.execute(sa.text(
                "insert into memory_items (content, memory_type, scope, source_type, status, "
                "importance, metadata, research_session_id, created_at, updated_at) values ('m114', "
                "'fact', 'session', 'test', 'active', 1, '{}', :rs, now(), now()) returning id"),
                {"rs": rs_id}).scalar()
            conn.execute(sa.text("delete from research_sessions where id = :rs"), {"rs": rs_id})
            valor = conn.execute(sa.text(
                "select research_session_id from memory_items where id = :m"), {"m": mem_id}).scalar()
            assert valor is None, "SET NULL no actuo con la constraint NOT VALID"
        engine.dispose()
    finally:
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{scratch}"'))
        admin.dispose()
class _ConnFalsa:
    """Conexion minima que solo registra el SQL ejecutado (tests del guard)."""

    def __init__(self, registro):
        self._registro = registro

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, clausula, params=None):
        self._registro.append(str(clausula))


class _EngineFalso:
    """Engine minimo para probar _scratch sin Postgres (tests del guard)."""

    def __init__(self, registro):
        self._registro = registro
        self.disposed = False

    def connect(self):
        return _ConnFalsa(self._registro)

    def dispose(self):
        self.disposed = True


def test_validar_url_admin_ci_acepta_la_url_del_job():
    """La URL exacta del job `migrations` de ci.yml pasa el gate."""
    _validar_url_admin_ci("postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/cavaai_research")
    _validar_url_admin_ci("postgresql://portfolio:portfolio@localhost:5432/cavaai_research")


def test_validar_url_admin_ci_rechaza_host_remoto():
    with pytest.raises(ValueError, match="host admin"):
        _validar_url_admin_ci("postgresql+psycopg://u:p@db.staging.internal:5432/cavaai_research")


def test_validar_url_admin_ci_rechaza_otra_bd():
    with pytest.raises(ValueError, match="BD admin"):
        _validar_url_admin_ci("postgresql+psycopg://u:p@127.0.0.1:5432/produccion")


def test_validar_url_admin_ci_rechaza_driver_no_postgres():
    with pytest.raises(ValueError, match="no es postgres"):
        _validar_url_admin_ci("sqlite:///./local.db")


def test_scratch_no_crea_engine_si_la_url_no_es_ci(monkeypatch):
    """El gate corre antes de tocar la red: create_engine no debe llamarse."""
    import sqlalchemy as sa

    def _prohibido(*args, **kwargs):
        raise AssertionError("create_engine no debia llamarse con una URL no-CI")

    monkeypatch.setattr(sa, "create_engine", _prohibido)
    with pytest.raises(ValueError, match="host admin"):
        _scratch("postgresql+psycopg://u:p@db.prod.internal:5432/cavaai_research")


def test_scratch_destruye_la_bd_si_la_migracion_falla(monkeypatch):
    """Fallo a mitad del fixture: DROP de la scratch antes de propagar."""
    import os

    import sqlalchemy as sa

    from alembic import command

    registro = []
    engine = _EngineFalso(registro)
    monkeypatch.setattr(sa, "create_engine", lambda *args, **kwargs: engine)

    def _upgrade_que_falla(cfg, revision):
        raise RuntimeError("migracion rota")

    monkeypatch.setattr(command, "upgrade", _upgrade_que_falla)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./previo.db")

    with pytest.raises(RuntimeError, match="migracion rota"):
        _scratch("postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/cavaai_research")

    creates = [s for s in registro if s.startswith("CREATE DATABASE")]
    drops = [s for s in registro if s.startswith("DROP DATABASE")]
    assert len(creates) == 1 and len(drops) == 1
    nombre = creates[0].split('"')[1]
    assert nombre.startswith("fk114_")
    assert f'"{nombre}"' in drops[0] and "WITH (FORCE)" in drops[0]
    assert engine.disposed
    assert os.environ["DATABASE_URL"] == "sqlite:///./previo.db"
def test_validar_url_admin_ci_rechaza_query_bypass():
    """libpq honra ?host=, ?hostaddr= y ?service= sobre la autoridad: fuera."""
    for query in ("host=db.remoto.internal", "hostaddr=10.9.9.9", "service=pg_produccion"):
        with pytest.raises(ValueError, match="query"):
            _validar_url_admin_ci(f"postgresql+psycopg://u:p@127.0.0.1:5432/cavaai_research?{query}")


def test_scratch_restaura_database_url_ausente_tras_fallo(monkeypatch):
    """Si DATABASE_URL no existia antes, el fixture no la deja sembrada."""
    import os

    import sqlalchemy as sa

    from alembic import command

    engine = _EngineFalso([])
    monkeypatch.setattr(sa, "create_engine", lambda *args, **kwargs: engine)

    def _upgrade_que_falla(cfg, revision):
        raise RuntimeError("migracion rota")

    monkeypatch.setattr(command, "upgrade", _upgrade_que_falla)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="migracion rota"):
        _scratch("postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/cavaai_research")

    assert "DATABASE_URL" not in os.environ
