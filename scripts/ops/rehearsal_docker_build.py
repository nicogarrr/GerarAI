"""Local Docker legacy-build backend with terminal-request acknowledgment.

Not a CLI. Only an audited rehearsal adapter should call this backend. No SSH,
remote endpoint, registry push, prune or production command. API errors/raw build
output stay in memory, not copied into receipts. Actual VM behavior is untested.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import socket
import tarfile
import threading
import time
import urllib.parse
from pathlib import Path

from rehearsal_build_workers import BUILD, RECIPE, ROLE, RUN, worker_proof
from rehearsal_guard import full_id, require
from rehearsal_preflight import COUNTERS


class LocalDocker(http.client.HTTPConnection):
    def __init__(self):
        super().__init__('localhost', timeout=35)

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect('/var/run/docker.sock')


class DockerBuild:
    """One request, one fixed build; caller holds private run lock throughout."""
    def __init__(self, archive, generated_dockerfile_sha256, output_tag,
                 client_factory=LocalDocker, cgroup_root=Path('/sys/fs/cgroup'), proc_root=Path('/proc'),
                 clock=time.monotonic, sleep=time.sleep):
        self.archive = Path(archive)
        self.generated_hash = generated_dockerfile_sha256
        self.tag = output_tag
        self.client_factory = client_factory
        self.cgroup_root = cgroup_root
        self.proc_root = proc_root
        self.clock, self.sleep = clock, sleep
        self.inventory = self.rendered = None
        self.thread = None
        self.terminal = None
        self.transport_failed = False
        self.cancelled = False
        self.requested = False
        self.observed = set()

    def api(self, method, path, body=None):
        connection = self.client_factory()
        try:
            payload = None if body is None else json.dumps(body).encode()
            connection.request(method, path, body=payload, headers={'Content-Type': 'application/json'})
            response = connection.getresponse()
            raw = response.read()
            require(200 <= response.status < 300, 'Docker operation rejected')
            return json.loads(raw) if raw else None
        finally:
            connection.close()

    def owned(self, item):
        ident = full_id(item['Id'])
        require(ident != self.inventory['source_id'] and ident not in self.inventory['production_ids'], 'Forbidden daemon worker')
        labels = item['Config'].get('Labels') or {}
        expected = {RUN: self.inventory['run_id'], ROLE: 'build-worker', BUILD: self.rendered['build_id'],
                    RECIPE: self.rendered['recipe']}
        require(all(labels.get(k) == v for k, v in expected.items()), 'Worker ownership changed')
        # The unique per-build gate cannot belong to an earlier run/image. A
        # matching label alone does not authorize kill or exec.
        cmd = item['Config'].get('Cmd') or []
        require(len(cmd) == 3 and cmd[:2] == ['/bin/sh', '-c'] and
                cmd[2].startswith('n=0; while [ ! -f ' + self.rendered['gate_prefix'] + '-'),
                'Worker gate identity mismatch')
        return ident

    def inspect_workers(self):
        filters = {'label': [RUN + '=' + self.inventory['run_id'], ROLE + '=build-worker',
                             BUILD + '=' + self.rendered['build_id'], RECIPE + '=' + self.rendered['recipe']]}
        listed = self.api('GET', '/containers/json?all=1&filters=' + urllib.parse.quote(json.dumps(filters)))
        require(isinstance(listed, list), 'Docker worker listing unavailable')
        result = []
        for record in listed:
            ident = full_id(record['Id'])
            inspected = self.api('GET', '/containers/' + ident + '/json')
            require(inspected['Id'] == ident, 'Worker inspection ID mismatch')
            cmd = inspected['Config'].get('Cmd') or []
            is_gated = len(cmd) == 3 and cmd[:2] == ['/bin/sh', '-c'] and cmd[2].startswith(
                'n=0; while [ ! -f ' + self.rendered['gate_prefix'] + '-')
            # Classic LABEL/COPY/etc commits can leave non-running metadata
            # containers with inherited labels but no gated RUN command. They
            # are not released or killed as workers. A running mismatch fails.
            if not is_gated and not inspected['State']['Running']:
                continue
            self.owned(inspected)
            self.observed.add(ident)
            result.append(inspected)
        return result

    def start(self, inventory, rendered):
        require(self.thread is None, 'Build backend cannot be reused')
        self.inventory, self.rendered = inventory, rendered
        require(self.tag == 'gerarai-bench:' + inventory['run_id'] + '-' + rendered['build_id'], 'Private build tag required')
        require(self.archive.is_file() and not self.archive.is_symlink(), 'Private build archive required')
        require(not self.inspect_workers(), 'Run/build ownership already exists')
        # Querying the local tag is read-only. Do not overwrite any existing
        # image, even if it claims the same run label.
        existing = self.api('GET', '/images/json?all=1&filters=' + urllib.parse.quote(json.dumps({'reference': [self.tag]})))
        require(existing == [], 'Output image tag already exists')
        require(self.generated_hash == hashlib.sha256(rendered['dockerfile'].encode()).hexdigest(),
                'Generated Dockerfile fingerprint mismatch')
        with tarfile.open(self.archive, 'r:') as archive:
            members = archive.getmembers()
            names = [entry.name for entry in members]
            require(len(names) == len(set(names)) and 'Dockerfile.bench' in names, 'Unique generated recipe required')
            for entry in members:
                path = Path(entry.name)
                require(entry.isfile() and not path.is_absolute() and '..' not in path.parts and
                        not any(part == '.git' or part == 'docker.env' or part.startswith('.env') for part in path.parts),
                        'Build archive contains unsafe path/type/environment data')
            recipe = archive.extractfile('Dockerfile.bench').read()
            require(hashlib.sha256(recipe).hexdigest() == self.generated_hash, 'Archive recipe mismatch')
        self.requested = True
        self.thread = threading.Thread(target=self._request, name='gerarai-owned-build', daemon=True)
        self.thread.start()

    def _request(self):
        connection = self.client_factory()
        connection.timeout = 14400  # quiet compilation is not transport failure after35s
        try:
            query = {'t': self.tag, 'dockerfile': 'Dockerfile.bench', 'version': '1', 'pull': '0', 'nocache': '1',
                         'networkmode': 'none', 'cgroupparent': self.inventory['cgroup_parent'], 'cpuperiod': '100000',
                         'cpuquota': '200000', 'cpushares': '2', 'memory': str(3 * 1024**3), 'memswap': str(4 * 1024**3),
                         'rm': '0', 'forcerm': '0'}
            # The caller packages exactly one audited gated Dockerfile at this
            # fixed name. No server-side/frontend/remote-context URL is used.
            with self.archive.open('rb') as archive:
                connection.request('POST', '/build?' + urllib.parse.urlencode(query), body=archive,
                                   headers={'Content-Type': 'application/x-tar', 'Content-Length': str(os.fstat(archive.fileno()).st_size)})
                response = connection.getresponse()
                if not 200 <= response.status < 300:
                    response.read()
                    self.terminal = {'exit_code': 1, 'http_rejected': True}
                    return
                last = None
                failed = False
                for raw in response:
                    frame = json.loads(raw)
                    if frame.get('error') or frame.get('errorDetail'):
                        failed = True
                        last = {'exit_code': 1, 'daemon_error': True}
                    aux = frame.get('aux') or {}
                    if aux.get('ID') and not failed:
                        last = {'exit_code': 0, 'image_id': aux['ID'], 'recipe': self.rendered['recipe']}
                # Only a terminal daemon frame followed by clean HTTP stream end
                # is acknowledgment. EOF with no terminal frame is inconclusive.
                self.terminal = last
        except Exception:  # noqa: BLE001 - transport loss is unconfirmed, never success
            self.transport_failed = True
        finally:
            connection.close()

    def snapshot(self):
        require(self.inventory is not None, 'No owned build started')
        info = self.api('GET', '/info')
        parent = self.cgroup_root / self.inventory['cgroup_parent']
        files = {name: (parent / name).read_text() for name in COUNTERS}
        result = []
        for inspected in self.inspect_workers():
            if not inspected['State']['Running']:
                continue
            pid = inspected['State']['Pid']
            require(isinstance(pid, int) and not isinstance(pid, bool) and pid > 0, 'Invalid live worker PID')
            proc = self.proc_root / str(pid)
            membership = (proc / 'cgroup').read_text()
            network = {name: (proc / 'net' / name).read_text() for name in ('dev', 'route', 'ipv6_route')}
            result.append((inspected, info, files, membership, network))
        return result

    def release(self, ident, marker):
        require(not self.cancelled, 'Cannot release worker during cancellation')
        record = next((record for record in self.snapshot() if record[0]['Id'] == ident), None)
        require(record is not None, 'Worker vanished before release')
        proof = worker_proof(self.inventory, self.rendered, *record)
        require(proof['marker'] == marker, 'Release marker mismatch')
        # Fixed shell script, positional marker, no shell interpolation of data.
        created = self.api('POST', '/containers/' + ident + '/exec', {
            'AttachStdout': True, 'AttachStderr': True, 'Tty': False, 'User': '0',
            'Cmd': ['/bin/sh', '-c', 'test ! -e "$1" && : > "$1"', 'release', marker]})
        exec_id = full_id(created['Id'])
        # Detached exec avoids copying user/application output; inspect checks
        # completion. The command writes only the single in-container gate.
        self.api('POST', '/exec/' + exec_id + '/start', {'Detach': True, 'Tty': False})
        deadline = self.clock() + 5
        while self.clock() < deadline:
            state = self.api('GET', '/exec/' + exec_id + '/json')
            if not state['Running']:
                require(state['ExitCode'] == 0, 'Worker gate release failed')
                return
            self.sleep(.01)
        raise RuntimeError('Worker release acknowledgment missing')

    def daemon_settled(self):
        return bool((self.cancelled and not self.requested) or
                    (self.thread is not None and not self.thread.is_alive() and self.terminal is not None))

    def finish(self):
        require(self.daemon_settled() and not self.cancelled, 'Daemon build did not finish normally')
        result = dict(self.terminal)
        if result['exit_code'] == 0:
            # Final immutable image and local tag must agree. No image is
            # accepted solely because a matching tag happens to exist.
            from rehearsal_guard import image_id
            ident = image_id(result['image_id'])
            inspected = self.api('GET', '/images/' + urllib.parse.quote(ident, safe='') + '/json')
            require(inspected['Id'] == ident and self.tag in inspected.get('RepoTags', []), 'Final image ID/tag mismatch')
            labels = inspected['Config'].get('Labels') or {}
            require(labels.get(RUN) == self.inventory['run_id'] and labels.get(BUILD) == self.rendered['build_id'] and
                    labels.get(RECIPE) == self.rendered['recipe'], 'Final image ownership/recipe mismatch')
        return result

    def kill_owned(self, ids):
        # Include late gated workers from the request, not just released ones.
        for inspected in self.inspect_workers():
            ident = self.owned(inspected)
            if inspected['State']['Running']:
                self.api('POST', '/containers/' + ident + '/kill?signal=SIGKILL')
        # Killing does not remove containers/images/volumes. Cleanup identities
        # are retained for the operator; no prune or broad name deletion.

    def cancel_request(self):
        self.cancelled = True
        if not self.requested:
            return True  # start failed before sending any build request
        deadline = self.clock() + 90
        while self.clock() < deadline:
            self.kill_owned(self.observed)
            if self.daemon_settled():
                return True
            # The next RUN, if a step completed during cancellation, remains
            # gated and is killed on the next pass. A gated RUN also times out.
            self.sleep(.1)
        return False  # transport/request uncertainty is a blocker, not a green
