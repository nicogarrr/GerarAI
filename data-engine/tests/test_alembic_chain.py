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


def test_salto_huerfano_se_detecta(tmp_path):
    _migracion_sintetica(tmp_path, "0002_beta", "0002_beta", "0001_alpha")
    problemas = violaciones_cadena(tmp_path)
    assert any("no existe (salto o huerfano)" in p for p in problemas), problemas


def test_web_push_0101_round_trip_on_ci_postgres():
    """Real Postgres round trip in an isolated schema; CI migration job runs this file."""
    import importlib.util
    import os
    import uuid

    import pytest
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    url = os.environ.get('DATABASE_URL', '')
    if os.environ.get('CI') != 'true' or not url.startswith('postgresql'):
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
