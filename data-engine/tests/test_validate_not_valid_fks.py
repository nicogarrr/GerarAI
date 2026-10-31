"""El runner VALIDATE del paso aparte de 0114 valida, reporta y es idempotente.

Gated al job Postgres: crea scratchs migradas a head (59 FKs NOT VALID) y
ejecuta scripts/validate_not_valid_fks.py como subproceso contra ellas.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa

from tests.test_0114_fk_ondelete import _scratch
from tests.test_alembic_chain import _url_postgres_ci

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "validate_not_valid_fks.py"
_PENDIENTES = "select count(*) from pg_constraint where contype='f' and not convalidated and connamespace='public'::regnamespace"


def _run(scratch_url: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": scratch_url, "APP_ENV": "test"}
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=_SCRIPT.parent.parent,
        timeout=300,
    )


def _drop(admin, scratch: str) -> None:
    import time

    for _ in range(5):
        try:
            with admin.connect() as conn:
                conn.execute(
                    sa.text(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)')
                )
            break
        except sa.exc.OperationalError:
            time.sleep(1)
    admin.dispose()


def test_runner_dry_run_no_toca_y_apply_valida_todo_en_ci_postgres():
    url = _url_postgres_ci()
    if not url:
        pytest.skip("solo en el job Postgres con CAVAAI_ORIGINAL_DATABASE_URL")
    scratch, scratch_url, admin = _scratch(url)
    try:
        engine = sa.create_engine(scratch_url)
        with engine.connect() as conn:
            assert conn.execute(sa.text(_PENDIENTES)).scalar_one() == 59

        dry = _run(scratch_url)
        assert dry.returncode == 0, dry.stderr
        assert "Dry-run" in dry.stdout
        with engine.connect() as conn:
            assert conn.execute(sa.text(_PENDIENTES)).scalar_one() == 59

        apply = _run(scratch_url, "--apply")
        assert apply.returncode == 0, apply.stderr + apply.stdout
        with engine.connect() as conn:
            assert conn.execute(sa.text(_PENDIENTES)).scalar_one() == 0

        otra = _run(scratch_url, "--apply")
        assert otra.returncode == 0
        assert "Nada que hacer" in otra.stdout
        engine.dispose()
    finally:
        _drop(admin, scratch)


def test_runner_reporta_huerfanos_y_sigue_con_el_resto_en_ci_postgres():
    url = _url_postgres_ci()
    if not url:
        pytest.skip("solo en el job Postgres con CAVAAI_ORIGINAL_DATABASE_URL")
    scratch, scratch_url, admin = _scratch(url)
    try:
        engine = sa.create_engine(scratch_url)
        with engine.begin() as conn:
            conn.execute(sa.text("set session_replication_role = replica"))
            conn.execute(sa.text(
                "insert into tenants (external_id, name, status, metadata, created_at, updated_at)"
                " values ('v-fks', 'V', 'active', '{}', now(), now())"
            ))
            conn.execute(sa.text(
                "insert into document_chunks (document_id, tenant_id, chunk_index, text, token_count, metadata, created_at, updated_at)"
                " select 999999999, id, 0, 'huerfano', 1, '{}', now(), now() from tenants where external_id='v-fks'"
            ))
            conn.execute(sa.text("reset session_replication_role"))

        res = _run(scratch_url, "--apply")
        assert res.returncode == 1
        assert "document_chunks_document_id_fkey" in res.stdout
        assert "999999999" in res.stdout  # muestra de la clave infractora
        with engine.connect() as conn:
            restantes = conn.execute(
                sa.text(
                    "select conname from pg_constraint where contype='f'"
                    " and not convalidated and connamespace='public'::regnamespace"
                )
            ).all()
        # solo la del huerfano sigue NOT VALID: el runner no se detuvo en ella
        assert [r[0] for r in restantes] == ["document_chunks_document_id_fkey"]
        engine.dispose()
    finally:
        _drop(admin, scratch)


def test_fk_compuesta_huerfano_detectado_y_tabla_filtra_el_resultado_en_ci_postgres():
    """FK compuesta: hijo (A1,B2) con padres (A1,B1),(A2,B2) ES huerfano y la
    muestra debe detectarlo (un unico NOT EXISTS con todas las igualdades).
    Ademas, con --tabla el exito/fracaso se juzga solo en esa tabla aunque el
    resto de la BD siga con NOT VALID pendientes."""
    url = _url_postgres_ci()
    if not url:
        pytest.skip("solo en el job Postgres con CAVAAI_ORIGINAL_DATABASE_URL")
    scratch, scratch_url, admin = _scratch(url)
    try:
        engine = sa.create_engine(scratch_url)
        with engine.begin() as conn:
            conn.execute(sa.text(
                "create table padre_comp (a int not null, b int not null,"
                " constraint uq_padre_comp unique (a, b))"
            ))
            conn.execute(sa.text(
                "create table hijo_comp (id int primary key, a int, b int)"
            ))
            conn.execute(sa.text(
                "alter table hijo_comp add constraint fk_hijo_comp_padre"
                " foreign key (a, b) references padre_comp (a, b) not valid"
            ))
            conn.execute(sa.text("insert into padre_comp (a, b) values (1, 1), (2, 2)"))
            conn.execute(sa.text("set session_replication_role = replica"))
            conn.execute(sa.text("insert into hijo_comp (id, a, b) values (1, 1, 2)"))
            conn.execute(sa.text("reset session_replication_role"))

        res = _run(scratch_url, "--apply", "--tabla", "hijo_comp")
        assert res.returncode == 1
        assert "fk_hijo_comp_padre" in res.stdout
        assert "(1, 2)" in res.stdout  # la combinacion huerfana, no columnas sueltas
        with engine.connect() as conn:
            restantes = {
                r[0]
                for r in conn.execute(sa.text(
                    "select conname from pg_constraint where contype='f'"
                    " and not convalidated and connamespace='public'::regnamespace"
                )).all()
            }
        assert "fk_hijo_comp_padre" in restantes
        assert len(restantes) == 60  # las 59 de la cadena + la compuesta

        # una tabla limpia valida aunque queden NOT VALID en otras: sale 0
        res_ok = _run(scratch_url, "--apply", "--tabla", "documents")
        assert res_ok.returncode == 0, res_ok.stdout
        with engine.connect() as conn:
            docs_pendientes = conn.execute(sa.text(
                "select count(*) from pg_constraint where contype='f' and not convalidated"
                " and conrelid = 'documents'::regclass"
            )).scalar_one()
        assert docs_pendientes == 0
        engine.dispose()
    finally:
        _drop(admin, scratch)
