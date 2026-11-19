"""Legacy-build RUN gates and daemon-worker lifecycle controller.

Library only, no CLI or default Docker client. The rehearsal adapter must supply
an audited backend implementing the methods used here. No real Docker command
is executed by this module. This is not yet a runnable rehearsal.

Every RUN is blocked until a host-side inspection proves its immutable ID,
run/step ownership and PID membership in the common bounded cgroup. Cancel
stops the build request, kills owned workers in the daemon and requires a
positive daemon-settled proof. An empty instantaneous worker list is not proof.
"""
from __future__ import annotations

import hashlib
import json
import re
import shlex
import time
import uuid
from pathlib import Path

from rehearsal_guard import ROLE, RUN, full_id, image_id, require, validate_cgroup

STEP = 'io.gerarai.bench.step'
BUILD = 'io.gerarai.bench.build'
RECIPE = 'io.gerarai.bench.recipe'
ALLOWED = {'FROM', 'RUN', 'ARG', 'ENV', 'LABEL', 'WORKDIR', 'USER', 'COPY', 'EXPOSE', 'CMD'}


def logical_lines(text):
    """Deliberately small shell-form Dockerfile subset. Reject other syntax."""
    require(isinstance(text, str) and text.strip(), 'Dockerfile text required')
    pending = ''
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            require(not line.lower().startswith(('# syntax=', '# escape=')), 'Parser directives unsupported')
            continue
        if line.endswith('\\'):
            pending += line[:-1] + ' '
            continue
        yield pending + line
        pending = ''
    require(not pending, 'Unterminated Dockerfile continuation')


def render(text, run_id, build_id, external_images):
    """Return gated Dockerfile and exact expected step set, not a build command.

    external_images maps each external FROM reference to a fresh image-inspect
    object pinned by the calling adapter. Stage aliases are retained. External
    base images with ONBUILD, custom shell or volumes are refused, because those
    could introduce work/data not covered by the RUN gates.
    """
    require(isinstance(run_id, str) and re.fullmatch('[a-z0-9][a-z0-9-]{7,47}', run_id), 'Invalid run ID')
    require(build_id in ('backend', 'frontend', 'smoke-success', 'smoke-failure', 'smoke-cancel'),
            'Closed build IDs only')
    recipe = hashlib.sha256(text.encode()).hexdigest()
    gate = '/tmp/gerarai-bench-release-' + uuid.uuid4().hex
    stages = set()
    used = set()
    lines = []
    steps = []
    in_stage = False
    for line in logical_lines(text):
        parts = line.split(None, 1)
        require(len(parts) == 2 and parts[0].upper() in ALLOWED, 'Unsupported Dockerfile instruction')
        instruction, body = parts[0].upper(), parts[1]
        require('<<' not in body and '\x00' not in body, 'Heredoc/NUL unsupported')
        if instruction == 'FROM':
            words = body.split()
            require(len(words) in (1, 3) and (len(words) == 1 or words[1].upper() == 'AS'), 'Unsupported FROM')
            ref = words[0]
            require(not ref.startswith('--') and '$' not in ref, 'Dynamic/platform FROM unsupported')
            if ref not in stages:
                require(ref in external_images, 'External base must be explicitly inspected')
                inspected = external_images[ref]
                pinned = image_id(inspected['Id'])
                config = inspected['Config']
                require(not config.get('OnBuild') and not config.get('Volumes') and
                        config.get('Shell') in (None, [], ['/bin/sh', '-c']), 'Unsafe external base behavior')
                ref = pinned
                used.add(words[0])
            suffix = '' if len(words) == 1 else ' AS ' + words[2]
            if suffix:
                require(re.fullmatch('[a-z][a-z0-9_-]*', words[2]) and words[2] not in stages, 'Invalid/duplicate stage')
                stages.add(words[2])
            lines.append('FROM ' + ref + suffix)
            lines.append('ENTRYPOINT []')  # no inherited entrypoint work before RUN gate
            in_stage = True
        else:
            require(in_stage, 'Instructions before FROM unsupported')
            require(RUN not in body and ROLE not in body and BUILD not in body and STEP not in body and RECIPE not in body,
                    'Source may not overwrite ownership labels')
            if instruction == 'COPY':
                for word in body.split():
                    if word.startswith('--from='):
                        require(word.split('=', 1)[1] in stages, 'COPY may reference only declared local stages')
            if instruction == 'RUN':
                require(not body.lstrip().startswith(('[', '--')), 'Only plain shell-form RUN supported')
                step = str(len(steps) + 1)
                steps.append(step)
                labels = {RUN: run_id, ROLE: 'build-worker', BUILD: build_id, STEP: step, RECIPE: recipe}
                lines.append('LABEL ' + ' '.join(key + '=' + json.dumps(value) for key, value in labels.items()))
                # Release uses a per-step nonce-like path to prevent earlier RUN
                # layers from granting future RUNs. Never use a shared gate file.
                marker = gate + '-' + step
                prefix = (f'( n=0; while [ ! -f {shlex.quote(marker)} ]; do '
                          'n=$((n+1)); [ "$n" -le 60 ] || exit 125; sleep 1; done ) || exit 125; ')
                # Keep original command exit status, shell short-circuit and
                # USER semantics. No set -e or shared shell state is injected.
                lines.append('RUN ' + prefix + body)
                continue
        if instruction != 'FROM':
            lines.append(instruction + ' ' + body)
    require(in_stage and steps, 'At least one gated RUN required')
    require(set(external_images) == used, 'Unused/ambiguous external image inventory')
    return {'dockerfile': '\n'.join(lines) + '\n', 'recipe': recipe, 'steps': steps,
            'gate_prefix': gate, 'run_id': run_id, 'build_id': build_id}


def worker_proof(inventory, rendered, worker, docker_info, cgroup_files, membership, network):
    """Return proof only for a blocked RUN worker on its real host cgroup."""
    ident = full_id(worker['Id'])
    require(ident != inventory['source_id'] and ident not in inventory['production_ids'], 'Forbidden worker ID')
    labels = worker['Config'].get('Labels') or {}
    step = labels.get(STEP)
    expected = {RUN: inventory['run_id'], ROLE: 'build-worker', BUILD: rendered['build_id'], RECIPE: rendered['recipe']}
    require(all(labels.get(key) == value for key, value in expected.items()) and step in rendered['steps'],
            'Worker ownership/recipe/step mismatch')
    host = worker['HostConfig']
    require(host['CgroupParent'] == inventory['cgroup_parent'] and not host['Privileged'] and
            not host.get('Binds') and not host.get('VolumesFrom') and not worker['Mounts'] and
            not host.get('Devices') and not host.get('DeviceRequests') and not host.get('CapAdd') and
            host.get('PidMode', '') == '' and host.get('IpcMode', '') in ('', 'private') and
            host.get('UTSMode', '') == '' and host.get('UsernsMode', '') != 'host' and not host.get('ExtraHosts'),
            'Worker has unsafe resources/namespaces')
    require(host['NetworkMode'] == 'none', 'This worker stage supports offline builds only')
    require(not host.get('PortBindings') and
            all(not bindings for bindings in worker['NetworkSettings'].get('Ports', {}).values()), 'Published worker port')
    pid = worker['State']['Pid']
    require(worker['State']['Running'] is True and not worker['State'].get('Paused') and
            not worker['State'].get('Restarting'), 'Worker not stably running')
    validate_cgroup(inventory, docker_info, cgroup_files, {pid: membership})
    require(membership.strip() == '0::/' + inventory['cgroup_parent'] + '/docker-' + ident + '.scope',
            'Worker cgroup identity mismatch')
    validate_offline_network(network)
    marker = rendered['gate_prefix'] + '-' + step
    cmd = worker['Config']['Cmd']
    require(isinstance(cmd, list) and cmd[:2] == ['/bin/sh', '-c'] and len(cmd) == 3 and
            cmd[2].startswith('( n=0; while [ ! -f ' + shlex.quote(marker) + ' ]; do '),
            'Worker is not executing expected blocked RUN')
    return {'id': ident, 'pid': pid, 'step': step, 'cgroup': membership.strip(), 'marker': marker}


class BuildIncomplete(RuntimeError):
    """Typed failure evidence, never permission or a successful build result."""
    def __init__(self, message, *, reason='other', live_worker_ids=(), worker_exit_codes=(), cleanup_confirmed=False):
        super().__init__(message)
        self.reason = reason
        self.live_worker_ids = tuple(live_worker_ids)
        self.worker_exit_codes = tuple(worker_exit_codes)
        self.cleanup_confirmed = cleanup_confirmed


def supervise(inventory, rendered, engine, timeout, clock=time.monotonic, sleep=time.sleep):
    """Backend contract is deliberately explicit and is NOT implemented here.

    engine starts one classic no-cache offline build with cgroup-parent, private
    tags and run/build/recipe labels. Its snapshots return worker inspections
    plus fresh info/cgroup/PID reads. release(id, marker) must reinspect identity
    immediately before exec and create only that marker as root inside worker.
    finish() returns image/source evidence after daemon build request resolves.
    daemon_settled() is a positive request-completion/cancellation acknowledgment,
    never merely an empty worker list or CLI exit. cancel_request() must prevent
    further RUN creation or report false. kill_owned() revalidates immutable ID
    and ownership before a daemon-side kill; it may not delete foreign IDs.
    """
    require(isinstance(timeout, (float, int)) and not isinstance(timeout, bool) and 0 < timeout <= 14400,
            'Bounded positive build timeout required')
    proofs = {}
    ids = set()
    failure = None
    reason = 'other'
    timeout_live = []
    worker_exits = []
    try:
        engine.start(inventory, rendered)
        deadline = clock() + timeout
        while True:
            if clock() >= deadline:
                reason = 'timeout'
                for record in engine.snapshot():
                    proof = worker_proof(inventory, rendered, *record)
                    if proof['step'] in proofs and proofs[proof['step']]['id'] == proof['id']:
                        timeout_live.append(proof['id'])
                raise ValueError('Build timeout')
            snapshot = engine.snapshot()
            for worker, info, files, membership, network in snapshot:
                proof = worker_proof(inventory, rendered, worker, info, files, membership, network)
                step, ident = proof['step'], proof['id']
                require(ident not in ids or (step in proofs and proofs[step]['id'] == ident), 'Worker identity reused')
                require(step not in proofs or proofs[step]['id'] == ident, 'Multiple workers for a single RUN')
                ids.add(ident)
                if step not in proofs:
                    # Record proof before release. Failure to release still
                    # takes cancellation path, never a successful build result.
                    proofs[step] = proof
                    engine.release(ident, proof['marker'])
            if engine.daemon_settled():
                result = engine.finish()
                if result['exit_code'] != 0:
                    reason = 'daemon_failed'
                    worker_exits = engine.failed_exit_codes()
                    raise ValueError('Daemon build failed')
                require(set(proofs) == set(rendered['steps']), 'Missing real worker proof for some RUNs')
                image_id(result['image_id'])
                require(result['recipe'] == rendered['recipe'], 'Final image recipe mismatch')
                return {'kind': 'build_worker_evidence_not_release_permission', 'image_id': result['image_id'],
                        'proofs': [proofs[step] for step in rendered['steps']], 'release_authorized': False}
            sleep(.1)
    except BaseException as error:  # noqa: BLE001 - cancel daemon work even on SystemExit/interrupt
        failure = error
    # Clean up after any error, including interruption. The backend, not this
    # Python process group, owns daemon cancellation. Keep the failure non-green
    # if cancellation cannot be confirmed, even if no workers are visible now.
    try:
        acknowledged = engine.cancel_request()
        engine.kill_owned(ids)
        require(acknowledged is True and engine.daemon_settled() is True,
                'Daemon cancellation unconfirmed: no readiness and operator follow-up required')
        require(not engine.snapshot(), 'Owned daemon workers remain after cancellation')
    except BaseException as cleanup_error:
        raise BuildIncomplete('Build failed and daemon cleanup is unconfirmed', reason=reason,
                              live_worker_ids=timeout_live, worker_exit_codes=worker_exits) from cleanup_error
    raise BuildIncomplete('Build failed; daemon cancellation confirmed', reason=reason,
                          live_worker_ids=timeout_live, worker_exit_codes=worker_exits, cleanup_confirmed=True) from failure



def validate_offline_network(files):
    """Host reads from /proc/HOST_PID/net in the exact worker namespace."""
    require(set(files) == {'dev', 'route', 'ipv6_route'}, 'Complete worker network namespace reads required')
    devices = files['dev'].splitlines()
    require(len(devices) >= 3, 'Network device inspection unavailable')
    interfaces = {line.split(':', 1)[0].strip() for line in devices[2:] if line.strip()}
    require(interfaces == {'lo'}, 'Non-loopback worker network interface')
    routes = files['route'].splitlines()
    require(routes and routes[0].split()[0] == 'Iface', 'IPv4 route inspection unavailable')
    for line in routes[1:]:
        words = line.split()
        require(len(words) >= 3 and words[0] == 'lo' and words[1] != '00000000',
                'External/default IPv4 worker route')
    for line in files['ipv6_route'].splitlines():
        words = line.split()
        require(len(words) == 10 and words[-1] == 'lo', 'External IPv6 route/interface')
        # Linux emits unreachable ::/0 reject routes on loopback; these are
        # not usable default routes. Require RTF_REJECT in that special case.
        if words[0] == '0' * 32 and words[1] == '00':
            require(int(words[8], 16) & 0x200, 'Usable default IPv6 worker route')
    return True


def warm_frontend(original, fingerprints, base, deps):
    """Specific audited offline derivative, not a general Dockerfile rewriter.

    Preconditions supplied from exact checkout: lockfile, hook and Dockerfile
    SHA256. Both prebuilt images must carry those three fingerprints and be
    local immutable IDs. Building these dependencies is outside the benchmark.
    """
    require(set(fingerprints) == {'lockfile', 'install-hooks', 'dockerfile'}, 'Exact dependency fingerprints required')
    require(all(re.fullmatch('[0-9a-f]{64}', value) for value in fingerprints.values()), 'Full SHA256 fingerprints required')
    require(hashlib.sha256(original.encode()).hexdigest() == fingerprints['dockerfile'], 'Dockerfile fingerprint mismatch')
    for inspected in (base, deps):
        image_id(inspected['Id'])
        config = inspected['Config']
        require(not config.get('OnBuild') and not config.get('Volumes') and
                config.get('Shell') in (None, [], ['/bin/sh', '-c']), 'Unsafe warm dependency image')
        for key, value in fingerprints.items():
            require((config.get('Labels') or {}).get('io.gerarai.bench.deps.' + key) == value,
                    'Warm dependency image fingerprint mismatch')
    lines = list(logical_lines(original))
    replacements = {
        'FROM node:22-alpine AS base': 'FROM ' + base['Id'] + ' AS base',
        'FROM base AS deps': 'FROM ' + deps['Id'] + ' AS deps',
        'RUN apk add --no-cache --upgrade "zlib>=1.4-r0"': None,
        'RUN apk add --no-cache libc6-compat': None,
        'RUN npm ci': None,
    }
    require(all(lines.count(line) == 1 for line in replacements), 'Frontend recipe drift: dependency setup must be reviewed')
    require(lines.count('RUN npm run build') == 1, 'Measured frontend compilation must remain')
    result = [replacements.get(line, line) for line in lines]
    return '\n'.join(line for line in result if line is not None) + '\n'



def legacy_command(inventory, rendered, context, dockerfile):
    """Closed offline/no-cache classic build argv, for a future audited adapter.

    Paths must be private exact-source exports validated by that adapter. No
    arbitrary flags, environment, production tag, remote context or registry
    output is accepted. This function returns argv/env; it does not run them.
    """
    require(rendered['run_id'] == inventory['run_id'], 'Build/run ownership mismatch')
    require(rendered['build_id'] in ('backend', 'frontend'), 'Closed build role required')
    root = Path(inventory['output'])
    context, dockerfile = Path(context), Path(dockerfile)
    require(context.is_absolute() and context.is_relative_to(root) and context != root,
            'Build context must be a private subdirectory of current output')
    require(dockerfile.is_absolute() and dockerfile.is_relative_to(root) and dockerfile != root,
            'Generated Dockerfile must be inside current output')
    require('..' not in context.parts and '..' not in dockerfile.parts, 'Path traversal forbidden')
    tag = 'gerarai-bench:' + inventory['run_id'] + '-' + rendered['build_id']
    command = ['docker', '--host', 'unix:///var/run/docker.sock', 'build', '--pull=false', '--no-cache',
               '--network=none', '--cgroup-parent=' + inventory['cgroup_parent'],
               '--cpu-period=100000', '--cpu-quota=200000', '--cpu-shares=2',
               '--memory=3g', '--memory-swap=4g', '--rm=false', '--force-rm=false',
               '--tag=' + tag, '--file=' + str(dockerfile), str(context)]
    # No DOCKER_HOST, context, config, proxy or user-controlled BuildKit choice.
    return {'argv': command, 'env': {'PATH': '/usr/bin:/bin', 'DOCKER_BUILDKIT': '0'}, 'tag': tag}
