"""Gate de la cadena de Alembic: un solo head, lineal y sin ciclos ni huerfanos.

Alembic indexa las migraciones por nombre de fichero: si dos ficheros comparten
prefijo de 4 digitos (`0047_*.py`) o la cadena se ramifica, `alembic heads` da
varios heads y `alembic upgrade head` aborta con "Multiple head revisions are
present for given argument 'head'". En FIX-1 tres hermanos 0047_* apuntando a
0046_inferred_inputs dejaron el contenedor de produccion sin arrancar
(`Dockerfile.prod` ejecuta `alembic upgrade head` antes de uvicorn).

Este test parsea `alembic/versions/*.py` con ast (sin ejecutar Alembic) y
vigila las invariantes de la cadena. Los casos negativos escriben migraciones
sinteticas en `tmp_path` y comprueban que cada regla detecta de verdad: un gate
que no sabe fallar no vigila nada.
"""

import ast
import re
from pathlib import Path

VERSIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"

# Deuda preexistente FUERA de la propiedad de FIX-1 (no se puede renombrar
# 0016 aqui): `0016_principle_jobs_and_portfolio_snapshots.py` declara
# revision `0016_principle_jobs_snapshots`, distinta del stem del fichero.
# La regla revision == stem es ESTRICTA; esta lista es exactamente la deuda
# conocida. Cualquier violacion NUEVA falla el test, y arreglar 0016 tambien
# (hay que vaciar la lista a proposito: es el recordatorio de que el nombre
# del fichero y la revision deben caminar juntos).
DEUDA_CONOCIDA = [
    "0016_principle_jobs_and_portfolio_snapshots.py: "
    "revision '0016_principle_jobs_snapshots' != fichero '0016_principle_jobs_and_portfolio_snapshots'",
]

# Alembic crea alembic_version.version_num como VARCHAR(32): una revision mas
# larga NO se puede registrar en ninguna base de datos (PostgreSQL aborta el
# UPDATE de version con StringDataRightTruncation). Medido en el restore drill
# de CI (seed -> alembic upgrade head) con 0108_add_database_check_constraints,
# 35 caracteres, rojo en todos los runs del 2026-10-30/31. Renombrar una
# revision ya aplicada rompe el historial, asi que el sitio barato de pillarlo
# es este gate, antes del merge.
_LIMITE_VERSION_NUM = 32

_PATRON_PREFIJO = re.compile(r"^\d{4}_.+")
_AUSENTE = object()


def _constante(nodo: ast.AST) -> object:
    """Valor de una asignacion a nivel de modulo: str, None o AUSENTE."""
    if isinstance(nodo, ast.Constant):
        return nodo.value
    return _AUSENTE


def _leer_declaraciones(path: Path) -> tuple[object, object]:
    """(revision, down_revision) declarados a nivel de modulo de un fichero."""
    arbol = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    revision: object = _AUSENTE
    down_revision: object = _AUSENTE
    for sentencia in arbol.body:
        if isinstance(sentencia, ast.Assign):
            nombres = [t.id for t in sentencia.targets if isinstance(t, ast.Name)]
            valor = _constante(sentencia.value)
        elif isinstance(sentencia, ast.AnnAssign) and isinstance(sentencia.target, ast.Name):
            nombres = [sentencia.target.id]
            valor = _constante(sentencia.value) if sentencia.value is not None else _AUSENTE
        else:
            continue
        if "revision" in nombres:
            revision = valor
        if "down_revision" in nombres:
            down_revision = valor
    return revision, down_revision


def violaciones_cadena(versions_dir: Path) -> list[str]:
    """Invariantees de la cadena de migraciones, como mensajes accionables.

    Reglas: exactamente un head; revision == stem del fichero; prefijo de 4
    digitos unico; exactamente un down_revision = None (la raiz); cada revision
    es down_revision de exactamente una migracion (linealidad); ningun
    down_revision huerfano (no apunta a una revision inexistente) y ninguna
    revision inalcanzable desde la raiz (ciclo o rama colgante).
    """
    entradas: list[tuple[Path, str, object, object]] = []
    problemas: list[str] = []
    for path in sorted(versions_dir.glob("*.py")):
        revision, down_revision = _leer_declaraciones(path)
        entradas.append((path, path.stem, revision, down_revision))
        if revision is _AUSENTE or not isinstance(revision, str):
            problemas.append(f"{path.name}: sin revision de cadena str")
            continue
        if down_revision is _AUSENTE:
            problemas.append(f"{path.name}: sin down_revision declarado (usa down_revision = None)")
            continue
        if down_revision is not None and not isinstance(down_revision, str):
            problemas.append(f"{path.name}: down_revision ni str ni None")
            continue
        if revision != path.stem:
            problemas.append(f"{path.name}: revision '{revision}' != fichero '{path.stem}'")
        if isinstance(revision, str) and len(revision) > _LIMITE_VERSION_NUM:
            problemas.append(
                f"{path.name}: revision '{revision}' mide {len(revision)} caracteres "
                f"y alembic_version.version_num es VARCHAR({_LIMITE_VERSION_NUM}): "
                "al aplicarla, el UPDATE de version aborta (StringDataRightTruncation)"
            )
        if not _PATRON_PREFIJO.match(path.stem):
            problemas.append(f"{path.name}: el stem no empieza por prefijo de 4 digitos y '_'")

    prefijos: dict[str, list[str]] = {}
    stems: dict[str, str] = {}
    for path, stem, _revision, _down in entradas:
        prefijos.setdefault(stem[:4], []).append(path.name)
        stems[path.name] = stem
    for prefijo, nombres in sorted(prefijos.items()):
        if len(nombres) > 1:
            problemas.append(f"prefijo {prefijo} repetido en {', '.join(sorted(nombres))}")

    revisiones: dict[str, Path] = {}
    for path, _stem, revision, _down in entradas:
        if isinstance(revision, str) and revision is not _AUSENTE:
            if revision in revisiones:
                problemas.append(f"revision '{revision}' declarada en {revisiones[revision].name} y {path.name}")
            revisiones[revision] = path

    usadas: list[str] = []
    raices: list[str] = []
    hijos: dict[str, list[str]] = {}
    for path, _stem, revision, down_revision in entradas:
        if not isinstance(revision, str) or revision is _AUSENTE:
            continue
        if down_revision is _AUSENTE:
            continue
        if down_revision is None:
            raices.append(revision)
        elif isinstance(down_revision, str):
            usadas.append(down_revision)
            hijos.setdefault(down_revision, []).append(revision)
            if down_revision not in revisiones:
                problemas.append(f"{path.name}: down_revision '{down_revision}' no existe (salto o huerfano)")

    heads = sorted(set(revisiones) - set(usadas))
    if len(heads) != 1:
        problemas.append(f"hay {len(heads)} heads ({', '.join(heads)}); debe haber exactamente 1")
    if len(raices) != 1:
        problemas.append(f"hay {len(raices)} migraciones con down_revision = None; debe haber exactamente 1")

    for padre, hijos_del_padre in sorted(hijos.items()):
        if len(hijos_del_padre) > 1:
            problemas.append(
                f"la cadena se ramifica en '{padre}': down_revision de {', '.join(sorted(hijos_del_padre))}"
            )

    if len(raices) == 1:
        vistas: set[str] = set()
        cola = [raices[0]]
        while cola:
            actual = cola.pop()
            if actual in vistas:
                continue
            vistas.add(actual)
            cola.extend(hijos.get(actual, []))
        inalcanzables = sorted(set(revisiones) - vistas)
        if inalcanzables:
            problemas.append(f"revisiones inalcanzables desde la raiz (ciclo o rama): {', '.join(inalcanzables)}")

    return sorted(problemas)


def _migracion_sintetica(versions_dir: Path, stem: str, revision: str, down_revision: str | None) -> Path:
    down_repr = repr(down_revision)
    (versions_dir / f"{stem}.py").write_text(
        f'"""migracion sintetica para el gate de cadena."""\n'
        f"\n"
        f'revision = "{revision}"\n'
        f"down_revision = {down_repr}\n"
        f"\n"
        f"\n"
        f"def upgrade() -> None:\n"
        f"    pass\n"
        f"\n"
        f"\n"
        f"def downgrade() -> None:\n"
        f"    pass\n",
        encoding="utf-8",
    )
    return versions_dir / f"{stem}.py"


def _cadena_valida(versions_dir: Path) -> None:
    _migracion_sintetica(versions_dir, "0001_alpha", "0001_alpha", None)
    _migracion_sintetica(versions_dir, "0002_beta", "0002_beta", "0001_alpha")
    _migracion_sintetica(versions_dir, "0003_gamma", "0003_gamma", "0002_beta")


def test_cadena_real_un_head_lineal_y_sin_huerfanos():
    assert violaciones_cadena(VERSIONS_DIR) == DEUDA_CONOCIDA


def test_cadena_sintetica_valida_no_da_problemas(tmp_path):
    _cadena_valida(tmp_path)
    assert violaciones_cadena(tmp_path) == []


def test_dos_heads_se_detectan(tmp_path):
    _migracion_sintetica(tmp_path, "0001_alpha", "0001_alpha", None)
    _migracion_sintetica(tmp_path, "0002_beta", "0002_beta", "0001_alpha")
    _migracion_sintetica(tmp_path, "0003_gamma", "0003_gamma", "0001_alpha")
    problemas = violaciones_cadena(tmp_path)
    assert any("heads" in p for p in problemas), problemas
    assert any("ramifica" in p for p in problemas), problemas


def test_prefijo_de_4_digitos_duplicado_se_detecta(tmp_path):
    _migracion_sintetica(tmp_path, "0001_alpha", "0001_alpha", None)
    _migracion_sintetica(tmp_path, "0001_beta", "0001_beta", "0001_alpha")
    problemas = violaciones_cadena(tmp_path)
    assert any("prefijo 0001 repetido" in p for p in problemas), problemas


def test_una_cadena_limpia_no_da_problemas(tmp_path):
    _cadena_valida(tmp_path)
    assert violaciones_cadena(tmp_path) == []


def test_revision_distinta_del_nombre_de_fichero_se_detecta(tmp_path):
    _migracion_sintetica(tmp_path, "0001_alpha", "0001_delta", None)
    problemas = violaciones_cadena(tmp_path)
    assert any("revision '0001_delta' != fichero '0001_alpha'" in p for p in problemas), problemas


def test_ciclo_se_detecta(tmp_path):
    _migracion_sintetica(tmp_path, "0001_alpha", "0001_alpha", None)
    _migracion_sintetica(tmp_path, "0002_beta", "0002_beta", "0003_gamma")
    _migracion_sintetica(tmp_path, "0003_gamma", "0003_gamma", "0002_beta")
    problemas = violaciones_cadena(tmp_path)
    assert any("inalcanzables" in p for p in problemas), problemas


def test_revision_mas_larga_que_varchar32_se_detecta(tmp_path):
    _migracion_sintetica(tmp_path, "0001_alpha", "0001_alpha", None)
    _migracion_sintetica(
        tmp_path,
        "0002_una_revision_con_nombre_larguisimo_de_mas",
        "0002_una_revision_con_nombre_larguisimo_de_mas",
        "0001_alpha",
    )
    problemas = violaciones_cadena(tmp_path)
    assert any("VARCHAR(32)" in p for p in problemas), problemas


def test_salto_huerfano_se_detecta(tmp_path):
    _migracion_sintetica(tmp_path, "0002_beta", "0002_beta", "0001_alpha")
    problemas = violaciones_cadena(tmp_path)
    assert any("no existe (salto o huerfano)" in p for p in problemas), problemas


def test_web_push_0101_round_trip_on_ci_postgres():
    """Real Postgres round trip in an isolated schema; CI migration job runs this file."""
    import importlib.util
    import uuid

    import pytest
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    url = _url_postgres_ci()
    if not url:
        pytest.skip('Runs only on the CI Postgres migration service')
    schema = 'push_0101_test_' + uuid.uuid4().hex
    path = VERSIONS_DIR / '0101_web_push.py'
    spec = importlib.util.spec_from_file_location('push_0101_ci', path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            transaction = conn.begin()
            try:
                conn.execute(sa.schema.CreateSchema(schema))
                conn.execute(sa.text("SELECT set_config('search_path', :schema, true)"), {'schema': schema})
                conn.execute(sa.text('CREATE TABLE tenants (id INTEGER PRIMARY KEY)'))
                module.op = Operations(MigrationContext.configure(conn))
                module.upgrade()
                for table in ('push_subscriptions', 'push_preferences'):
                    inspector = sa.inspect(conn)
                    assert table in inspector.get_table_names(schema=schema)
                    assert inspector.get_foreign_keys(table, schema=schema)
                    assert inspector.get_unique_constraints(table, schema=schema)
                module.upgrade()
                module.downgrade()
                assert not {'push_subscriptions', 'push_preferences'} & set(sa.inspect(conn).get_table_names(schema=schema))
                module.upgrade()
                assert {'push_subscriptions', 'push_preferences'} <= set(sa.inspect(conn).get_table_names(schema=schema))
            finally:
                transaction.rollback()  # Removes only this test's temporary schema.
    finally:
        engine.dispose()


BASELINE_DERIVA = Path(__file__).resolve().parent / "fixtures" / "alembic_drift_baseline.txt"


def _url_postgres_ci() -> str:
    """URL Postgres del job de CI, o "" si no aplica.

    tests/conftest.py fuerza un sqlite hermetico en DATABASE_URL para toda la
    suite; la URL real del job (cuando existe) queda preservada en
    CAVAAI_ORIGINAL_DATABASE_URL. Sin este rescate los tests gated a CI
    Postgres quedaban muertos: su guard leia el sqlite forzado y hacian skip
    incluso en el job 'Postgres migration round trip'.
    """
    import os

    if os.environ.get("CI") != "true":
        return ""
    url = os.environ.get("CAVAAI_ORIGINAL_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
    return url if url.startswith("postgresql") else ""


def _deriva_actual(url: str) -> list[str]:
    """Diffs models<->migraciones sobre una BD scratch migrada a head.

    Misma comparacion que `alembic check` (compare_metadata con el
    target_metadata de env.py), pero devolviendo los diffs en repr ordenado:
    capturar el log de alembic.autogenerate.compare no es fiable aqui porque
    env.py aplica fileConfig en cada comando y se lleva por delante los
    handlers instalados por el test.
    """
    import os
    import re
    import uuid

    import sqlalchemy as sa
    from alembic.autogenerate import compare_metadata
    from alembic.config import Config
    from alembic.migration import MigrationContext

    from alembic import command
    from app.core.config import get_settings
    from app.core.database import Base

    scratch = "migdrift_" + uuid.uuid4().hex[:12]
    engine = sa.create_engine(url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{scratch}"'))  # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text -- fixture: nombre scratch uuid-hex generado por el propio test, sin input externo; BD efimera de CI

    anterior = os.environ.get("DATABASE_URL", "")
    try:
        # Sustituye solo la base de datos, conservando la query verbatim (un
        # socket unix lleva %2F al re-serializar y ConfigParser lo rechaza).
        base, sep, query = url.partition("?")
        base = re.sub(r"/[^/]+$", f"/{scratch}", base)
        scratch_url = base + (sep + query if sep else "")
        os.environ["DATABASE_URL"] = scratch_url
        get_settings.cache_clear()

        cfg = Config(str(VERSIONS_DIR.parent.parent / "alembic.ini"))
        cfg.set_main_option("script_location", str(VERSIONS_DIR.parent))
        command.upgrade(cfg, "head")

        scratch_engine = sa.create_engine(scratch_url)
        try:
            with scratch_engine.connect() as conn:
                ctx = MigrationContext.configure(
                    connection=conn, opts={"target_metadata": Base.metadata}
                )
                diffs = compare_metadata(ctx, Base.metadata)
        finally:
            scratch_engine.dispose()
        # Los repr de ReadOnlyColumnCollection llevan direccion de memoria:
        # se enmascara para que la baseline sea determinista.
        return sorted(
            re.sub(r"0x[0-9a-fA-F]+", "0x_", repr(diff)) for diff in diffs
        )
    finally:
        os.environ["DATABASE_URL"] = anterior
        get_settings.cache_clear()
        with engine.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{scratch}"'))  # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text -- fixture: nombre scratch uuid-hex generado por el propio test, sin input externo; BD efimera de CI
        engine.dispose()


def test_deriva_modelos_migraciones_no_cambia_en_ci_postgres():
    """Rachet de deriva esquema models<->migraciones; solo en el Postgres de CI.

    compare_metadata(Base.metadata, BD migrada a head) mide la misma deriva
    que `alembic check`. Hoy hay deriva conocida (tablas muertas de backtests,
    indices que los modelos declaran y ninguna migracion crea, NOT NULL
    ajustados sin migracion): esta fijada, linea a linea, en
    fixtures/alembic_drift_baseline.txt. El test falla si aparece deriva
    NUEVA y tambien si desaparece deuda (quien la arregle regenera la
    baseline en el mismo PR, para que el numero solo baje a proposito):

        CI=true DATABASE_URL=postgresql+psycopg://... python - <<'EOF'
        from pathlib import Path
        import tests.test_alembic_chain as t
        lineas = t._deriva_actual(t._url_postgres_ci())
        Path("tests/fixtures/alembic_drift_baseline.txt").write_text(
            "\\n".join(lineas) + "\\n", encoding="utf-8")
        EOF

    Corre en el job 'Postgres migration round trip' sobre una BD scratch
    desechable que crea y destruye el propio test.
    """
    import pytest

    url = _url_postgres_ci()
    if not url:
        pytest.skip("Runs only on the CI Postgres migration service")

    actuales = _deriva_actual(url)
    esperados = BASELINE_DERIVA.read_text(encoding="utf-8").splitlines()
    if actuales != esperados:
        nuevos = sorted(set(actuales) - set(esperados))
        curados = sorted(set(esperados) - set(actuales))
        detalle = ["deriva models<->migraciones distinta de la baseline:"]
        detalle += [f"  NUEVA: {m}" for m in nuevos[:10]]
        detalle += [f"  RESUELTA (regenera baseline): {m}" for m in curados[:10]]
        raise AssertionError("\n".join(detalle))

