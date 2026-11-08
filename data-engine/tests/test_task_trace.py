"""Traza por message_id: sin valores de args, snapshot opt-in 0600 y retencion."""
import json
import logging
import os
import stat

import dramatiq
import pytest

from app.workers.task_trace import TaskTraceMiddleware, args_digest

SECRET_ARG = "tok-SECRET-VALUE-123"


def msg(**opts):
    return dramatiq.Message(
        "default", "refresh_rss_feeds", (5, SECRET_ARG), {"scope": "all", "ticker": "ABC"}, opts
    )


def test_logs_have_ids_but_never_arg_values(caplog, monkeypatch):
    monkeypatch.delenv("TRACE_HASH_KEY", raising=False)
    mw = TaskTraceMiddleware()
    m = msg(redis_message_id="rid-1", retries=2)
    with caplog.at_level(logging.INFO, logger="dramatiq.task_trace"):
        mw.before_process_message(None, m)
        assert [e["message_id"] for e in mw.inflight()] == [m.message_id]
        mw.after_process_message(None, m, result=None, exception=None)
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert m.message_id in text and "rid-1" in text and "retries=2" in text
    assert "kwargs=scope,ticker" in text and "outcome=ok" in text
    assert SECRET_ARG not in text and "ABC" not in text
    assert "args_hash=-" in text  # sin clave no hay hash reversible
    assert mw.inflight() == []


def test_error_and_skip_outcomes(caplog):
    mw = TaskTraceMiddleware()
    a, b = msg(), msg()
    with caplog.at_level(logging.INFO, logger="dramatiq.task_trace"):
        mw.before_process_message(None, a)
        mw.after_process_message(None, a, exception=ValueError("boom " + SECRET_ARG))
        mw.after_skip_message(None, b)
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "outcome=error:ValueError" in text and "outcome=skipped" in text
    assert "boom" not in text and SECRET_ARG not in text
    assert mw.inflight() == []


def test_hash_is_keyed_and_stable(monkeypatch):
    monkeypatch.setenv("TRACE_HASH_KEY", "k" * 32)
    h1, h2 = args_digest(msg()), args_digest(msg())
    assert h1 == h2 and len(h1) == 16 and h1 != "-"
    monkeypatch.setenv("TRACE_HASH_KEY", "j" * 32)
    assert args_digest(msg()) != h1
    monkeypatch.setenv("TRACE_HASH_KEY", "short")
    assert args_digest(msg()) == "-"


def test_snapshot_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("TRACE_SNAPSHOT_DIR", raising=False)
    mw = TaskTraceMiddleware()
    mw.before_process_message(None, msg())
    mw.before_worker_shutdown(None, object())
    assert list(tmp_path.iterdir()) == []


def test_snapshot_private_and_retained(tmp_path, monkeypatch):
    target = tmp_path / "snap"
    monkeypatch.setenv("TRACE_SNAPSHOT_DIR", str(target))
    monkeypatch.setenv("TRACE_SNAPSHOT_KEEP", "2")
    mw = TaskTraceMiddleware()
    m = msg()
    mw.before_process_message(None, m)
    target.mkdir(mode=0o700)
    os.chmod(target, 0o700)  # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions -- test: chmod deliberado para fijar los permisos del escenario bajo prueba
    for i in range(4):  # ficheros viejos: la retencion debe borrarlos primero
        (target / f"inflight-2000010{i}T000000-1.json").write_text("{}")
    mw.before_worker_shutdown(None, object())
    files = sorted(os.listdir(target))
    assert len(files) == 2 and files[-1].startswith("inflight-2")
    path = target / files[-1]
    assert not files[-1].startswith("inflight-2000")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(target.stat().st_mode) == 0o700
    body = json.loads(path.read_text())
    assert body["inflight"][0]["message_id"] == m.message_id


def test_snapshot_failure_does_not_block_shutdown(tmp_path, monkeypatch):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setenv("TRACE_SNAPSHOT_DIR", str(blocker / "sub"))
    mw = TaskTraceMiddleware()
    mw.before_process_message(None, msg())
    mw.before_worker_shutdown(None, object())  # no lanza


def test_registered_on_worker_broker():
    from app.workers import dramatiq_app

    assert any(isinstance(x, TaskTraceMiddleware) for x in dramatiq_app.broker.middleware)


@pytest.mark.parametrize("hook", ["before_process_message", "after_skip_message"])
def test_hooks_tolerate_unknown_message(hook):
    getattr(TaskTraceMiddleware(), hook)(None, msg())


def test_duplicate_inflight_message_id_keeps_both():
    mw = TaskTraceMiddleware()
    a = msg()
    b = a.copy()  # mismo message_id (reentrega)
    assert a.message_id == b.message_id
    mw.before_process_message(None, a)
    mw.before_process_message(None, b)
    assert len(mw.inflight()) == 2
    mw.after_process_message(None, a)
    assert len(mw.inflight()) == 1
    mw.after_process_message(None, b)
    assert mw.inflight() == []


def test_snapshot_size_cap_counts_truncated(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACE_SNAPSHOT_DIR", str(tmp_path / "s"))
    monkeypatch.setenv("TRACE_SNAPSHOT_MAX_BYTES", "4096")
    mw = TaskTraceMiddleware()
    for _ in range(40):
        m = dramatiq.Message("default", "x", ("p" * 500,), {}, {})
        mw.before_process_message(None, m)
    mw.before_worker_shutdown(None, object())
    (path,) = (tmp_path / "s").iterdir()
    body = json.loads(path.read_text())
    assert body["truncated"] > 0 and len(body["inflight"]) + body["truncated"] == 40
    assert len(path.read_text()) < 4096 + 1024


def test_slow_snapshot_does_not_block_shutdown(tmp_path, monkeypatch):
    import time

    monkeypatch.setenv("TRACE_SNAPSHOT_DIR", str(tmp_path / "s"))
    monkeypatch.setenv("TRACE_SNAPSHOT_TIMEOUT_S", "1")
    mw = TaskTraceMiddleware()
    monkeypatch.setattr(mw, "_write_snapshot", lambda d, p: time.sleep(3))
    mw.before_process_message(None, msg())
    start = time.monotonic()
    mw.before_worker_shutdown(None, object())
    assert time.monotonic() - start < 2.5


def test_snapshot_written_atomically_no_tmp_left(tmp_path, monkeypatch):
    d = tmp_path / "s"
    monkeypatch.setenv("TRACE_SNAPSHOT_DIR", str(d))
    mw = TaskTraceMiddleware()
    mw.before_process_message(None, msg())
    mw.before_worker_shutdown(None, object())
    names = os.listdir(d)
    assert len(names) == 1 and names[0].endswith(".json") and not names[0].startswith(".")


def test_failed_write_removes_tmp_and_keeps_old(tmp_path, monkeypatch):
    d = tmp_path / "s"
    mw = TaskTraceMiddleware()
    mw.before_process_message(None, msg())
    mw._write_snapshot(str(d), [msg()])
    before = sorted(os.listdir(d))

    def boom(src, dst):
        raise OSError("disk")

    monkeypatch.setattr("app.workers.task_trace.os.replace", boom)
    with pytest.raises(OSError):
        mw._write_snapshot(str(d), [msg()])
    assert sorted(os.listdir(d)) == before  # sin tmp huerfano ni fichero parcial


def test_stale_partials_are_cleaned_fresh_ones_kept(tmp_path):
    d = tmp_path / "s"
    d.mkdir(mode=0o700)
    old, fresh = d / ".inflight-a.json.tmp", d / ".inflight-b.json.tmp"
    old.write_text("x")
    fresh.write_text("x")
    os.utime(old, (1, 1))
    TaskTraceMiddleware()._write_snapshot(str(d), [msg()])
    assert not old.exists() and fresh.exists()


def test_existing_dir_validated_not_chmodded(tmp_path):
    loose = tmp_path / "loose"
    loose.mkdir()
    os.chmod(loose, 0o755)  # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions -- test: chmod deliberado para fijar los permisos del escenario bajo prueba
    with pytest.raises(PermissionError):
        TaskTraceMiddleware()._write_snapshot(str(loose), [msg()])
    assert stat.S_IMODE(loose.stat().st_mode) == 0o755  # no se toco
    ok = tmp_path / "ok"
    ok.mkdir()
    os.chmod(ok, 0o700)  # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions -- test: chmod deliberado para fijar los permisos del escenario bajo prueba
    TaskTraceMiddleware()._write_snapshot(str(ok), [msg()])
    notdir = tmp_path / "f"
    notdir.write_text("x")
    with pytest.raises(NotADirectoryError):
        TaskTraceMiddleware()._write_snapshot(str(notdir), [msg()])


def test_args_digest_args_no_serializables_devuelve_guion(monkeypatch):
    monkeypatch.setenv("TRACE_HASH_KEY", "k" * 32)
    # sort_keys con claves de tipos mezclados: TypeError -> "-" y nunca rompe el log
    m = dramatiq.Message("default", "actor", ({1: "x", "a": "y"},), {}, {})
    assert args_digest(m) == "-"


def test_env_roto_cae_al_default(monkeypatch):
    from app.workers import task_trace

    monkeypatch.setenv("TRACE_SNAPSHOT_MAX_BYTES", "no-numero")
    monkeypatch.setenv("TRACE_SNAPSHOT_KEEP", "no-numero")
    assert task_trace._int_env("TRACE_SNAPSHOT_MAX_BYTES", 1_048_576, 4096) == 1_048_576
    assert task_trace._keep() == 5


def test_drop_stale_partials_tolera_borrado_roto(tmp_path, monkeypatch):
    import time

    d = tmp_path / "snap"
    d.mkdir()
    viejo = d / ".inflight-viejo.tmp"
    viejo.write_text("{}")
    hace_una_hora = time.time() - 3600
    os.utime(viejo, (hace_una_hora, hace_una_hora))
    reciente = d / ".inflight-nuevo.tmp"
    reciente.write_text("{}")

    real_remove = os.remove

    def remove_roto(path):
        if "viejo" in str(path):
            raise OSError("en uso por otro proceso")
        return real_remove(path)

    monkeypatch.setattr(os, "remove", remove_roto)
    TaskTraceMiddleware._drop_stale_partials(str(d))
    assert viejo.exists()  # el fallo de borrado no rompe la limpieza
    assert reciente.exists()  # y un tmp en curso (mtime reciente) no se toca


def test_snapshot_replace_roto_limpia_tmp_y_propaga(tmp_path, monkeypatch):
    mw = TaskTraceMiddleware()

    def replace_roto(src, dst):
        raise RuntimeError("disco lleno")

    def remove_roto(path):
        raise OSError("tampoco se puede borrar")

    monkeypatch.setattr(os, "replace", replace_roto)
    monkeypatch.setattr(os, "remove", remove_roto)
    with pytest.raises(RuntimeError):
        mw._write_snapshot(str(tmp_path / "snap"), [msg()])


def test_snapshot_retencion_tolera_borrado_roto(tmp_path, monkeypatch):
    d = tmp_path / "snap"
    d.mkdir(mode=0o700)
    os.chmod(d, 0o700)  # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions -- test: chmod deliberado para fijar los permisos del escenario bajo prueba
    monkeypatch.setenv("TRACE_SNAPSHOT_KEEP", "1")
    for i in range(3):
        (d / f"inflight-2000010{i}T000000-1.json").write_text("{}")
    mw = TaskTraceMiddleware()
    borrados = []

    def remove_fallando(path):
        borrados.append(str(path))
        raise OSError("bloqueado")

    monkeypatch.setattr(os, "remove", remove_fallando)
    mw._write_snapshot(str(d), [])
    assert any("inflight-2000" in b for b in borrados)  # intento podar los viejos
    assert sum(1 for f in os.listdir(d) if f.startswith("inflight-")) == 4
