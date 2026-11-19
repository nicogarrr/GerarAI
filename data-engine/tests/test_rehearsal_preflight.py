"""All Docker/cgroup inputs are local fixtures. No Docker executable is run."""
import importlib.util
import json
import os
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from tests.test_rehearsal_guard import cgroup_files
from tests.test_rehearsal_guard import records as records

OPS = Path(__file__).resolve().parents[2] / 'scripts/ops'
sys.path.insert(0, str(OPS))
try:
    spec = importlib.util.spec_from_file_location('rehearsal_preflight', OPS / 'rehearsal_preflight.py')
    preflight = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(preflight)
finally:
    sys.path.remove(str(OPS))


@pytest.fixture
def inspected(records, tmp_path, monkeypatch):
    inv, source, volume = records
    cgroups = tmp_path / 'cgroup'
    parent = cgroups / inv['cgroup_parent']
    scope = parent / ('docker-' + inv['source_id'] + '.scope')
    scope.mkdir(parents=True)
    for name, content in cgroup_files().items():
        (parent / name).write_text(content)
    (parent / 'cgroup.procs').touch()
    (scope / 'cgroup.procs').write_text('123\n')
    proc = tmp_path / 'proc'
    (proc / '123').mkdir(parents=True)
    (proc / '123' / 'cgroup').write_text('0::/' + str(scope.relative_to(cgroups)) + '\n')
    prod = dict(Id='c'*64, Mounts=[])
    containers = [source, prod]
    monkeypatch.setattr(preflight, 'collect_ids', lambda: [c['Id'] for c in containers])
    def docker(*args):
        if args[0] == 'info':
            return dict(CgroupVersion='2', CgroupDriver='systemd')
        if args[0] == 'volume':
            return [volume]
        assert args[0:2] == ('container', 'inspect')
        return containers if len(args) > 3 else [containers[0]]
    monkeypatch.setattr(preflight, 'docker_json', docker)
    return inv, containers, cgroups, proc, parent, scope


def test_collects_safe_fields_not_environment(inspected):
    inv, _, cg, proc, _, _ = inspected
    result = preflight.inspect_current(inv, cg, proc)
    assert result['source_pid'] == 123
    assert result['resource_snapshot']['memory.max'] == '8589934592'
    assert 'POSTGRES_DB' not in json.dumps(result)


def test_all_container_ids_and_volume_must_be_inspected(inspected, monkeypatch):
    inv, containers, cg, proc, _, _ = inspected
    monkeypatch.setattr(preflight, 'collect_ids', lambda: [])
    with pytest.raises(ValueError):
        preflight.inspect_current(inv, cg, proc)
    monkeypatch.setattr(preflight, 'collect_ids', lambda: ['c'*64])
    with pytest.raises(ValueError):
        preflight.inspect_current(inv, cg, proc)
    monkeypatch.setattr(preflight, 'collect_ids', lambda: ['a'*64, 'c'*64, 'f'*64])
    with pytest.raises(ValueError):
        preflight.inspect_current(inv, cg, proc)
    monkeypatch.setattr(preflight, 'collect_ids', lambda: [c['Id'] for c in containers])
    original = preflight.docker_json
    monkeypatch.setattr(preflight, 'docker_json', lambda *args: [] if args[0] == 'volume' else original(*args))
    with pytest.raises(ValueError):
        preflight.inspect_current(inv, cg, proc)


def test_missing_or_foreign_cgroup_fails(inspected):
    inv, _, cg, proc, parent, scope = inspected
    (proc / '124').mkdir()
    (proc / '124' / 'cgroup').write_text('0::/system.slice/foreign.scope')
    (scope / 'cgroup.procs').write_text('123\n124\n')
    with pytest.raises(ValueError):
        preflight.inspect_current(inv, cg, proc)
    (scope / 'cgroup.procs').write_text('123\n')
    (proc / '123' / 'cgroup').write_text('0::/gerarai_bench.slice/not-source.scope')
    with pytest.raises(ValueError):
        preflight.inspect_current(inv, cg, proc)
    (proc / '123' / 'cgroup').write_text('0::/' + str(scope.relative_to(cg)))
    (parent / 'cgroup.procs').write_text('123')
    with pytest.raises(ValueError):
        preflight.inspect_current(inv, cg, proc)
    with pytest.raises(ValueError):
        preflight.inspect_current(inv, cg / 'missing', proc)


def test_docker_commands_are_fixed_local_socket(monkeypatch):
    read = Mock(return_value='{"CgroupVersion":"2"}')
    monkeypatch.setattr(preflight.subprocess, 'check_output', read)
    assert preflight.docker_json('info', '--format', '{{json .}}')['CgroupVersion'] == '2'
    assert read.call_args.args[0] == ['docker', '--host', 'unix:///var/run/docker.sock', 'info', '--format', '{{json .}}']
    read.return_value = 'a'*64 + '\n' + 'c'*64 + '\n'
    assert preflight.collect_ids() == ['a'*64, 'c'*64]
    read.return_value = 'a'*64 + '\n' + 'a'*64 + '\n'
    with pytest.raises(ValueError):
        preflight.collect_ids()
    read.return_value = 'unsafe-name'
    with pytest.raises(ValueError):
        preflight.collect_ids()


@pytest.fixture
def runnable(records, tmp_path, monkeypatch):
    inv = records[0]
    output = tmp_path / 'serial'
    output.mkdir()
    lock = tmp_path / 'backup.lock'
    lock.touch(mode=0o600)
    inv.update(root=str(tmp_path), output=str(output), lock=str(lock))
    monkeypatch.setattr(preflight, 'validate_inventory', lambda value: value)
    monkeypatch.setattr(preflight, 'exact_source', lambda *args: 'e'*40)
    monkeypatch.setattr(preflight, 'inspect_current', lambda value: {'source_id': value['source_id']})
    return inv, output, lock


def test_run_exclusive_private_receipt_and_no_authorization(runnable):
    inv, output, _ = runnable
    receipt = output / 'preflight.json'
    result = preflight.run(inv, Path('/unused'), receipt)
    assert json.loads(receipt.read_text()) == result
    assert receipt.stat().st_mode & 0o777 == 0o600
    assert not result['rehearsal_authorized'] and not result['release_authorized']
    with pytest.raises(FileExistsError):
        preflight.run(inv, Path('/unused'), receipt)


def test_run_refuses_bad_receipt_lock_or_source_drift(runnable, monkeypatch):
    inv, output, lock = runnable
    with pytest.raises(ValueError):
        preflight.run(inv, Path('/unused'), output.parent / 'outside.json')
    receipt = output / 'receipt'
    lock.chmod(0o666)
    with pytest.raises(ValueError):
        preflight.run(inv, Path('/unused'), receipt)
    lock.chmod(0o600)
    descriptor = os.open(lock, os.O_RDONLY)
    try:
        preflight.fcntl.flock(descriptor, preflight.fcntl.LOCK_EX | preflight.fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            preflight.run(inv, Path('/unused'), receipt)
    finally:
        os.close(descriptor)
    calls = iter(['a'*40, 'b'*40])
    monkeypatch.setattr(preflight, 'exact_source', lambda *args: next(calls))
    with pytest.raises(ValueError):
        preflight.run(inv, Path('/unused'), receipt)
    assert not receipt.exists()


def test_cli_uses_requested_inventory_and_receipt(runnable, tmp_path, monkeypatch, capsys):
    inv, output, _ = runnable
    path = tmp_path / 'inventory.json'
    path.write_text(json.dumps(inv))
    assert preflight.main(['--inventory', str(path), '--repo', str(tmp_path),
                           '--receipt', str(output / 'receipt')]) == 0
    assert json.loads(capsys.readouterr().out)['rehearsal_authorized'] is False



def test_source_change_on_reinspection_is_rejected(inspected, monkeypatch):
    import copy
    inv, containers, cg, proc, _, _ = inspected
    original = preflight.docker_json
    for changed in ('config', 'pid', 'missing'):
        def docker(*args):
            result = original(*args)
            if args == ('container', 'inspect', inv['source_id']):
                if changed == 'missing':
                    return []
                result = copy.deepcopy(result)
                if changed == 'config':
                    result[0]['Config']['Env'].append('UNEXPECTED_CHANGE=1')
                else:
                    result[0]['State']['Pid'] = 456
            return result
        monkeypatch.setattr(preflight, 'docker_json', docker)
        with pytest.raises(ValueError):
            preflight.inspect_current(inv, cg, proc)
