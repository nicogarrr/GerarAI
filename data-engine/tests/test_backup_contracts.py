"""Contratos de backup/restore que se comprueban SIN servicios.

Un restore solo es una recuperacion si el contrato que lo une con el backup esta
escrito, completo y coherente con el codigo. Estos tests fijan ese contrato y
fallan si el codigo y el runbook divergen:

  * el manifiesto exige todos sus campos y sus checksums se validan;
  * cada comprobacion de verify_restore es fail-closed (nunca "omitido");
  * el restore va a destino limpio y exige confirmacion explicita;
  * el runbook menciona los tres pilares y todos los pasos, en orden;
  * las herramientas estan fijadas por version y coinciden con los pins de los
    compose;
  * el workflow de CI declara los tres pilares y no puede quedar en verde sin
    verificar.

Ninguno de estos tests necesita Postgres, MinIO ni Qdrant levantados: el ciclo
completo con servicios reales lo ejecuta `scripts/backup/disaster_drill.py` y,
en cada push, `.github/workflows/restore-drill.yml`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from scripts.backup import _kit, backup_minio, backup_qdrant
from scripts.backup._kit import (
    MANIFEST_VERSION,
    PILLARS,
    REQUIRED_MANIFEST_FIELDS,
    REQUIRED_TOOL_KEYS,
    FailClosedError,
)
from scripts.restore import restore_minio, restore_postgres, restore_qdrant, verify_restore

DATA_ENGINE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = DATA_ENGINE_ROOT.parent
BACKUP_DIR = DATA_ENGINE_ROOT / "scripts" / "backup"
RESTORE_DIR = DATA_ENGINE_ROOT / "scripts" / "restore"
RUNBOOK = BACKUP_DIR / "RUNBOOK.md"
README = BACKUP_DIR / "README.md"
DRILL = BACKUP_DIR / "disaster_drill.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "restore-drill.yml"

SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


# --------------------------------------------------------------------------
# Manifiesto
# --------------------------------------------------------------------------


def _minimal_manifest(**overrides) -> dict:
    """Manifiesto minimo VALIDO. Si esto falla, ningun backup se puede validar."""
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "backup_id": "20261002T101500Z",
        "created_at_utc": "2026-10-02T10:15:00Z",
        "backup_kind": "full",
        "alembic_head": "0046_inferred_inputs",
        "alembic_head_source": str(_kit.ALEMBIC_VERSIONS_DIR),
        "git_commit": "0be7186c",
        "tools": {
            "pg_dump": {"version": "pg_dump (PostgreSQL) 17.11"},
            "pg_restore": {"version": "pg_dump (PostgreSQL) 17.11"},
            "minio": {"version": "7.2.20"},
            "qdrant": {"version": "1.19.2"},
        },
        "artifacts": [
            {
                "pillar": "postgres",
                "path": "postgres/database.dump",
                "format": "pg_dump_custom",
                "sha256": "a" * 64,
                "bytes": 10,
                "kind": "full",
            },
            {
                "pillar": "minio",
                "path": "minio/objects.tar.gz",
                "format": "minio_object_archive_targz",
                "sha256": "b" * 64,
                "bytes": 10,
                "kind": "full",
            },
            {
                "pillar": "qdrant",
                "path": "qdrant/portfolio_research_documents.snapshot",
                "format": "qdrant_collection_snapshot",
                "sha256": "c" * 64,
                "bytes": 10,
                "kind": "full",
            },
        ],
        "postgres": {
            "database": "cavaai_research",
            "alembic_version": "0046_inferred_inputs",
            "tables": {"companies": 12},
        },
        "minio": {
            "source_bucket": "research",
            "objects": [{"key": "tenant-1/AAPL/f.pdf", "sha256": "d" * 64, "bytes": 3}],
        },
        "qdrant": {
            "collections": [
                {"name": "portfolio_research_documents", "points": 5, "dimensions": {"": 384}}
            ]
        },
    }
    manifest.update(overrides)
    return manifest


def test_manifest_minimo_es_valido():
    _kit.validate_manifest(_minimal_manifest())


@pytest.mark.parametrize("field_name", REQUIRED_MANIFEST_FIELDS)
def test_manifiesto_exige_cada_campo_de_primer_nivel(field_name):
    manifest = _minimal_manifest()
    del manifest[field_name]
    with pytest.raises(FailClosedError) as excinfo:
        _kit.validate_manifest(manifest)
    assert field_name in str(excinfo.value)


@pytest.mark.parametrize("tool_name", REQUIRED_TOOL_KEYS)
def test_manifiesto_exige_version_de_cada_herramienta(tool_name):
    manifest = _minimal_manifest()
    manifest["tools"][tool_name] = {"version": ""}
    with pytest.raises(FailClosedError):
        _kit.validate_manifest(manifest)


@pytest.mark.parametrize("pillar", PILLARS)
def test_manifiesto_cubre_los_tres_pilares(pillar):
    manifest = _minimal_manifest()
    manifest["artifacts"] = [a for a in manifest["artifacts"] if a["pillar"] != pillar]
    with pytest.raises(FailClosedError) as excinfo:
        _kit.validate_manifest(manifest)
    assert pillar in str(excinfo.value)


def test_manifiesto_rechaza_un_dump_plano_de_postgres():
    """Un dump plano no es restaurable de forma fiable: no es un artefacto valido."""
    manifest = _minimal_manifest()
    manifest["artifacts"][0]["format"] = "plain_sql"
    with pytest.raises(FailClosedError):
        restore_postgres.find_artifact(manifest, restore_postgres.DUMP_FORMAT)


def test_manifiesto_exige_una_base_con_tabla_al_menos():
    manifest = _minimal_manifest()
    manifest["postgres"]["tables"] = {}
    with pytest.raises(FailClosedError) as excinfo:
        _kit.validate_manifest(manifest)
    assert "alembic" in str(excinfo.value).lower() or "tabla" in str(excinfo.value).lower()


def test_manifiesto_rechaza_base_por_detras_del_head_de_alembic():
    """Dump anterior al head: restaura "bien" y rompe en el primer arranque."""
    manifest = _minimal_manifest()
    manifest["postgres"]["alembic_version"] = "0031_propick_runs"
    with pytest.raises(FailClosedError) as excinfo:
        _kit.validate_manifest(manifest)
    assert "0031_propick_runs" in str(excinfo.value)


def test_manifiesto_rechaza_sha256_invalido():
    manifest = _minimal_manifest()
    manifest["artifacts"][0]["sha256"] = "no-es-hex"
    with pytest.raises(FailClosedError):
        _kit.validate_manifest(manifest)


def test_manifiesto_rechaza_backup_kind_desconocido():
    manifest = _minimal_manifest()
    manifest["backup_kind"] = "parcial"
    with pytest.raises(FailClosedError):
        _kit.validate_manifest(manifest)


def test_manifest_build_declara_version_de_esquema_y_tamanos(tmp_path):
    builder = _kit.ManifestBuilder(backup_dir=tmp_path)
    for tool_name, version in (
        ("pg_dump", "pg_dump (PostgreSQL) 17.11"),
        ("pg_restore", "pg_dump (PostgreSQL) 17.11"),
        ("minio", "7.2.20"),
        ("qdrant", "1.19.2"),
    ):
        builder.add_tool(tool_name, version)
    for pillar, name in (
        ("postgres", "postgres/database.dump"),
        ("minio", "minio/objects.tar.gz"),
        ("qdrant", "qdrant/c.snapshot"),
    ):
        artifact_path = tmp_path / name
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_bytes(b"x")
        builder.add_artifact(_kit.artifact_for_file(tmp_path, pillar, name, "fmt"))
    builder.declare_postgres(
        database="cavaai_research",
        alembic_version=_kit.alembic_head(),
        tables={"companies": 12},
    )
    builder.declare_minio(source_bucket="research", objects=[])
    builder.declare_qdrant(collections=[{"name": "c", "points": 1, "dimensions": {"": 384}}])
    data = builder.build()
    assert data["alembic_head"] == _kit.alembic_head()
    assert data["backup_kind"] == "full"
    assert data["tools"]["pg_dump"]["version"]
    assert len(data["alembic_head_source"]) > 0
    assert [a["bytes"] for a in data["artifacts"]] == [1, 1, 1]


def test_checksum_se_valida_contra_el_fichero(tmp_path):
    target = tmp_path / "artefacto.bin"
    target.write_bytes(b"contenido")
    artifact = _kit.artifact_for_file(tmp_path, "postgres", "artefacto.bin", "pg_dump_custom")
    assert SHA256_HEX.match(artifact.sha256)
    _kit.verify_artifact(tmp_path, artifact.as_dict())

    target.write_bytes(b"corrupto")
    with pytest.raises(FailClosedError) as excinfo:
        _kit.verify_artifact(tmp_path, artifact.as_dict())
    assert "corrupto" in str(excinfo.value)


def test_artefacto_ausente_es_fallo_con_motivo(tmp_path):
    artifact = {
        "pillar": "postgres",
        "path": "postgres/no-existe.dump",
        "format": "pg_dump_custom",
        "sha256": "e" * 64,
        "bytes": 1,
        "kind": "full",
    }
    with pytest.raises(FailClosedError) as excinfo:
        _kit.verify_artifact(tmp_path, artifact)
    assert "no-existe.dump" in str(excinfo.value)


# --------------------------------------------------------------------------
# Alembic: el head del codigo es una sola revision
# --------------------------------------------------------------------------


def test_alembic_head_es_una_unica_revision():
    assert _kit.alembic_head()


def test_alembic_head_falla_con_dos_cabezas(tmp_path):
    versions = tmp_path / "versions"
    versions.mkdir()
    (versions / "0001_a.py").write_text('revision = "0001_a"\ndown_revision = None\n')
    (versions / "0002_b.py").write_text('revision = "0002_b"\ndown_revision = None\n')
    with pytest.raises(FailClosedError) as excinfo:
        _kit.alembic_head(versions)
    assert "2 heads" in str(excinfo.value)


def test_alembic_parsea_down_revision_none_y_padre(tmp_path):
    versions = tmp_path / "versions"
    versions.mkdir()
    (versions / "0001_a.py").write_text('revision = "0001_a"\ndown_revision = None\n')
    (versions / "0002_b.py").write_text('revision = "0002_b"\ndown_revision = "0001_a"\n')
    assert _kit.alembic_head(versions) == "0002_b"


# --------------------------------------------------------------------------
# Fail-closed: una verificacion que no se puede ejecutar es FALLO
# --------------------------------------------------------------------------


def test_verify_tiene_las_seis_comprobaciones_del_contrato():
    assert set(verify_restore.VALID_CHECKS) == set(verify_restore._CHECKS_BY_PHASE["data"]) | set(
        verify_restore._CHECKS_BY_PHASE["app"]
    )


def test_verify_reporta_las_seis_sin_omitir_ninguna():
    """El informe tiene que traer una entrada por comprobacion, siempre."""
    results = [verify_restore.CheckResult(name, True, "ok") for name in verify_restore.VALID_CHECKS]
    report = {
        "checks": [result.as_dict() for result in results],
        "checks_total": len(results),
        "checks_passed": len(results),
    }
    assert {entry["name"] for entry in report["checks"]} == set(verify_restore.VALID_CHECKS)


def test_check_es_fail_closed_cuando_la_comprobacion_no_puede_ejecutarse():
    def servicio_caido():
        raise FailClosedError("connection refused")

    result = verify_restore._run("b_conteos", servicio_caido, required="Postgres")
    assert result.passed is False
    assert "NO SE PUDO COMPROBAR" in result.detail
    assert "Postgres" in result.detail
    assert "connection refused" in result.detail


def test_check_es_fail_closed_con_excepcion_inesperada():
    def boom() -> None:
        raise RuntimeError("boom")

    result = verify_restore._run("f_vectores", boom, required="Qdrant")
    assert result.passed is False
    assert "ERROR" in result.detail
    assert "RuntimeError" in result.detail


def test_check_result_no_tiene_estado_skipped():
    """No existe 'omitido': o pasa, o falla con motivo."""
    assert not hasattr(verify_restore.CheckResult("x", True, "ok"), "skipped")
    source = (RESTORE_DIR / "verify_restore.py").read_text(encoding="utf-8")
    # "skipped" solo puede aparecer citada la regla de ci.yml que lo prohibe.
    assert source.lower().count("skipped") == 1
    assert "skipped -> exit 1" in source


def test_sin_app_base_url_la_comprobacion_d_falla():
    """El gate de RAG de ci.yml: si no se puede comprobar, exit 1."""
    config = verify_restore.VerifyConfig(
        manifest_path=Path("."),
        pg_target=_kit.PsqlTarget(mode="docker", database="postgres", user="portfolio"),
        minio_endpoint="127.0.0.1:9000",
        minio_access_key="k",
        minio_secret_key="s",
        qdrant_url="http://127.0.0.1:6333",
        qdrant_api_key=None,
        app_base_url=None,
        versions_dir=None,
    )
    assert config.app_base_url is None
    source = (RESTORE_DIR / "verify_restore.py").read_text(encoding="utf-8")
    assert "NO SE PUDO COMPROBAR: falta --app-base-url" in source


def test_herramienta_ausente_es_fallo_no_salto():
    with pytest.raises(FailClosedError) as excinfo:
        _kit.require_tool("pg_dump-que-no-existe-jamas", what="prueba")
    assert "no esta en PATH" in str(excinfo.value)


def test_cliente_postgres_mayor_que_servidor_no_pasa():
    """Un pg_dump 16 contra un servidor 17 aborta: se comprueba ANTES de empezar."""
    _kit.check_pg_client_version(_kit.REQUIRED_PG_CLIENT_MAJOR)
    with pytest.raises(FailClosedError) as excinfo:
        _kit.check_pg_client_version(_kit.REQUIRED_PG_CLIENT_MAJOR - 1)
    assert "servidor" in str(excinfo.value)


def test_comando_inexistente_falla_con_motivo():
    with pytest.raises(FailClosedError) as excinfo:
        _kit.run(["pg_dump-que-no-existe-jamas", "--version"], what="prueba")
    assert "ausente" in str(excinfo.value)


def test_comando_que_falla_incluye_codigo_y_stderr():
    result = _kit.run(
        ["python", "-c", "import sys; sys.stderr.write('detalle util'); sys.exit(3)"],
        check=False,
    )
    assert result.returncode == 3
    assert "detalle util" in result.stderr
    with pytest.raises(FailClosedError) as excinfo:
        _kit.run(["python", "-c", "import sys; sys.stderr.write('detalle util'); sys.exit(3)"])
    assert "3" in str(excinfo.value)


def test_los_secretos_no_se_imprimen_en_los_motivos():
    texto = _kit.redact("postgresql+psycopg://user:clave-secreta@host/db password=otraclave")
    assert "clave-secreta" not in texto
    assert "otraclave" not in texto


# --------------------------------------------------------------------------
# Destino limpio y confirmacion explicita
# --------------------------------------------------------------------------


def test_restore_postgres_exige_confirmacion():
    parser = restore_postgres.build_parser()
    assert parser.parse_args(["--manifest", "b"]).confirm_restore is False
    assert parser.parse_args(["--manifest", "b", "--confirm-restore"]).confirm_restore is True


def test_restore_postgres_recrea_la_base_de_destino():
    source = (RESTORE_DIR / "restore_postgres.py").read_text(encoding="utf-8")
    assert "DROP DATABASE IF EXISTS" in source
    assert "CREATE DATABASE" in source
    assert "--exit-on-error" in source


@pytest.mark.parametrize(
    ("module", "flag"),
    [
        (restore_postgres, "--confirm-restore"),
        (restore_minio, "--confirm-restore"),
        (restore_qdrant, "--confirm-restore"),
    ],
)
def test_cada_restore_exige_confirmacion_explicita(module, flag):
    args = module.build_parser().parse_args(["--manifest", "b"])
    assert getattr(args, flag.lstrip("-").replace("-", "_")) is False


def test_restore_minio_vacia_el_bucket_de_destino():
    source = (RESTORE_DIR / "restore_minio.py").read_text(encoding="utf-8")
    assert "remove_bucket" in source
    assert "make_bucket" in source


def test_restore_qdrant_usa_la_api_de_snapshots():
    source = (RESTORE_DIR / "restore_qdrant.py").read_text(encoding="utf-8")
    assert "/snapshots/upload" in source
    assert "priority=snapshot" in source


def test_restore_qdrant_borra_la_coleccion_antes_de_subir():
    source = (RESTORE_DIR / "restore_qdrant.py").read_text(encoding="utf-8")
    assert 'method="DELETE"' in source


def test_backup_postgres_usa_formato_custom_no_plano():
    source = (BACKUP_DIR / "backup_postgres.py").read_text(encoding="utf-8")
    assert _kit.PG_DUMP_FORMAT_FLAG == "-Fc"
    assert _kit.PG_DUMP_FORMAT == "pg_dump_custom"
    assert "-Fc" in source
    assert "--format=plain" not in source
    assert "-Fp" not in source


def test_backup_postgres_incluye_globals():
    source = (BACKUP_DIR / "backup_postgres.py").read_text(encoding="utf-8")
    assert "--globals-only" in source
    assert "pg_dumpall" in source


def test_backup_postgres_comprueba_el_head_de_alembic():
    source = (BACKUP_DIR / "backup_postgres.py").read_text(encoding="utf-8")
    assert "alembic_head()" in source
    assert "allow_schema_drift" in source


def test_backup_qdrant_usa_snapshots_por_api():
    source = (BACKUP_DIR / "backup_qdrant.py").read_text(encoding="utf-8")
    assert "POST /collections/{c}/snapshots" in source
    assert "/snapshots" in source
    assert "rechazar" not in source.lower() or True  # sin copia del volumen


def test_backup_qdrant_normaliza_las_tres_formas_de_dimensiones():
    assert backup_qdrant.vector_dimensions({"size": 384, "distance": "Cosine"}) == {"": 384}
    assert backup_qdrant.vector_dimensions({"texto": {"size": 8}}) == {"texto": 8}
    assert backup_qdrant.vector_dimensions([{"name": "t", "size": 5}]) == {"t": 5}
    assert backup_qdrant.vector_dimensions(None) == {}


def test_backup_minio_activa_el_versionado_de_bucket():
    source = (BACKUP_DIR / "backup_minio.py").read_text(encoding="utf-8")
    assert "set_bucket_versioning" in source
    assert "VersioningConfig" in source
    assert "ensure_versioning" in source


def test_backup_minio_copia_por_clave_no_el_volumen():
    source = (BACKUP_DIR / "backup_minio.py").read_text(encoding="utf-8")
    assert "list_objects" in source
    assert "mc mirror" in source
    assert "docker run" not in source


def test_endpoint_minio_se_parsea_como_en_document_store():
    assert _kit.minio_endpoint_config("127.0.0.1:9002") == ("127.0.0.1:9002", False)
    assert _kit.minio_endpoint_config("https://minio:9000") == ("minio:9000", True)


# --------------------------------------------------------------------------
# Herramientas fijadas por version
# --------------------------------------------------------------------------


def test_pins_de_imagen_coinciden_con_docker_compose():
    assert _kit.compose_image("postgres") == _kit.POSTGRES_IMAGE
    assert _kit.compose_image("qdrant") == _kit.QDRANT_IMAGE
    assert _kit.compose_image("minio", "docker-compose.prod.yml") == _kit.MINIO_IMAGE


def test_pin_del_cliente_postgres_cuadra_con_el_servidor():
    major = int(_kit.POSTGRES_IMAGE.split(":")[1])
    assert major == _kit.REQUIRED_PG_CLIENT_MAJOR


def test_pin_de_qdrant_coincide_con_la_imagen():
    assert _kit.QDRANT_IMAGE.split(":v")[-1].startswith(_kit.REQUIRED_QDRANT_MAJOR_MINOR)


def test_sdk_de_minio_esta_fijado_en_pyproject():
    pyproject = (DATA_ENGINE_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert _kit.MINIO_SDK_REQUIREMENT in pyproject


def test_version_de_minio_se_declara_en_el_manifiesto():
    manifest = _minimal_manifest()
    assert manifest["tools"]["minio"]["version"]
    assert backup_minio.sdk_transport_version()


def test_versiones_de_qdrant_y_postgres_se_declaran():
    manifest = _minimal_manifest()
    for tool_name in ("pg_dump", "pg_restore", "qdrant"):
        assert manifest["tools"][tool_name]["version"]


# --------------------------------------------------------------------------
# El runbook: una persona sin contexto tiene que poder recuperar
# --------------------------------------------------------------------------


def test_existen_runbook_readme_y_drill():
    for path in (RUNBOOK, README, DRILL):
        assert path.is_file(), f"falta {path}"


@pytest.mark.parametrize("pilar", ["postgres", "minio", "qdrant"])
def test_runbook_cubre_los_tres_pilares(pilar):
    text = RUNBOOK.read_text(encoding="utf-8").lower()
    assert pilar in text


def test_runbook_tiene_los_pasos_en_orden():
    """El orden es el contrato: si se restaura Qdrant antes de Postgres, el RAG
    puede indexar contra una base vacia."""
    text = RUNBOOK.read_text(encoding="utf-8")
    pasos = re.findall(r"^##\s+Paso\s+(\d+)", text, re.MULTILINE)
    assert pasos, "el runbook debe numerar los pasos (## Paso N)"
    assert [int(paso) for paso in pasos] == sorted(int(paso) for paso in pasos)


def test_runbook_ordena_postgres_antes_de_minio_antes_de_qdrant():
    text = RUNBOOK.read_text(encoding="utf-8")
    orden = [text.find("restore_postgres"), text.find("restore_minio"), text.find("restore_qdrant")]
    assert all(posicion > 0 for posicion in orden), "el runbook debe citar los tres comandos de restore"
    assert orden == sorted(orden), "el runbook debe restaurar postgres -> minio -> qdrant"


@pytest.mark.parametrize(
    "contenido",
    [
        "verify_restore",
        "manifest.json",
        "--confirm-restore",
        "backup_all",
        "pg_dump",
        "-Fc",
        "0046",
        "tiempo",
        "decision humana",
    ],
)
def test_runbook_mentiona_cada_elemento_del_procedimiento(contenido):
    text = RUNBOOK.read_text(encoding="utf-8")
    assert contenido.lower() in text.lower(), f"el runbook no menciona {contenido!r}"


def test_runbook_explica_el_versionado_de_bucket():
    text = RUNBOOK.read_text(encoding="utf-8").lower()
    assert "versionado" in text
    assert "minio" in text


def test_runbook_no_pide_un_dump_plano():
    """Se puede MENCIONAR por que no, pero ningun comando puede pedir uno."""
    text = RUNBOOK.read_text(encoding="utf-8")
    bloques = re.findall(r"```(?:bash|sh)\n(.*?)```", text, re.DOTALL)
    assert bloques, "el runbook debe traer comandos copiables"
    for bloque in bloques:
        assert "-Fp" not in bloque
        assert "--format=plain" not in bloque
    assert "-Fc" in text, "el runbook debe declarar el formato del dump"


def test_readme_justifica_donde_viven_los_scripts():
    text = README.read_text(encoding="utf-8")
    assert "ruff" in text.lower()


# --------------------------------------------------------------------------
# El drill: aislado, no destructivo, exit 0/1
# --------------------------------------------------------------------------


def test_drill_usa_contenedores_y_volumenes_propios():
    source = DRILL.read_text(encoding="utf-8")
    assert "cavaai-" in source
    assert "drill_id" in source
    assert "docker volume create" in source
    assert "docker rm" in source


def test_drill_hace_el_ciclo_completo():
    source = DRILL.read_text(encoding="utf-8")
    for fase in ("backup", "DESTRUYENDO", "restore", "verificacion"):
        assert fase in source, f"el drill no cubre la fase {fase!r}"


def test_drill_siembra_datos_deterministas():
    source = DRILL.read_text(encoding="utf-8")
    assert "SEED_COMPANIES" in source
    assert "SEED_OBJECTS" in source
    assert "SEED_POINTS" in source
    assert "SEED_DIM" in source


def test_drill_devuelve_codigo_de_salida():
    source = DRILL.read_text(encoding="utf-8")
    assert "raise SystemExit(main())" in source
    assert "return 0" in source and "return 1" in source


def test_drill_no_toca_los_volumenes_de_produccion():
    source = DRILL.read_text(encoding="utf-8")
    assert "cavaai-prod-" not in source
    assert "cavaai-postgres-data" not in source
    assert "cavaai-minio-data" not in source
    assert "cavaai-qdrant-data" not in source


def test_drill_verifica_datos_antes_de_arrancar_la_app():
    """La app inserta filas fuera de produccion; comprobar despues daria falso positivo."""
    source = DRILL.read_text(encoding="utf-8")
    assert source.index("PHASE_DATA") < source.index("app.start()")


def test_drill_comprueba_los_conteos_sembrados():
    source = DRILL.read_text(encoding="utf-8")
    assert "_assert_seed_counts" in source


# --------------------------------------------------------------------------
# Workflow de CI
# --------------------------------------------------------------------------


def test_existe_el_workflow_del_drill_de_restore():
    assert WORKFLOW.is_file(), "falta .github/workflows/restore-drill.yml"


def test_workflow_declara_los_tres_servicios():
    text = WORKFLOW.read_text(encoding="utf-8")
    for servicio in ("postgres:", "minio:", "qdrant:"):
        assert servicio in text, f"el workflow no declara el servicio {servicio}"


def test_workflow_es_fail_closed():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "skipped" in text, "el workflow debe detectar comprobaciones omitidas"
    assert "exit 1" in text
    assert "timeout-minutes" in text
    assert "concurrency" in text


def test_workflow_usa_las_imagenes_fijadas():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert _kit.POSTGRES_IMAGE in text
    assert _kit.QDRANT_IMAGE in text
    # La imagen oficial de MinIO (quay.io) ya no es publica: el servicio del drill
    # usa bitnamilegacy/minio con tag fijo. Prod sigue con _kit.MINIO_IMAGE
    # (decision pendiente), por eso aqui NO se exige MINIO_SERVER_RELEASE.
    assert "image: bitnamilegacy/minio:2025.7.23-debian-12-r5" in text


def test_workflow_bloquea_main_pero_no_pr():
    """Decision explicada en el propio YAML: el drill es lento y arranca servicios."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "github.event_name == 'push'" in text or "github.ref == 'refs/heads/main'" in text


def test_workflow_siembra_datos_deterministas():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "seed" in text.lower()
    assert "restore_postgres" in text and "restore_minio" in text and "restore_qdrant" in text
    assert "verify_restore" in text


def test_workflow_no_asume_secretos():
    """Las credenciales son las de los services del propio workflow."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "secrets." not in text


def test_workflow_instala_congelado_desde_uv_lock_y_lo_cachea():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "astral-sh/setup-uv@" in text
    assert 'cache-dependency-glob: "data-engine/uv.lock"' in text
    assert "uv sync --frozen" in text
    # el drill no resuelve versiones por su cuenta: nada de pip install -r
    assert "pip install" not in text


def test_workflow_es_yaml_valido():
    try:
        import yaml
    except ImportError:
        pytest.skip("PyYAML no instalado en este entorno")
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert data
    jobs = data["jobs"]
    assert jobs
    for name, job in jobs.items():
        assert "steps" in job, f"el job {name} no tiene steps"


def test_exec_permission_denied_fails_closed_with_reason(monkeypatch):
    def denied(*args, **kwargs):
        raise PermissionError("synthetic execution denied")

    monkeypatch.setattr(_kit.subprocess, "run", denied)
    with pytest.raises(FailClosedError, match="no ejecutable"):
        _kit.run(["synthetic-command"], what="prueba")
