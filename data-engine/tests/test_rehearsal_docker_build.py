"""Local daemon backend tests are fake HTTP/proc fixtures, not VM execution."""
import hashlib
import importlib.util
import io
import json
import sys
import tarfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from tests.test_rehearsal_build_workers import worker as worker
from tests.test_rehearsal_guard import records as records

OPS = Path(__file__).resolve().parents[2] / 'scripts/ops'
sys.path.insert(0, str(OPS))
try:
    spec = importlib.util.spec_from_file_location('rehearsal_docker_build', OPS / 'rehearsal_docker_build.py')
    backend = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(backend)
finally:
    sys.path.remove(str(OPS))


class Response(io.BytesIO):
    status = 200


def response(value):
    return Response(json.dumps(value).encode())


@pytest.fixture
def engine(worker, tmp_path):
    inv, recipe = worker[:2]
    path = tmp_path / 'context.tar'
    with tarfile.open(path, 'w') as archive:
        data = recipe['dockerfile'].encode()
        member = tarfile.TarInfo('Dockerfile.bench')
        member.size = len(data)
        archive.addfile(member, io.BytesIO(data))
    obj = backend.DockerBuild(path, hashlib.sha256(recipe['dockerfile'].encode()).hexdigest(),
                              'gerarai-bench:'+inv['run_id']+'-frontend')
    obj.inventory, obj.rendered = inv, recipe
    return obj


def test_fixed_unix_socket(monkeypatch):
    sock = Mock()
    monkeypatch.setattr(backend.socket, 'socket', Mock(return_value=sock))
    client = backend.LocalDocker()
    client.connect()
    sock.connect.assert_called_once_with('/var/run/docker.sock')
    assert client.host == 'localhost'


def test_api_json_and_failure_closes_connection(engine):
    client = Mock()
    client.getresponse.return_value = response({'Id': 'a'*64})
    engine.client_factory = lambda: client
    assert engine.api('GET', '/info')['Id'] == 'a'*64
    assert client.close.called
    client.getresponse.return_value = Response(b'')
    assert engine.api('POST', '/exec/test/start', {'Detach': True}) is None
    client.getresponse.return_value = Response(b'{}')
    client.getresponse.return_value.status = 403
    with pytest.raises(ValueError):
        engine.api('GET', '/info')


def test_owned_requires_id_labels_and_unique_gate(engine, worker):
    record = worker[2]
    assert engine.owned(record) == 'f'*64
    record['Config']['Cmd'] = ['sh', '-c', 'other']
    with pytest.raises(ValueError):
        engine.owned(record)
    record['Id'] = 'c'*64
    with pytest.raises(ValueError):
        engine.owned(record)


def test_inspect_records_only_full_owned_ids(engine, worker):
    record = worker[2]
    engine.api = Mock(side_effect=[[{'Id': record['Id']}], record])
    assert engine.inspect_workers() == [record]
    assert record['Id'] in engine.observed
    engine.api = Mock(return_value=None)
    with pytest.raises(ValueError):
        engine.inspect_workers()


def test_start_fixed_archive_no_remote_builder(engine, monkeypatch):
    engine.inspect_workers = Mock(return_value=[])
    engine.api = Mock(return_value=[])
    thread = Mock()
    monkeypatch.setattr(backend.threading, 'Thread', Mock(return_value=thread))
    engine.start(engine.inventory, engine.rendered)
    assert engine.requested and thread.start.called
    with pytest.raises(ValueError):
        engine.start(engine.inventory, engine.rendered)


def test_start_refuses_existing_worker_tag_or_bad_archive(engine):
    inv, recipe = engine.inventory, engine.rendered
    engine.inspect_workers = Mock(return_value=[{}])
    with pytest.raises(ValueError):
        engine.start(inv, recipe)
    engine.inspect_workers.return_value = []
    engine.api = Mock(return_value=[{}])
    with pytest.raises(ValueError):
        engine.start(inv, recipe)
    engine.api.return_value = []
    engine.generated_hash = 'f'*64
    with pytest.raises(ValueError):
        engine.start(inv, recipe)
    assert not engine.requested


@pytest.mark.parametrize('frames,expected', [
    ([{'stream': 'progress'}], None), ([{'errorDetail': {'message': 'synthetic'}}], 1),
    ([{'aux': {'ID': 'sha256:'+'8'*64}}], 0),
])
def test_request_needs_terminal_frame_and_clean_stream_end(engine, frames, expected):
    client = Mock()
    client.getresponse.return_value = Response(b''.join(json.dumps(x).encode()+b'\n' for x in frames))
    engine.client_factory = lambda: client
    engine._request()
    if expected is None:
        assert engine.terminal is None
    else:
        assert engine.terminal['exit_code'] == expected
    path = client.request.call_args.args[1]
    assert '/build?' in path and 'version=1' in path and 'pull=0' in path and 'networkmode=none' in path
    assert 'cgroupparent=gerarai_bench.slice' in path
    assert client.close.called


def test_http_rejection_and_transport_loss_are_not_green(engine):
    client = Mock()
    rejected = Response(b'{}')
    rejected.status = 400
    client.getresponse.return_value = rejected
    engine.client_factory = lambda: client
    engine._request()
    assert engine.terminal['exit_code'] == 1
    engine.terminal = None
    client.getresponse.side_effect = ConnectionError('synthetic')
    engine._request()
    assert engine.transport_failed and engine.terminal is None


def test_snapshot_uses_real_pid_namespace_files(engine, worker, tmp_path):
    engine.cgroup_root = tmp_path / 'cg'
    parent = engine.cgroup_root / engine.inventory['cgroup_parent']
    parent.mkdir(parents=True)
    for name, content in worker[4].items():
        (parent / name).write_text(content)
    engine.proc_root = tmp_path / 'proc'
    proc = engine.proc_root / '456'
    (proc / 'net').mkdir(parents=True)
    (proc / 'cgroup').write_text(worker[5])
    for name, content in worker[6].items():
        (proc / 'net' / name).write_text(content)
    engine.api = Mock(return_value=worker[3])
    engine.inspect_workers = Mock(return_value=[worker[2]])
    assert engine.snapshot()[0][3] == worker[5]
    worker[2]['State']['Running'] = False
    assert engine.snapshot() == []


def test_release_rechecks_worker_and_uses_positional_marker(engine, worker):
    ident = worker[2]['Id']
    marker = worker[1]['gate_prefix']+'-1'
    engine.snapshot = Mock(return_value=[worker[2:]])
    engine.api = Mock(side_effect=[{'Id': '7'*64}, None, {'Running': False, 'ExitCode': 0}])
    engine.release(ident, marker)
    create = engine.api.call_args_list[0].args[2]
    assert create['Cmd'][-1] == marker and create['Cmd'][2] == 'test ! -e "$1" && : > "$1"'
    assert create['User'] == '0'
    engine.cancelled = True
    with pytest.raises(ValueError):
        engine.release(ident, marker)


def test_cancel_requires_daemon_terminal_response_not_cli_or_empty_list(engine):
    engine.requested = True
    engine.thread = Mock()
    engine.thread.is_alive.return_value = False
    engine.inspect_workers = Mock(return_value=[])
    assert not engine.daemon_settled()
    values = iter([0, 1, 100])
    engine.clock = lambda: next(values)
    engine.sleep = lambda seconds: None
    assert engine.cancel_request() is False
    engine.terminal = {'exit_code': 1}
    assert engine.daemon_settled()
    engine.clock = lambda: 0
    assert engine.cancel_request() is True


def test_kill_calls_daemon_for_own_id_only(engine, worker):
    engine.inspect_workers = Mock(return_value=[worker[2]])
    engine.api = Mock()
    engine.kill_owned(set())
    engine.api.assert_called_once_with('POST', '/containers/'+'f'*64+'/kill?signal=SIGKILL')
    worker[2]['State']['Running'] = False
    engine.api.reset_mock()
    engine.kill_owned(set())
    engine.api.assert_not_called()


def test_final_image_id_and_tag_are_rechecked(engine):
    engine.thread = Mock()
    engine.thread.is_alive.return_value = False
    engine.terminal = dict(exit_code=0, image_id='sha256:'+'8'*64, recipe=engine.rendered['recipe'])
    labels = {backend.RUN: engine.inventory['run_id'], backend.BUILD: 'frontend', backend.RECIPE: engine.rendered['recipe']}
    engine.api = Mock(return_value=dict(Id='sha256:'+'8'*64, RepoTags=[engine.tag], Config=dict(Labels=labels)))
    assert engine.finish()['exit_code'] == 0
    engine.api.return_value['RepoTags'] = ['other']
    with pytest.raises(ValueError):
        engine.finish()



def test_error_frame_cannot_be_overwritten_by_later_aux(engine):
    client = Mock()
    frames = [{'error': 'synthetic'}, {'aux': {'ID': 'sha256:'+'8'*64}}]
    client.getresponse.return_value = Response(b''.join(json.dumps(x).encode()+b'\n' for x in frames))
    engine.client_factory = lambda: client
    engine._request()
    assert engine.terminal['exit_code'] == 1


@pytest.mark.parametrize('name,kind', [('../escape', 'regular'), ('.env.production', 'regular'),
                                     ('docker.env', 'regular'), ('link', 'symlink'), ('Dockerfile.bench', 'duplicate')])
def test_unsafe_archive_is_never_submitted(engine, name, kind):
    with tarfile.open(engine.archive, 'a') as archive:
        entry = tarfile.TarInfo(name)
        if kind == 'symlink':
            entry.type = tarfile.SYMTYPE
            entry.linkname = '/etc/passwd'
        archive.addfile(entry, io.BytesIO(b''))
    engine.inspect_workers = Mock(return_value=[])
    engine.api = Mock(return_value=[])
    with pytest.raises(ValueError):
        engine.start(engine.inventory, engine.rendered)
    assert not engine.requested


def test_archive_recipe_is_compared_to_expected_hash(engine):
    with tarfile.open(engine.archive, 'w') as archive:
        entry = tarfile.TarInfo('Dockerfile.bench')
        entry.size = 5
        archive.addfile(entry, io.BytesIO(b'wrong'))
    engine.inspect_workers = Mock(return_value=[])
    engine.api = Mock(return_value=[])
    with pytest.raises(ValueError):
        engine.start(engine.inventory, engine.rendered)
    assert not engine.requested


def test_release_failure_or_timeout_never_claims_success(engine, worker):
    engine.snapshot = Mock(return_value=[worker[2:]])
    marker = engine.rendered['gate_prefix']+'-1'
    engine.api = Mock(side_effect=[{'Id': '7'*64}, None, {'Running': False, 'ExitCode': 1}])
    with pytest.raises(ValueError):
        engine.release('f'*64, marker)
    times = iter([0, 1, 10])
    engine.clock = lambda: next(times)
    engine.sleep = lambda n: None
    engine.api = Mock(side_effect=[{'Id': '7'*64}, None, {'Running': True}])
    with pytest.raises(RuntimeError):
        engine.release('f'*64, marker)


def test_cancel_before_submission_needs_no_daemon_kill(engine):
    engine.kill_owned = Mock()
    assert engine.cancel_request() is True
    assert engine.daemon_settled()
    engine.kill_owned.assert_not_called()



def test_stopped_metadata_containers_are_not_running_workers(engine, worker):
    import copy
    metadata = copy.deepcopy(worker[2])
    metadata['Id'] = '6'*64
    metadata['Config']['Cmd'] = ['/bin/sh', '-c', '#(nop) LABEL value']
    metadata['State']['Running'] = False
    engine.api = Mock(side_effect=[[{'Id': metadata['Id']}], metadata])
    assert engine.inspect_workers() == []
    metadata['State']['Running'] = True
    engine.api = Mock(side_effect=[[{'Id': metadata['Id']}], metadata])
    with pytest.raises(ValueError):
        engine.inspect_workers()


def test_cancel_waits_for_terminal_and_kills_late_worker(engine, worker):
    engine.requested = True
    engine.thread = Mock()
    engine.thread.is_alive.side_effect = [True, False]
    engine.terminal = {'exit_code': 1}
    engine.inspect_workers = Mock(side_effect=[[], [worker[2]]])
    engine.api = Mock()
    engine.clock = lambda: 0
    engine.sleep = lambda seconds: None
    assert engine.cancel_request() is True
    assert engine.inspect_workers.call_count == 2
    engine.api.assert_called_once_with('POST', '/containers/'+'f'*64+'/kill?signal=SIGKILL')


def test_broken_stream_after_stage_aux_is_unconfirmed(engine):
    client = Mock()
    client.getresponse.return_value = Response(json.dumps({'aux': {'ID': 'sha256:'+'8'*64}}).encode()+b'\ninvalid-json\n')
    engine.client_factory = lambda: client
    engine._request()
    assert engine.transport_failed and engine.terminal is None
