"""Preparation tooling only; no Docker, network, credentials or production."""
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

PATH = Path(__file__).resolve().parents[2] / 'scripts/ops/deploy_preparation.py'
spec = importlib.util.spec_from_file_location('deploy_preparation', PATH)
prep = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prep)


@pytest.fixture
def repo(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    subprocess.run(['git', 'init', '-q', str(source)], check=True)
    subprocess.run(['git', '-C', str(source), '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                    'commit', '--allow-empty', '-qm', 'Synthetic'], check=True)
    sha = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    return source, sha


def test_real_command_receipt_and_no_secret_arguments(repo, tmp_path):
    source, sha = repo
    output = tmp_path / 'phase.json'
    marker = tmp_path / 'literal;not-shell'
    result = prep.time_phase(source, sha, 'backend', output,
                             [sys.executable, '-c', 'import pathlib,sys;pathlib.Path(sys.argv[1]).touch()', str(marker)], 10)
    assert result['status'] == 'passed' and result['exit_code'] == 0
    assert result['sha'] == sha and len(result['tree']) == 40
    assert result['command_seconds'] >= 0
    assert result['started_utc'] <= result['ended_utc']
    assert marker.is_file()
    assert json.loads(output.read_text()) == result
    assert 'argv' not in output.read_text() and str(marker) not in output.read_text()
    with pytest.raises(FileExistsError):
        prep.time_phase(source, sha, 'backend', output, [sys.executable, '-V'], 10)


@pytest.mark.parametrize('sha', ['main', 'A' * 40, '0' * 40])
def test_wrong_sha_is_not_started(repo, tmp_path, sha):
    with pytest.raises(ValueError):
        prep.time_phase(repo[0], sha, 'backend', tmp_path / 'not-written', ['false'], 10)
    assert not (tmp_path / 'not-written').exists()


def test_dirty_repo_is_not_started(repo, tmp_path):
    (repo[0] / 'unexpected').touch()
    with pytest.raises(ValueError, match='clean'):
        prep.time_phase(*repo, 'backend', tmp_path / 'receipt', ['false'], 10)


@pytest.mark.parametrize(('phase', 'command', 'timeout'), [
    ('rollout', ['true'], 10), ('backend', [], 10), ('backend', ['true'], 0),
    ('backend', ['true'], float('inf')), ('backend', ['true'], True),
])
def test_bad_timing_input(repo, tmp_path, phase, command, timeout):
    with pytest.raises(ValueError):
        prep.time_phase(*repo, phase, tmp_path / 'receipt', command, timeout)


def test_output_inside_source_is_rejected(repo):
    with pytest.raises(ValueError, match='outside'):
        prep.time_phase(*repo, 'backend', repo[0] / 'receipt', ['true'], 10)


@pytest.mark.parametrize(('command', 'expected'), [
    ([sys.executable, '-c', 'raise SystemExit(3)'], 'failed'),
    (['/no/such/synthetic-command'], 'launch_failed'),
    ([sys.executable, '-c', 'import time;time.sleep(30)'], 'timeout'),
])
def test_nonpassing_receipts(repo, tmp_path, command, expected):
    result = prep.time_phase(*repo, 'backend', tmp_path / 'receipt', command, .05)
    assert result['status'] == expected and result['exit_code'] != 0


def test_source_changed_during_command_is_not_green(repo, tmp_path):
    result = prep.time_phase(*repo, 'frontend', tmp_path / 'receipt',
                             [sys.executable, '-c', "open('unexpected','w').close()"], 10)
    assert result['status'] == 'source_changed' and result['exit_code'] == 125


def test_interrupt_stops_child_and_is_not_green(repo, tmp_path, monkeypatch):
    original = prep.subprocess.Popen
    process = original([sys.executable, '-c', 'import time;time.sleep(30)'], start_new_session=True)
    wait = process.wait
    calls = []
    def interrupt_once(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise KeyboardInterrupt
        return wait(*args, **kwargs)
    monkeypatch.setattr(process, 'wait', interrupt_once)
    # Source validation uses check_output/Popen too. Patch source check only in
    # this interruption unit test; independent tests above exercise actual git.
    monkeypatch.setattr(prep, 'exact_source', lambda *args: 'a' * 40)
    monkeypatch.setattr(prep.subprocess, 'Popen', lambda *args, **kwargs: process)
    result = prep.time_phase(*repo, 'backend', tmp_path / 'receipt', ['synthetic'], 10)
    assert result['status'] == 'interrupted' and result['exit_code'] == 130
    assert process.poll() is not None


def test_stop_escalates_when_term_does_not_finish(monkeypatch):
    process = Mock(pid=123)
    process.wait.side_effect = [subprocess.TimeoutExpired('synthetic', 5), 0]
    signals = []
    monkeypatch.setattr(prep.os, 'killpg', lambda pid, sig: signals.append((pid, sig)))
    prep._stop(process)
    assert signals == [(123, signal.SIGTERM), (123, signal.SIGKILL)]


def test_plan_preserves_all_phases_and_only_overlaps_preparation():
    durations = dict.fromkeys(prep.PHASES, 10)
    serial = prep.plan(durations, 'serial')
    parallel = prep.plan(durations, 'overlap-build-backup')
    assert serial['preparation_seconds'] == 100
    assert parallel['preparation_seconds'] == 80
    assert parallel['phases']['backup_dump']['start_seconds'] == parallel['phases']['build_backend']['start_seconds'] == 50
    assert parallel['barrier'] == list(prep.PHASES)
    assert not parallel['release_authorized']
    assert parallel['kind'] == 'estimate_only_not_gate_evidence'
    # Both lanes retain serial internal ordering, max two at once.
    for t in range(100):
        assert sum(p['start_seconds'] <= t < p['end_seconds'] for p in parallel['phases'].values()) <= 2


def test_freshness_uses_dump_start_not_restore_end():
    durations = dict.fromkeys(prep.PHASES, 1)
    durations['backup_restore'] = 7200
    result = prep.plan(durations, 'overlap-build-backup')
    assert not result['backup_within_estimated_budget']
    assert result['backup_age_at_reserved_change_seconds'] > 7200


@pytest.mark.parametrize('bad', [True, -1, float('nan'), float('inf'), '1', None])
def test_invalid_durations(bad):
    values = dict.fromkeys(prep.PHASES, 1)
    values['pg'] = bad
    with pytest.raises(ValueError):
        prep.plan(values, 'serial')


def test_unknown_or_missing_phase_mode_and_bad_reserve():
    with pytest.raises(ValueError):
        prep.plan({}, 'serial')
    with pytest.raises(ValueError):
        prep.plan(dict.fromkeys(prep.PHASES, 1), 'rollout')
    with pytest.raises(ValueError):
        prep.plan(dict.fromkeys(prep.PHASES, 1), 'serial', 299)


def test_cli_plan_and_time(repo, tmp_path, capsys):
    durations = tmp_path / 'durations.json'
    durations.write_text(json.dumps(dict.fromkeys(prep.PHASES, 1)))
    assert prep.main(['plan', '--durations', str(durations)]) == 0
    assert json.loads(capsys.readouterr().out)['kind'] == 'estimate_only_not_gate_evidence'
    args = ['time', '--repo', str(repo[0]), '--sha', repo[1], '--phase', 'backend',
            '--output', str(tmp_path / 'receipt'), '--timeout', '10', '--', sys.executable, '-c', 'pass']
    assert prep.main(args) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'passed'


@pytest.mark.parametrize('stage', ['term', 'kill'])
def test_stop_reaps_child_that_just_exited(monkeypatch, stage):
    process = Mock(pid=123)
    if stage == 'kill':
        process.wait.side_effect = [subprocess.TimeoutExpired('synthetic', 5), 0]
    def gone(pid, sig):
        if stage == 'term' or sig == signal.SIGKILL:
            raise ProcessLookupError
    monkeypatch.setattr(prep.os, 'killpg', gone)
    prep._stop(process)
    assert process.wait.called


def test_interrupt_before_child_launch_is_not_green(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(prep, 'exact_source', lambda *args: 'a' * 40)
    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt
    monkeypatch.setattr(prep.subprocess, 'Popen', interrupt)
    result = prep.time_phase(*repo, 'backend', tmp_path / 'receipt', ['synthetic'], 10)
    assert result['status'] == 'interrupted'


def test_post_command_tree_mismatch_is_not_green(repo, tmp_path, monkeypatch):
    calls = iter(['a' * 40, 'b' * 40])
    monkeypatch.setattr(prep, 'exact_source', lambda *args: next(calls))
    result = prep.time_phase(*repo, 'backend', tmp_path / 'receipt', [sys.executable, '-c', 'pass'], 10)
    assert result['status'] == 'source_changed'


def test_cli_signal_exit_becomes_nonzero(repo, tmp_path, capsys):
    assert prep.main(['time', '--repo', str(repo[0]), '--sha', repo[1],
                      '--phase', 'backend', '--output', str(tmp_path / 'receipt'), '--timeout', '10',
                      sys.executable, '-c', 'import os,signal;os.kill(os.getpid(),signal.SIGTERM)']) == 1
    assert json.loads(capsys.readouterr().out)['status'] == 'failed'


def test_script_plan_entrypoint_does_not_execute_commands(tmp_path):
    durations = tmp_path / 'durations.json'
    durations.write_text(json.dumps(dict.fromkeys(prep.PHASES, 1)))
    result = subprocess.run([sys.executable, str(PATH), 'plan', '--durations', str(durations),
                             '--mode', 'overlap-build-backup'], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)['release_authorized'] is False



def test_timeout_kills_term_ignoring_descendant_after_leader_exits(repo, tmp_path):
    ready = tmp_path / 'descendant.pid'
    child_code = (
        'import os,signal,time,pathlib,sys;'
        'signal.signal(signal.SIGTERM,signal.SIG_IGN);'
        'pathlib.Path(sys.argv[1]).write_text(str(os.getpid()));'
        'time.sleep(60)'
    )
    leader_code = (
        'import subprocess,sys,time,pathlib;'
        'child=subprocess.Popen([sys.executable,"-c",sys.argv[1],sys.argv[2]]);'
        'ready=pathlib.Path(sys.argv[2]);'
        'exec("while not ready.exists(): time.sleep(.01)");'
        'child.wait()'
    )
    pid = None
    try:
        result = prep.time_phase(*repo, 'backend', tmp_path / 'receipt',
                                 [sys.executable, '-c', leader_code, child_code, str(ready)], 1)
        assert result['status'] == 'timeout'
        pid = int(ready.read_text())
        # Orphans can remain zombies until the host init reaps them. They are
        # dead, not live work. Do not mistake kill(pid, 0) success for survival.
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            stat = Path(f'/proc/{pid}/stat')
            if not stat.exists() or stat.read_text().split()[2] == 'Z':
                break
            time.sleep(.01)
        else:
            pytest.fail('TERM-ignoring descendant survived timeout cleanup')
    finally:
        if pid is None and ready.exists():
            pid = int(ready.read_text())
        if pid is not None:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
