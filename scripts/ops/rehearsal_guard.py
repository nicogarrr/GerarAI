"""Fail-closed validation of Pilot-supplied isolated rehearsal inventory.

Pure checks only. This module creates no Docker resources and never accepts a
name prefix as evidence of isolation. Inputs must come from fresh Docker/cgroup
inspection, not self-attested labels or the historical preparation runner.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

RUN = 'io.gerarai.bench.run_id'
ROLE = 'io.gerarai.bench.role'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def full_id(value):
    require(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value),
            'Expected full immutable container ID')
    return value


def image_id(value):
    require(isinstance(value, str) and re.fullmatch('sha256:[0-9a-f]{64}', value),
            'Expected immutable local image ID')
    return value


def labels(actual, run_id, role):
    require(isinstance(actual, dict) and actual.get(RUN) == run_id and actual.get(ROLE) == role,
            'Run and role ownership labels must match inventory')


def private_path(path: Path, root: Path):
    """Existing absolute, symlink-free path under the explicit rehearsal root."""
    require(path.is_absolute() and root.is_absolute(), 'Absolute paths required')
    require(root.exists() and root.is_dir(), 'Rehearsal root must already exist')
    require(path.exists(), 'Inventoried path must already exist')
    for current in (path, *path.parents, root, *root.parents):
        require(not current.is_symlink(), 'Symlink in rehearsal path')
    require(path.resolve().is_relative_to(root.resolve()) and path != root,
            'Path must be strictly inside rehearsal root')
    for current in (path, *path.parents):
        require(current.stat().st_uid == os.getuid() and not (current.stat().st_mode & 0o022),
                'Rehearsal paths must be owned and not group/other writable')
        if current == root:
            break
    return path.resolve()


def validate_inventory(inventory):
    require(isinstance(inventory, dict), 'Inventory must be an object')
    required = {'schema', 'run_id', 'source_id', 'source_image', 'source_volume',
                'production_ids', 'root', 'output', 'lock', 'cgroup_parent',
                'cpu_max', 'memory_max', 'memory_swap_max', 'sha', 'source_db', 'source_version'}
    require(set(inventory) == required and inventory['schema'] == 1,
            'Exact versioned inventory fields required')
    run = inventory['run_id']
    require(isinstance(run, str) and re.fullmatch('[a-z0-9][a-z0-9-]{7,47}', run), 'Invalid run ID')
    full_id(inventory['source_id'])
    image_id(inventory['source_image'])
    require(isinstance(inventory['source_volume'], str) and
            re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}', inventory['source_volume']), 'Explicit source volume required')
    production = inventory['production_ids']
    require(isinstance(production, list) and production, 'Explicit nonempty production ID denylist required')
    for item in production:
        full_id(item)
    require(inventory['source_id'] not in production, 'Source is a production container')
    require(inventory['root'] == '/home/ubuntu/benchmarks/gerarai-6b2b/' + run, 'Dedicated per-run root required')
    require(inventory['output'] in (inventory['root'] + '/serial', inventory['root'] + '/overlap'),
            'Dedicated serial/overlap output required')
    require(inventory['lock'] == inventory['root'] + '/backup.lock', 'Exclusive per-run lock required')
    require(isinstance(inventory['sha'], str) and re.fullmatch('[0-9a-f]{40}', inventory['sha']), 'Full source SHA required')
    require(inventory['source_db'] == 'bench_source', 'Only isolated bench_source database allowed')
    require(isinstance(inventory['source_version'], str) and
            re.fullmatch('[a-zA-Z0-9_]{1,64}', inventory['source_version']), 'Actual restored version required')
    require(inventory['cgroup_parent'] == 'gerarai_bench.slice', 'Dedicated systemd slice required')
    require(inventory['cpu_max'] == '200000 100000' and inventory['memory_max'] == '8589934592' and
            inventory['memory_swap_max'] == '1073741824', 'Expected aggregate 2CPU/8GiB/swap1GiB budget')
    return inventory


def validate_source(inventory, container, volume):
    """Validate current docker inspect objects against the explicit inventory."""
    validate_inventory(inventory)
    require(container['Id'] == inventory['source_id'], 'Container ID mismatch')
    require(container['Id'] not in inventory['production_ids'], 'Production ID forbidden')
    require(container['Image'] == inventory['source_image'], 'Source image mismatch')
    labels(container['Config'].get('Labels'), inventory['run_id'], 'source')
    host = container['HostConfig']
    require(host['NetworkMode'] == 'none', 'Source must have no external network')
    ports = container['NetworkSettings'].get('Ports') or {}
    require(host.get('PortBindings') in ({}, None) and isinstance(ports, dict) and
            all(value in (None, []) for value in ports.values()), 'Published ports forbidden')
    require(set(container['NetworkSettings']['Networks']) <= {'none'}, 'Unexpected attached network')
    require(not host['Privileged'] and not host.get('CapAdd') and not host.get('Devices') and
            not host.get('DeviceRequests') and not host.get('VolumesFrom') and
            host.get('PidMode', '') == '' and host.get('IpcMode') in ('private', '') and
            host.get('UTSMode', '') == '' and not host.get('ExtraHosts') and
            host.get('UsernsMode', '') != 'host', 'Unsafe namespace or privilege setting')
    require(isinstance(container['State'].get('Pid'), int) and not isinstance(container['State']['Pid'], bool) and
            container['State']['Pid'] > 0, 'Positive source host PID required')
    require(container['State']['Running'] is True and not container['State'].get('Paused') and
            not container['State'].get('Restarting'), 'Source is not stably running')
    require(host['CgroupParent'] == inventory['cgroup_parent'], 'Source outside common resource parent')
    env = container['Config']['Env']
    require(isinstance(env, list) and all(isinstance(v, str) for v in env), 'Source environment unavailable')
    values = dict(item.split('=', 1) for item in env if '=' in item)
    require(len(values) == len(env), 'Malformed or duplicate source environment keys')
    require(values.get('POSTGRES_DB') == 'bench_source' and values.get('POSTGRES_USER') == 'postgres',
            'Unexpected source database/user')
    require(not any(key.endswith('_URL') or key in ('PGHOST', 'PGSERVICE', 'PGSERVICEFILE', 'PGDATABASE')
                    for key in values), 'External database/service environment forbidden')
    mounts = container['Mounts']
    require(len(mounts) == 1, 'Only the inventoried source data volume is allowed')
    mount = mounts[0]
    require(mount['Type'] == 'volume' and mount['Name'] == inventory['source_volume'] and
            mount['Destination'] == '/var/lib/postgresql/data' and mount['RW'] is True,
            'Unexpected source data mount')
    require(volume['Name'] == inventory['source_volume'] and volume['Driver'] == 'local' and
            not volume.get('Options'), 'Only a local, non-driver-mounted volume allowed')
    labels(volume.get('Labels'), inventory['run_id'], 'source-data')
    require(mount['Source'] == volume['Mountpoint'], 'Volume mountpoint mismatch')
    # Every other live/stopped container must be checked for use of this volume
    # by the collecting adapter. This pure validator cannot discover them.
    return True


def validate_volume_exclusivity(inventory, containers):
    require(isinstance(containers, list) and containers, 'Complete container inspection required')
    sources = [item for item in containers if item['Id'] == inventory['source_id']]
    require(len(sources) == 1, 'Exactly one inventoried source required')
    source_path = Path(sources[0]['Mounts'][0]['Source'])
    require(source_path.is_absolute(), 'Absolute source volume mountpoint required')
    seen = set()
    for container in containers:
        ident = full_id(container['Id'])
        require(ident not in seen, 'Duplicate container in inspection')
        seen.add(ident)
        if ident == inventory['source_id']:
            continue
        for mount in container['Mounts']:
            require(mount.get('Name') != inventory['source_volume'], 'Source volume shared')
            if mount.get('Type') == 'bind':
                path = Path(os.path.normpath(mount['Source']))
                require(path.is_absolute(), 'Absolute bind mount source required')
                require(not (source_path.is_relative_to(path) or path.is_relative_to(source_path)),
                        'Source data exposed through an ancestor or descendant bind mount')
                require(not path.is_relative_to('/var/lib/docker'), 'Docker data bind exposed')
    require(inventory['source_id'] in seen, 'Source absent from full container inspection')
    require(set(inventory['production_ids']) <= seen, 'Production inventory drift or incomplete inspection')
    return True



def validate_cgroup(inventory, docker_info, files, memberships):
    """Fresh host reads, including every supplied live worker PID membership.

    A daemon/client inside the slice is NOT proof that build workers are there.
    The collector must include source, dump/compression, restore, migration and
    actual builder worker host PIDs. io.stat is observation, never an IO ceiling.
    """
    validate_inventory(inventory)
    require(docker_info.get('CgroupVersion') == '2' and docker_info.get('CgroupDriver') == 'systemd',
            'Only Docker systemd cgroup v2 supported')
    for key in ('cpu.max', 'memory.max', 'memory.swap.max'):
        expected = inventory[{'cpu.max': 'cpu_max', 'memory.max': 'memory_max',
                              'memory.swap.max': 'memory_swap_max'}[key]]
        require(files.get(key, '').strip() == expected, 'Effective aggregate limit mismatch: ' + key)
    require(files.get('cgroup.type', '').strip() == 'domain', 'Domain cgroup required')
    for key in ('cpu.stat', 'memory.current', 'memory.peak', 'memory.events', 'io.stat'):
        require(key in files and isinstance(files[key], str), 'Required resource counter unavailable: ' + key)
    require(isinstance(memberships, dict) and memberships, 'Live workload PID proof required')
    parent = '/' + inventory['cgroup_parent'] + '/'
    for pid, content in memberships.items():
        require(isinstance(pid, int) and not isinstance(pid, bool) and pid > 0, 'Valid host PID required')
        lines = content.strip().splitlines()
        require(len(lines) == 1 and lines[0].startswith('0::' + parent), 'Worker outside aggregate slice')
        require('..' not in lines[0].split('/'), 'Invalid worker cgroup path')
    return True
