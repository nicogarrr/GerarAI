"""Synthetic worker lifecycles only. This is not proof of VM Docker behavior."""
import copy
import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

from tests.test_rehearsal_guard import cgroup_files
from tests.test_rehearsal_guard import records as records

OPS = Path(__file__).resolve().parents[2] / 'scripts/ops'
sys.path.insert(0, str(OPS))
try:
    spec = importlib.util.spec_from_file_location('rehearsal_build_workers', OPS / 'rehearsal_build_workers.py')
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
finally:
    sys.path.remove(str(OPS))

BASE = {'node:22-alpine': {'Id': 'sha256:' + 'e'*64, 'Config': {}}}
NETWORK = {'dev': 'header\nheader\nlo: 0 0 0\n', 'route': 'Iface Destination Gateway\n', 'ipv6_route': ''}


def rendered():
    return build.render('FROM node:22-alpine AS base\nRUN echo one\nRUN echo two\n', 'bench-20261119-a', 'frontend', BASE)


@pytest.fixture
def worker(records):
    inv = records[0]
    recipe = rendered()
    ident = 'f'*64
    marker = recipe['gate_prefix'] + '-1'
    obj = dict(Id=ident, Config=dict(Labels={build.RUN: inv['run_id'], build.ROLE: 'build-worker',
                                           build.BUILD: 'frontend', build.STEP: '1', build.RECIPE: recipe['recipe']},
                                   Cmd=['/bin/sh', '-c', f'( n=0; while [ ! -f {marker} ]; do placeholder']),
               HostConfig=dict(CgroupParent=inv['cgroup_parent'], Privileged=False, NetworkMode='none'),
               State=dict(Pid=456, Running=True), Mounts=[], NetworkSettings=dict(Ports={}))
    return inv, recipe, obj, {'CgroupVersion': '2', 'CgroupDriver': 'systemd'}, cgroup_files(), \
        '0::/gerarai_bench.slice/docker-' + ident + '.scope', copy.deepcopy(NETWORK)


def test_each_run_gets_unique_marker_and_local_pinned_base():
    result = rendered()
    assert result['steps'] == ['1', '2']
    assert 'FROM sha256:' + 'e'*64 in result['dockerfile']
    assert result['gate_prefix'] + '-1' in result['dockerfile']
    assert result['gate_prefix'] + '-2' in result['dockerfile']
    assert result['gate_prefix'] != rendered()['gate_prefix']
    assert result['dockerfile'].count('done ) || exit 125;') == 2
    assert build.render('FROM node:22-alpine AS base\nFROM base AS next\nRUN echo a \\\n && echo b\n',
                        'bench-20261119-a', 'frontend', BASE)['steps'] == ['1']


@pytest.mark.parametrize('text', [
    '', 'RUN echo no', 'FROM node:22-alpine', 'FROM missing\nRUN echo a',
    '# syntax=docker/dockerfile:latest\nFROM node:22-alpine\nRUN true',
    '# escape=`\nFROM node:22-alpine\nRUN true', 'FROM node:22-alpine\nRUN echo \\',
    'FROM --platform=arm64 node:22-alpine\nRUN true', 'FROM $BASE\nRUN true',
    'FROM node:22-alpine AS INVALID\nRUN true',
    'FROM node:22-alpine AS base\nFROM base AS base\nRUN true',
    'FROM node:22-alpine\nSHELL ["sh","-c"]\nRUN true',
    'FROM node:22-alpine\nRUN ["true"]', 'FROM node:22-alpine\nRUN --mount=x true',
    'FROM node:22-alpine\nRUN <<EOF', 'FROM node:22-alpine\nRUN true\x00',
    'FROM node:22-alpine\nLABEL io.gerarai.bench.step=evil\nRUN true',
])
def test_unsupported_recipe_fails_closed(text):
    with pytest.raises(ValueError):
        build.render(text, 'bench-20261119-a', 'frontend', BASE)


def test_invalid_identity_or_external_base():
    for run, name in [('bad', 'frontend'), ('bench-20261119-a', 'rollout')]:
        with pytest.raises(ValueError):
            build.render('FROM node:22-alpine\nRUN true', run, name, BASE)
    for config in ({'OnBuild': ['RUN evil']}, {'Volumes': {'/data': {}}}, {'Shell': ['bash', '-c']}):
        images = copy.deepcopy(BASE)
        images['node:22-alpine']['Config'] = config
        with pytest.raises(ValueError):
            build.render('FROM node:22-alpine\nRUN true', 'bench-20261119-a', 'frontend', images)
    with pytest.raises(ValueError):
        build.render('FROM node:22-alpine\nRUN true', 'bench-20261119-a', 'frontend', dict(BASE, unused={}))


def test_real_identity_and_blocked_run_required(worker):
    proof = build.worker_proof(*worker)
    assert proof['step'] == '1' and proof['pid'] == 456
    for path, value in [(['Id'], 'c'*64), (['Config', 'Labels', build.RECIPE], 'bad'),
                        (['HostConfig', 'CgroupParent'], 'system.slice'), (['HostConfig', 'Privileged'], True),
                        (['HostConfig', 'NetworkMode'], 'bridge'), (['HostConfig', 'Binds'], ['/data']),
                        (['Mounts'], [{}]), (['HostConfig', 'PortBindings'], {'80/tcp': [{}]}),
                        (['NetworkSettings', 'Ports'], {'80/tcp': [{}]}), (['State', 'Running'], False),
                        (['Config', 'Cmd'], ['sh', '-c', 'true'])]:
        bad = copy.deepcopy(worker)
        target = bad[2]
        for part in path[:-1]:
            target = target[part]
        target[path[-1]] = value
        with pytest.raises(ValueError):
            build.worker_proof(*bad)
    bad = list(copy.deepcopy(worker))
    bad[5] = '0::/gerarai_bench.slice/docker-wrong.scope'
    with pytest.raises(ValueError):
        build.worker_proof(*bad)


@pytest.mark.parametrize('files', [
    {}, dict(NETWORK, dev=''), dict(NETWORK, dev='h\nh\nlo: 0\neth0: 0'),
    dict(NETWORK, route=''), dict(NETWORK, route='Iface Destination Gateway\nlo 00000000 00000000'),
    dict(NETWORK, route='Iface Destination Gateway\neth0 01000000 00000000'),
    dict(NETWORK, ipv6_route='invalid'),
    dict(NETWORK, ipv6_route='0'*32+' 00 '+'0'*32+' 00 '+'0'*32+' 0 0 0 00000000 lo'),
])
def test_external_or_unknown_network_fails(files):
    with pytest.raises(ValueError):
        build.validate_offline_network(files)


def test_only_loopback_routes_allowed():
    files = dict(NETWORK, route='Iface Destination Gateway\nlo 0000007F 00000000',
                 ipv6_route='0'*32+' 00 '+'0'*32+' 00 '+'0'*32+' 0 0 0 00000200 lo')
    assert build.validate_offline_network(files)


class FakeEngine:
    def __init__(self, worker):
        self.record = worker
        self.released = []
        self.started = 0
        self.snapshots = 0
        self.cancelled = False
        self.killed = None
        self.acknowledge = True
        self.remain = False
        self.result_code = 0
        self.missing = False

    def start(self, inventory, recipe):
        self.started += 1

    def snapshot(self):
        if self.cancelled:
            return [self.record[2:]] if self.remain else []
        self.snapshots += 1
        if self.missing:
            return []
        record = list(copy.deepcopy(self.record[2:]))
        if self.snapshots >= 2:
            record[0]['Id'] = '9'*64
            record[0]['Config']['Labels'][build.STEP] = '2'
            record[0]['Config']['Cmd'][2] = record[0]['Config']['Cmd'][2].replace('-1 ]', '-2 ]')
            record[3] = '0::/gerarai_bench.slice/docker-' + '9'*64 + '.scope'
        return [record]

    def release(self, ident, marker):
        self.released.append((ident, marker))

    def daemon_settled(self):
        return self.acknowledge if self.cancelled else self.snapshots >= 2

    def finish(self):
        return dict(exit_code=self.result_code, image_id='sha256:'+'8'*64, recipe=self.record[1]['recipe'])

    def failed_exit_codes(self):
        return [17]

    def cancel_request(self):
        self.cancelled = True
        return self.acknowledge

    def kill_owned(self, ids):
        self.killed = set(ids)


def test_two_real_workers_proved_before_release(worker):
    engine = FakeEngine(worker)
    result = build.supervise(*worker[:2], engine, 20, sleep=lambda seconds: None)
    assert len(result['proofs']) == 2 and not result['release_authorized']
    assert len(engine.released) == 2
    assert engine.killed is None


@pytest.mark.parametrize('failure', ['exit', 'missing', 'release', 'interrupt', 'cleanup', 'remain', 'timeout'])
def test_failures_are_not_green_and_cancel_in_daemon(worker, failure):
    engine = FakeEngine(worker)
    if failure == 'exit':
        engine.result_code = 1
    elif failure == 'missing':
        engine.missing = True
    elif failure in ('release', 'interrupt'):
        def raises(*args):
            if failure == 'interrupt':
                raise KeyboardInterrupt
            raise OSError('synthetic')
        engine.release = raises
    elif failure in ('cleanup', 'remain'):
        engine.result_code = 1
        engine.acknowledge = failure != 'cleanup'
        engine.remain = failure == 'remain'
    tick = iter([0, 100]) if failure == 'timeout' else None
    with pytest.raises(build.BuildIncomplete, match='unconfirmed' if failure in ('cleanup', 'remain') else 'confirmed'):
        build.supervise(*worker[:2], engine, 20, clock=(lambda: next(tick)) if tick else (lambda: 0), sleep=lambda n: None)
    assert engine.cancelled and engine.killed is not None


@pytest.mark.parametrize('timeout', [True, 0, -1, float('inf'), 14401])
def test_bad_timeout_does_not_launch(worker, timeout):
    engine = FakeEngine(worker)
    with pytest.raises(ValueError):
        build.supervise(*worker[:2], engine, timeout)
    assert not engine.started


def test_frontend_warm_recipe_requires_all_fingerprints():
    original = (Path(__file__).resolve().parents[2] / 'Dockerfile').read_text()
    fp = dict(lockfile='1'*64, **{'install-hooks': '2'*64}, dockerfile=hashlib.sha256(original.encode()).hexdigest())
    base = dict(Id='sha256:'+'3'*64, Config=dict(Labels={'io.gerarai.bench.deps.'+k: v for k, v in fp.items()}))
    deps = copy.deepcopy(base)
    deps['Id'] = 'sha256:'+'4'*64
    warm = build.warm_frontend(original, fp, base, deps)
    assert 'RUN npm run build' in warm and 'RUN npm ci' not in warm and 'RUN apk' not in warm
    assert 'FROM '+deps['Id']+' AS deps' in warm
    for fingerprints in ({}, dict(fp, lockfile='bad'), dict(fp, dockerfile='f'*64)):
        with pytest.raises(ValueError):
            build.warm_frontend(original, fingerprints, base, deps)
    broken = copy.deepcopy(deps)
    broken['Config']['Labels'] = {}
    with pytest.raises(ValueError):
        build.warm_frontend(original, fp, base, broken)
    broken = copy.deepcopy(deps)
    broken['Config']['OnBuild'] = ['RUN evil']
    with pytest.raises(ValueError):
        build.warm_frontend(original, fp, base, broken)
    changed = original.replace('RUN npm ci', 'RUN npm install')
    changedfp = dict(fp, dockerfile=hashlib.sha256(changed.encode()).hexdigest())
    for item in (base, deps):
        item['Config']['Labels'] = {'io.gerarai.bench.deps.'+k: v for k, v in changedfp.items()}
    with pytest.raises(ValueError):
        build.warm_frontend(changed, changedfp, base, deps)



def test_closed_build_command_has_no_production_tags_or_network(worker):
    inventory, recipe = worker[:2]
    root = inventory['output']
    result = build.legacy_command(inventory, recipe, root+'/context', root+'/Dockerfile.frontend')
    for value in ('--network=none', '--pull=false', '--no-cache', '--cgroup-parent=gerarai_bench.slice'):
        assert value in result['argv']
    assert result['env'] == {'PATH': '/usr/bin:/bin', 'DOCKER_BUILDKIT': '0'}
    assert 'main-' not in result['tag'] and result['tag'].startswith('gerarai-bench:')
    for context, dockerfile in [('/home/ubuntu/deploy', root+'/D'), (root+'/C', '/tmp/D'),
                                (root+'/../escape', root+'/D'), (root, root+'/D')]:
        with pytest.raises(ValueError):
            build.legacy_command(inventory, recipe, context, dockerfile)


def test_controller_never_releases_duplicate_step_or_reused_id(worker):
    for which in ('duplicate-step', 'reused-id', 'repeat-same'):
        engine = FakeEngine(worker)
        original = engine.snapshot
        def snapshot():
            result = original()
            if engine.snapshots >= 2 and result and not engine.cancelled:
                if which == 'duplicate-step':
                    result[0][0]['Config']['Labels'][build.STEP] = '1'
                    result[0][0]['Config']['Cmd'][2] = result[0][0]['Config']['Cmd'][2].replace('-2 ]', '-1 ]')
                elif which == 'reused-id':
                    result[0][0]['Id'] = 'f'*64
                    result[0][3] = worker[5]
                else:
                    return [copy.deepcopy(worker[2:])]
            return result
        engine.snapshot = snapshot
        with pytest.raises(build.BuildIncomplete):
            build.supervise(*worker[:2], engine, 20, clock=lambda: 0, sleep=lambda n: None)
        assert engine.cancelled and len(engine.released) == 1


def test_original_run_exit_and_shell_semantics_survive_render(tmp_path):
    import subprocess
    recipe = build.render('FROM node:22-alpine\nRUN false && echo unreachable\n',
                          'bench-20261119-a', 'frontend', BASE)
    run = next(line[4:] for line in recipe['dockerfile'].splitlines() if line.startswith('RUN '))
    gate = Path(recipe['gate_prefix']+'-1')
    gate.touch()
    try:
        result = subprocess.run(['/bin/sh', '-c', run], capture_output=True, text=True)
        assert result.returncode == 1 and result.stdout == ''
    finally:
        gate.unlink()



def test_remote_copy_source_and_inherited_entrypoint_are_not_allowed():
    with pytest.raises(ValueError):
        build.render('FROM node:22-alpine\nCOPY --from=registry.invalid/remote /app /app\nRUN true',
                     'bench-20261119-a', 'frontend', BASE)
    text = 'FROM node:22-alpine AS deps\nRUN true\nFROM deps AS final\nCOPY --from=deps /app /app\nRUN true'
    recipe = build.render(text, 'bench-20261119-a', 'frontend', BASE)
    assert recipe['dockerfile'].count('ENTRYPOINT []') == 2



@pytest.mark.parametrize('existing', [None, 'preexisting-exported'])
def test_gate_counter_does_not_change_original_shell_or_environment(existing):
    import os
    import subprocess
    body = 'printf "shell_n=%s\\n" "${n-unset}"; env | grep "^n=" || true'
    recipe = build.render('FROM node:22-alpine\nRUN '+body+'\n', 'bench-20261119-a', 'frontend', BASE)
    run = next(line[4:] for line in recipe['dockerfile'].splitlines() if line.startswith('RUN '))
    environment = dict(os.environ)
    environment.pop('n', None)
    if existing is not None:
        environment['n'] = existing
    gate = Path(recipe['gate_prefix']+'-1')
    gate.touch()
    try:
        original = subprocess.run(['/bin/sh', '-c', body], env=environment, capture_output=True, text=True)
        generated = subprocess.run(['/bin/sh', '-c', run], env=environment, capture_output=True, text=True)
        assert generated.returncode == original.returncode == 0
        assert generated.stdout == original.stdout
        assert ('shell_n=unset' in generated.stdout) if existing is None else ('n='+existing in generated.stdout)
    finally:
        gate.unlink()


def test_gate_failure_is_barrier_to_entire_original_body(tmp_path):
    import subprocess
    marker = tmp_path/'must-not-run'
    body = 'touch '+str(marker)+'; false || true'
    recipe = build.render('FROM node:22-alpine\nRUN '+body+'\n', 'bench-20261119-a', 'frontend', BASE)
    run = next(line[4:] for line in recipe['dockerfile'].splitlines() if line.startswith('RUN '))
    # Replace the gate's wait with a deterministic failure, never weaken the
    # original body. This proves || in the original cannot bypass failed gate.
    prefix, original = run.rsplit('done ) || exit 125; ', 1)
    assert prefix.startswith('( n=0;')
    failed = '( exit 1 ) || exit 125; '+original
    result = subprocess.run(['/bin/sh', '-c', failed], check=False)
    assert result.returncode == 125 and not marker.exists()


def test_typed_timeout_requires_released_worker_alive_at_deadline(worker):
    engine = FakeEngine(worker)
    engine.snapshot = lambda: [] if engine.cancelled else [worker[2:]]
    engine.daemon_settled = lambda: engine.cancelled
    ticks = iter([0, 0, 100])
    with pytest.raises(build.BuildIncomplete) as captured:
        build.supervise(*worker[:2], engine, 20, clock=lambda: next(ticks), sleep=lambda n: None)
    failure = captured.value
    assert failure.reason == 'timeout'
    assert failure.live_worker_ids == ('f'*64,)
    assert failure.cleanup_confirmed and engine.released
    assert failure.worker_exit_codes == ()


def test_immediate_daemon_error_is_not_timeout_or_live_cancellation(worker):
    engine = FakeEngine(worker)
    engine.result_code = 1
    engine.failed_exit_codes = lambda: [127]
    with pytest.raises(build.BuildIncomplete) as captured:
        build.supervise(*worker[:2], engine, 20, clock=lambda: 0, sleep=lambda n: None)
    failure = captured.value
    assert failure.reason == 'daemon_failed' and failure.worker_exit_codes == (127,)
    assert not failure.live_worker_ids
    assert failure.cleanup_confirmed and engine.cancelled  # does NOT mean timeout
