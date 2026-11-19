#!/usr/bin/env python3
"""Read-only Docker/source/cgroup preflight, NOT a rehearsal executor.

No create/run/exec/build/remove/restore/deploy operations. A passing inspection
is not permission to start work and does not prove restored data provenance,
source DB contents, image contents, builder workers or resource use over time.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import stat
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from deploy_preparation import exact_source
from rehearsal_guard import (
    full_id,
    private_path,
    require,
    validate_cgroup,
    validate_inventory,
    validate_source,
    validate_volume_exclusivity,
)

DOCKER = ['docker', '--host', 'unix:///var/run/docker.sock']
COUNTERS = ('cpu.max', 'memory.max', 'memory.swap.max', 'cgroup.type', 'cpu.stat',
            'memory.current', 'memory.peak', 'memory.events', 'io.stat')


def docker_json(*args):
    """No inherited Docker context, remote daemon or shell command expansion."""
    return json.loads(subprocess.check_output([*DOCKER, *args], text=True, timeout=30))


def inspect_current(inventory, cgroup_root=Path('/sys/fs/cgroup'), proc_root=Path('/proc')):
    """Collect sensitive inspection objects in memory, return only safe fields."""
    validate_inventory(inventory)
    ids = collect_ids()
    require(isinstance(ids, list) and ids, 'Complete nonempty container ID list required')
    for ident in ids:
        full_id(ident)
    require(inventory['source_id'] in ids, 'Source container missing')
    containers = docker_json('container', 'inspect', *ids)
    require(isinstance(containers, list) and {item['Id'] for item in containers} == set(ids),
            'Incomplete current container inspection')
    source = next(item for item in containers if item['Id'] == inventory['source_id'])
    volumes = docker_json('volume', 'inspect', inventory['source_volume'])
    require(isinstance(volumes, list) and len(volumes) == 1, 'Exact source volume inspection required')
    validate_source(inventory, source, volumes[0])
    validate_volume_exclusivity(inventory, containers)
    info = docker_json('info', '--format', '{{json .}}')
    parent = cgroup_root / inventory['cgroup_parent']
    require(parent.is_dir() and not parent.is_symlink(), 'Dedicated cgroup missing/symlinked')
    files = {name: (parent / name).read_text() for name in COUNTERS}
    pid = source['State']['Pid']
    membership = (proc_root / str(pid) / 'cgroup').read_text()
    validate_cgroup(inventory, info, files, {pid: membership})
    # The source must be the ONLY workload in the dedicated slice at preflight.
    # Enumerating all descendants also catches unlabelled helper/build workers.
    source_scope = '/' + inventory['cgroup_parent'] + '/docker-' + inventory['source_id'] + '.scope'
    require(membership.strip() == '0::' + source_scope, 'Unexpected source scope')
    for procs in parent.rglob('cgroup.procs'):
        for value in procs.read_text().split():
            full = (proc_root / str(int(value)) / 'cgroup').read_text().strip()
            require(full == '0::' + source_scope, 'Foreign workload already occupies rehearsal slice')
    # The parent cgroup itself is not included by rglob on all implementations.
    require(not (parent / 'cgroup.procs').read_text().strip(), 'Processes directly in parent slice')
    current = docker_json('container', 'inspect', inventory['source_id'])
    require(isinstance(current, list) and len(current) == 1, 'Source reinspection unavailable')
    validate_source(inventory, current[0], volumes[0])
    for key in ('Id', 'Image', 'Config', 'HostConfig', 'NetworkSettings', 'Mounts'):
        require(current[0][key] == source[key], 'Source configuration changed during inspection')
    require(current[0]['State']['Pid'] == pid, 'Source restarted during inspection')
    return {'source_id': source['Id'], 'source_image': source['Image'],
            'source_volume': volumes[0]['Name'], 'source_pid': pid,
            'source_cgroup': membership.strip(), 'resource_snapshot': files,
            'production_ids': list(inventory['production_ids']),
            'docker_cgroup_version': info['CgroupVersion'], 'docker_cgroup_driver': info['CgroupDriver']}


def collect_ids():
    output = subprocess.check_output([*DOCKER, 'container', 'ls', '--all', '--no-trunc', '--quiet'],
                                     text=True, timeout=30)
    result = output.splitlines()
    for ident in result:
        full_id(ident)
    require(len(result) == len(set(result)), 'Duplicate IDs returned by Docker')
    return result


def run(inventory, repo, receipt):
    validate_inventory(inventory)
    tree = exact_source(repo, inventory['sha'])
    root = Path(inventory['root'])
    output = private_path(Path(inventory['output']), root)
    lock = private_path(Path(inventory['lock']), root)
    require(output.is_dir() and lock.is_file(), 'Output directory and lock must already exist')
    require(receipt.parent == output and not receipt.is_symlink(), 'Receipt must be a direct child of output')
    # Do not create or truncate an operator's lock; refuse symlinks and shared
    # writable lock inodes. Preflight acquires no global production backup lock.
    fd = os.open(lock, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        st = os.fstat(fd)
        require(stat.S_ISREG(st.st_mode) and st.st_nlink == 1 and st.st_uid == os.getuid() and
                not (st.st_mode & 0o022), 'Lock must be private and owned by current operator')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        checked = inspect_current(inventory)
        require(exact_source(repo, inventory['sha']) == tree, 'Source changed during inspection')
        report = {'schema': 1, 'kind': 'inspection_only_not_execution_permission', 'run_id': inventory['run_id'],
                      'sha': inventory['sha'], 'tree': tree, 'checked': checked,
                      'inspected_utc': datetime.now(timezone.utc).isoformat(),  # noqa: UP017 - ops Python 3.10
                      'rehearsal_authorized': False, 'release_authorized': False,
                      'limitations': ['No restore/content provenance checked', 'No build worker inspected',
                                   'One instant, not duration-wide resource proof', 'No IO ceiling enforced',
                                   'Docker daemon overhead outside slice', 'No workload launched']}
        with os.fdopen(os.open(receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600),
                       'w', encoding='utf-8') as stream:
            json.dump(report, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        return report
    finally:
        os.close(fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args(argv)
    report = run(json.loads(args.inventory.read_text()), args.repo, args.receipt)
    print(json.dumps({'kind': report['kind'], 'rehearsal_authorized': False, 'release_authorized': False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
