"""Wiring fixtures only, no Docker/VM or actual daemon connection."""
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from tests.test_rehearsal_guard import records as records

OPS = Path(__file__).resolve().parents[2] / 'scripts/ops'
sys.path.insert(0, str(OPS))
try:
    spec = importlib.util.spec_from_file_location('rehearsal_smoke', OPS / 'rehearsal_smoke.py')
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
finally:
    sys.path.remove(str(OPS))


@pytest.fixture
def runnable(records, tmp_path, monkeypatch):
    inv = records[0]
    output = tmp_path / 'serial'
    output.mkdir(mode=0o700)
    lock = tmp_path / 'backup.lock'
    lock.touch(mode=0o600)
    inv.update(root=str(tmp_path), output=str(output), lock=str(lock))
    monkeypatch.setattr(smoke, 'exact_source', lambda *args: 'e'*40)
    monkeypatch.setattr(smoke, 'inspect_current', lambda value: {'source_id': value['source_id']})
    base = dict(Id='sha256:'+'f'*64, Config={})
    monkeypatch.setattr(smoke, 'docker_json', lambda *args: [base])
    return inv, base, output, lock


def test_receipt_false_authority_and_postcheck(runnable, monkeypatch):
    inv, base, output, _ = runnable
    monkeypatch.setattr(smoke, 'exercise', lambda *args, **kwargs: [{'case': 'fixture'}])
    result = smoke.run(inv, Path('/unused'), base['Id'], output/'smoke.json')
    assert result['status'] == 'verified_tiny_smoke_only'
    assert not result['rehearsal_authorized'] and not result['release_authorized']
    assert json.loads((output/'smoke.json').read_text()) == result
    assert (output/'smoke.json').stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        smoke.run(inv, Path('/unused'), base['Id'], output/'smoke.json')


def test_failed_exercise_or_source_drift_leaves_non_green_receipt(runnable, monkeypatch):
    inv, base, output, _ = runnable
    monkeypatch.setattr(smoke, 'exercise', Mock(side_effect=KeyboardInterrupt))
    with pytest.raises(KeyboardInterrupt):
        smoke.run(inv, Path('/unused'), base['Id'], output/'smoke.json')
    assert json.loads((output/'smoke.json').read_text())['status'] == 'failed_or_cleanup_unconfirmed'
    (output/'smoke.json').unlink()
    monkeypatch.setattr(smoke, 'exercise', lambda *args, **kwargs: [])
    calls = iter(['a'*40, 'b'*40])
    monkeypatch.setattr(smoke, 'exact_source', lambda *args: next(calls))
    with pytest.raises(ValueError):
        smoke.run(inv, Path('/unused'), base['Id'], output/'smoke.json')
    assert json.loads((output/'smoke.json').read_text())['status'] != 'verified_tiny_smoke_only'


def test_refuses_bad_paths_lock_base_and_permissions(runnable, monkeypatch):
    inv, base, output, lock = runnable
    with pytest.raises(ValueError):
        smoke.run(inv, Path('/unused'), 'postgres:17', output/'smoke.json')
    with pytest.raises(ValueError):
        smoke.run(inv, Path('/unused'), base['Id'], output/'other.json')
    output.chmod(0o755)
    with pytest.raises(ValueError):
        smoke.run(inv, Path('/unused'), base['Id'], output/'smoke.json')
    output.chmod(0o700)
    lock.chmod(0o666)
    with pytest.raises(ValueError):
        smoke.run(inv, Path('/unused'), base['Id'], output/'smoke.json')
    lock.chmod(0o600)
    monkeypatch.setattr(smoke, 'docker_json', lambda *args, **kwargs: [])
    with pytest.raises(ValueError):
        smoke.run(inv, Path('/unused'), base['Id'], output/'smoke.json')
    assert not (output/'smoke.json').exists()


def test_fixed_three_cases_and_expected_daemon_failures(records, tmp_path, monkeypatch):
    inv = records[0]
    base = dict(Id='sha256:'+'f'*64, Config={})
    engines = []
    class Engine:
        def __init__(self, archive, digest, tag):
            self.archive, self.digest, self.tag = archive, digest, tag
            self.released_proofs = [{'id': '1'*64}]
            self.terminal = dict(exit_code=1, daemon_error=True)
            self.cancelled = True
            self.observed = {'1'*64}
            engines.append(self)
        def daemon_settled(self):
            return True
        def snapshot(self):
            return []
        def inspect_workers(self):
            return [dict(Id='1'*64, State=dict(Running=False))]
    def supervise(inv, recipe, engine, timeout):
        assert engine.archive.exists() and timeout in (5, 30)
        if recipe['build_id'] == 'smoke-success':
            return dict(proofs=[dict(id='1'*64)], image_id='sha256:'+'2'*64)
        raise smoke.BuildIncomplete('synthetic confirmed')
    monkeypatch.setattr(smoke, 'supervise', supervise)
    progress = []
    results = smoke.exercise(inv, base, tmp_path, engine_factory=Engine, on_progress=progress.append)
    assert len(progress) == 6
    assert [result['case'] for result in results] == list(smoke.CASES)
    assert all(result['retained_container_ids'] == ['1'*64] for result in results)
    assert len(engines) == 3
    other = tmp_path/'no-progress-callback'
    other.mkdir()
    assert len(smoke.exercise(inv, base, other, engine_factory=Engine)) == 3


@pytest.mark.parametrize('failure', ['unexpected-success', 'no-release', 'not-settled', 'live-worker', 'no-terminal', 'not-cancelled'])
def test_smoke_never_accepts_unconfirmed_or_unexercised_failure(records, tmp_path, monkeypatch, failure):
    inv = records[0]
    base = dict(Id='sha256:'+'f'*64, Config={})
    class Engine:
        def __init__(self, *args):
            self.tag = args[2]
            self.released_proofs = [] if failure == 'no-release' else [{}]
            self.terminal = None if failure == 'no-terminal' else dict(exit_code=1, daemon_error=True)
            self.cancelled = failure != 'not-cancelled'
            self.observed = set()
        def daemon_settled(self):
            return failure != 'not-settled'
        def snapshot(self):
            return [{}] if failure == 'live-worker' else []
        def inspect_workers(self):
            return []
    def supervise(inv, recipe, engine, timeout):
        if recipe['build_id'] == 'smoke-success' or failure == 'unexpected-success':
            return dict(proofs=[], image_id='sha256:'+'2'*64)
        raise smoke.BuildIncomplete('synthetic')
    monkeypatch.setattr(smoke, 'supervise', supervise)
    with pytest.raises((ValueError, RuntimeError)):
        smoke.exercise(inv, base, tmp_path, engine_factory=Engine, on_progress=lambda value: None)
    other = tmp_path/'without-callback'
    other.mkdir()
    with pytest.raises((ValueError, RuntimeError)):
        smoke.exercise(inv, base, other, engine_factory=Engine)


def test_observed_release_is_recorded_only_after_parent_confirms(monkeypatch, tmp_path):
    monkeypatch.setattr(smoke.DockerBuild, 'release', lambda *args: None)
    engine = smoke.ObservedBuild(tmp_path/'archive', 'f'*64, 'unused')
    engine.release('a'*64, '/tmp/marker')
    assert engine.released_proofs == [{'id': 'a'*64, 'marker': '/tmp/marker'}]


def test_cli_reports_only_smoke_status(runnable, tmp_path, monkeypatch, capsys):
    inv, base, output, _ = runnable
    path = tmp_path/'inventory.json'
    path.write_text(json.dumps(inv))
    monkeypatch.setattr(smoke, 'exercise', lambda *args, **kwargs: [])
    assert smoke.main(['--inventory', str(path), '--repo', str(tmp_path), '--base-image', base['Id'],
                       '--receipt', str(output/'smoke.json')]) == 0
    assert json.loads(capsys.readouterr().out)['rehearsal_authorized'] is False



def test_live_progress_survives_failed_smoke_case(runnable, monkeypatch):
    inv, base, output, _ = runnable
    def exercise(*args, on_progress):
        on_progress({'case': 'smoke-success', 'status': 'verified'})
        on_progress({'case': 'smoke-cancel', 'status': 'failed_or_cleanup_unconfirmed',
                     'all_observed_container_ids': ['1'*64]})
        raise RuntimeError('synthetic daemon uncertainty')
    monkeypatch.setattr(smoke, 'exercise', exercise)
    with pytest.raises(RuntimeError):
        smoke.run(inv, Path('/unused'), base['Id'], output/'smoke.json')
    saved = json.loads((output/'smoke.json').read_text())
    assert saved['status'] == 'failed_or_cleanup_unconfirmed'
    assert saved['cases'][1]['all_observed_container_ids'] == ['1'*64]
