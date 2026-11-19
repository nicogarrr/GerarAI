"""Pure inspection-fixture tests, never connect to Docker or production."""
import copy
import importlib.util
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[2] / 'scripts/ops/rehearsal_guard.py'
spec = importlib.util.spec_from_file_location('rehearsal_guard', PATH)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


@pytest.fixture
def records():
    inv = dict(schema=1, run_id='bench-20261119-a', source_id='a'*64, source_image='sha256:'+'b'*64,
               source_volume='bench-source', production_ids=['c'*64], root='/home/ubuntu/benchmarks/gerarai-6b2b/bench-20261119-a',
               output='/home/ubuntu/benchmarks/gerarai-6b2b/bench-20261119-a/serial',
               lock='/home/ubuntu/benchmarks/gerarai-6b2b/bench-20261119-a/backup.lock', cgroup_parent='gerarai_bench.slice', cpu_max='200000 100000',
               memory_max='8589934592', memory_swap_max='1073741824', sha='d'*40,
               source_db='bench_source', source_version='0138_facts_tenant_company_idx')
    volume = dict(Name='bench-source', Driver='local', Options=None, Mountpoint='/var/lib/docker/volumes/bench-source/_data',
                  Labels={guard.RUN: inv['run_id'], guard.ROLE: 'source-data'})
    source = dict(Id=inv['source_id'], Image=inv['source_image'],
                  Config=dict(Labels={guard.RUN: inv['run_id'], guard.ROLE: 'source'},
                              Env=['POSTGRES_DB=bench_source', 'POSTGRES_USER=postgres']),
                  State=dict(Running=True, Pid=123),
                  HostConfig=dict(NetworkMode='none', Privileged=False, IpcMode='private', CgroupParent='gerarai_bench.slice'),
                  NetworkSettings=dict(Ports={}, Networks={'none': {}}),
                  Mounts=[dict(Type='volume', Name=volume['Name'], Destination='/var/lib/postgresql/data',
                               Source=volume['Mountpoint'], RW=True)])
    return inv, source, volume


def test_valid_source_and_volume(records):
    assert guard.validate_source(*records)
    records[1]['NetworkSettings']['Ports'] = {'5432/tcp': None}
    assert guard.validate_source(*records)
    inv, source, _ = records
    assert guard.validate_volume_exclusivity(inv, [source, dict(Id='c'*64, Mounts=[])])


@pytest.mark.parametrize(('field', 'value'), [
    ('schema', 2), ('root', '/home/ubuntu/deploy'), ('output', '/home/ubuntu/backups'), ('lock', '/tmp/cavaai-pgbackup.lock'), ('run_id', '../escape'), ('source_id', 'c'*64), ('source_id', 'abc'),
    ('source_image', 'postgres:17'), ('production_ids', []), ('production_ids', ['short']),
    ('sha', 'main'), ('source_db', 'postgres'), ('source_version', ''),
    ('source_volume', '../bad'), ('cgroup_parent', '/x/../y'), ('cgroup_parent', 'relative'),
    ('cpu_max', 'max'), ('memory_max', ''), ('memory_swap_max', 'max'),
])
def test_bad_inventory(records, field, value):
    inv, source, volume = records
    inv[field] = value
    with pytest.raises(ValueError):
        guard.validate_source(inv, source, volume)


@pytest.mark.parametrize(('path', 'value'), [
    (['Id'], 'e'*64), (['Image'], 'sha256:'+'e'*64), (['Config', 'Labels'], {}),
    (['HostConfig', 'NetworkMode'], 'bridge'), (['HostConfig', 'PortBindings'], {'5432/tcp': [{}]}),
    (['NetworkSettings', 'Networks'], {'prod': {}}), (['NetworkSettings', 'Ports'], {'5432/tcp': [{}]}),
    (['HostConfig', 'Privileged'], True), (['HostConfig', 'CapAdd'], ['SYS_ADMIN']),
    (['HostConfig', 'Devices'], [{}]), (['HostConfig', 'DeviceRequests'], [{}]),
    (['HostConfig', 'VolumesFrom'], ['prod']), (['HostConfig', 'PidMode'], 'host'),
    (['HostConfig', 'IpcMode'], 'host'), (['HostConfig', 'UTSMode'], 'host'),
    (['HostConfig', 'ExtraHosts'], ['db:127.0.0.1']), (['HostConfig', 'UsernsMode'], 'host'),
    (['HostConfig', 'CgroupParent'], '/prod.slice'), (['State', 'Running'], False),
    (['State', 'Pid'], 0), (['State', 'Pid'], '../bad'), (['State', 'Paused'], True), (['State', 'Restarting'], True),
    (['Config', 'Env'], ['POSTGRES_DB=production', 'POSTGRES_USER=postgres']),
    (['Config', 'Env'], ['POSTGRES_DB=bench_source', 'POSTGRES_USER=postgres', 'DATABASE_URL=remote']),
    (['Config', 'Env'], ['POSTGRES_DB=bench_source', 'POSTGRES_USER=postgres', 'PGHOST=remote']),
    (['Config', 'Env'], ['POSTGRES_DB=bench_source', 'POSTGRES_DB=prod']),
    (['Mounts'], []), (['Mounts', 0, 'Type'], 'bind'), (['Mounts', 0, 'Name'], 'prod'),
    (['Mounts', 0, 'Source'], '/prod'), (['Mounts', 0, 'Destination'], '/wrong'),
    (['Mounts', 0, 'RW'], False),
])
def test_bad_source(records, path, value):
    inv, source, volume = records
    target = source
    for item in path[:-1]:
        target = target[item]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        guard.validate_source(inv, source, volume)


@pytest.mark.parametrize(('field', 'value'), [('Name', 'prod'), ('Driver', 'nfs'), ('Options', {'device': '/prod'}), ('Labels', {})])
def test_bad_volume(records, field, value):
    inv, source, volume = records
    volume[field] = value
    with pytest.raises(ValueError):
        guard.validate_source(inv, source, volume)


def test_volume_must_not_be_shared(records):
    inv, source, _ = records
    other = dict(Id='c'*64, Mounts=[dict(Name=inv['source_volume'])])
    with pytest.raises(ValueError):
        guard.validate_volume_exclusivity(inv, [source, other])
    other['Mounts'] = [dict(Type='bind', Source='/var/lib/docker/volumes')]
    with pytest.raises(ValueError):
        guard.validate_volume_exclusivity(inv, [source, other])
    for containers in ([], [source], [other], [source, copy.deepcopy(source)]):
        with pytest.raises(ValueError):
            guard.validate_volume_exclusivity(inv, containers)


def test_paths_refuse_symlinks_and_outside(tmp_path):
    root = tmp_path / 'bench'
    root.mkdir()
    output = root / 'run'
    output.mkdir()
    assert guard.private_path(output, root) == output
    link = root / 'link'
    link.symlink_to(output, target_is_directory=True)
    for path, parent in ((link, root), (root, root), (tmp_path, root), (Path('relative'), root),
                         (root / 'missing', root), (output, root / 'absent')):
        with pytest.raises(ValueError):
            guard.private_path(path, parent)



def cgroup_files():
    return {'cpu.max': '200000 100000', 'memory.max': '8589934592', 'memory.swap.max': '1073741824',
            'cgroup.type': 'domain', 'cpu.stat': 'usage_usec 1', 'memory.current': '1', 'memory.peak': '2',
            'memory.events': 'oom_kill 0', 'io.stat': ''}


def test_cgroup_v2_systemd_budget_and_pid_proof(records):
    inv = records[0]
    info = dict(CgroupVersion='2', CgroupDriver='systemd')
    files = cgroup_files()
    members = {123: '0::/gerarai_bench.slice/docker-abc.scope'}
    assert guard.validate_cgroup(inv, info, files, members)
    for key in ('CgroupVersion', 'CgroupDriver'):
        bad = dict(info, **{key: 'unsupported'})
        with pytest.raises(ValueError):
            guard.validate_cgroup(inv, bad, files, members)
    for key in files:
        bad = dict(files)
        del bad[key]
        with pytest.raises(ValueError):
            guard.validate_cgroup(inv, info, bad, members)
    for bad in ({}, {123: '0::/system.slice/docker.scope'}, {123: '0::/gerarai_bench.slice-evil/docker.scope'},
                {123: '0::/gerarai_bench.slice/../prod'}, {0: '0::/gerarai_bench.slice/docker.scope'}):
        with pytest.raises(ValueError):
            guard.validate_cgroup(inv, info, files, bad)



def test_paths_refuse_group_writable_root(tmp_path):
    root = tmp_path / 'bench'
    root.mkdir(mode=0o700)
    child = root / 'serial'
    child.mkdir()
    root.chmod(0o770)
    with pytest.raises(ValueError):
        guard.private_path(child, root)



@pytest.mark.parametrize('path', ['/', '/var/lib', '/var/lib/docker/volumes/bench-source/_data',
                                  '/var/lib/docker/volumes/bench-source/_data/sub', '/var/lib/docker/../', 'relative'])
def test_root_and_ancestor_binds_cannot_expose_source(records, path):
    inv, source, _ = records
    with pytest.raises(ValueError):
        guard.validate_volume_exclusivity(inv, [source, dict(Id='c'*64, Mounts=[dict(Type='bind', Source=path)])])
