#!/usr/bin/env python3
"""Pilot-only offline tiny build/cancellation exercise, not the full benchmark.

Requires separately approved isolated source setup and audited exact SHA. No
setup, DB query, pull, restore, migration, production or rollout. Three fixed
small offline builds verify actual workers and cancellation before a larger
rehearsal is considered. Docker residues are retained by immutable ID.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import stat
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path

from deploy_preparation import exact_source
from rehearsal_build_workers import BuildIncomplete, render, supervise
from rehearsal_context import add
from rehearsal_docker_build import DockerBuild
from rehearsal_guard import image_id, private_path, require
from rehearsal_preflight import docker_json, inspect_current

CASES = {'smoke-success': 'printf "offline-smoke-ok\\n"',
         'smoke-failure': 'exit 17', 'smoke-cancel': 'sleep 120'}


class ObservedBuild(DockerBuild):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.released_proofs = []

    def release(self, ident, marker):
        super().release(ident, marker)
        self.released_proofs.append({'id': ident, 'marker': marker})


def exercise(inventory, base, output, engine_factory=ObservedBuild, on_progress=None):
    """Closed literal Dockerfiles, never command bodies from input JSON."""
    results = []
    for name, body in CASES.items():
        recipe = render('FROM ' + base['Id'] + '\nRUN ' + body + '\n', inventory['run_id'], name, {base['Id']: base})
        digest = hashlib.sha256(recipe['dockerfile'].encode()).hexdigest()
        path = output / (name + '.tar')
        with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600), 'wb') as stream, \
                tarfile.open(fileobj=stream, mode='w|') as archive:
            add(archive, 'Dockerfile.bench', recipe['dockerfile'].encode(), 0o600)
        engine = engine_factory(path, digest, 'gerarai-bench:' + inventory['run_id'] + '-' + name)
        if on_progress:
            on_progress({'case': name, 'status': 'running', 'tag': engine.tag})
        try:
            started = time.monotonic()
            if name == 'smoke-success':
                proof = supervise(inventory, recipe, engine, 30)
                result = {'case': name, 'status': 'verified', 'worker_proofs': proof['proofs'], 'image_id': proof['image_id']}
            else:
                try:
                    supervise(inventory, recipe, engine, 5 if name == 'smoke-cancel' else 30)
                except BuildIncomplete:
                    # Expected failure is accepted ONLY after a real RUN was
                    # released and a daemon error conclusively ended the request.
                    require(engine.released_proofs and engine.daemon_settled() and not engine.snapshot() and
                            engine.terminal is not None and engine.terminal.get('exit_code') == 1 and
                            engine.terminal.get('daemon_error') is True,
                            'Expected-failure smoke lacks worker release/terminal-error/cleanup proof')
                    if name == 'smoke-cancel':
                        require(engine.cancelled is True, 'Cancellation case did not reach cancellation path')
                    result = {'case': name, 'status': 'expected_failure_verified',
                              'released_workers': engine.released_proofs, 'daemon_terminal_error': True,
                              'daemon_cancellation_confirmed': engine.cancelled}
                else:
                    raise RuntimeError('Deliberately failing/cancelled smoke unexpectedly succeeded')
            residues = engine.inspect_workers()
            require(all(not worker['State']['Running'] for worker in residues), 'Live smoke worker residue')
            result.update(seconds=round(time.monotonic() - started, 6),
                          retained_container_ids=[worker['Id'] for worker in residues],
                          all_observed_container_ids=sorted(engine.observed), build_recipe_sha256=recipe['recipe'])
        except BaseException:
            if on_progress:
                on_progress({'case': name, 'status': 'failed_or_cleanup_unconfirmed', 'tag': engine.tag,
                             'all_observed_container_ids': sorted(engine.observed)})
            raise
        if on_progress:
            on_progress(result)
        results.append(result)
    return results


def run(inventory, repo, base_id, receipt):
    tree = exact_source(repo, inventory['sha'])
    root = Path(inventory['root'])
    output = private_path(Path(inventory['output']), root)
    lock = private_path(Path(inventory['lock']), root)
    require(output.is_dir() and output.stat().st_mode & 0o777 == 0o700, 'Smoke output must be private0700')
    require(receipt.parent == output and receipt.name == 'smoke.json', 'Fixed smoke receipt path inside output required')
    image_id(base_id)
    descriptor = os.open(lock, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        st = os.fstat(descriptor)
        require(stat.S_ISREG(st.st_mode) and st.st_nlink == 1 and st.st_uid == os.getuid() and
                not (st.st_mode & 0o022), 'Private owned lock required')
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = inspect_current(inventory)
        base = docker_json('image', 'inspect', base_id)
        require(isinstance(base, list) and len(base) == 1 and base[0]['Id'] == base_id, 'Local exact smoke base missing')
        # Validate recipe/base before creating running receipt or a build request.
        render('FROM '+base_id+'\nRUN true\n', inventory['run_id'], 'smoke-success', {base_id: base[0]})
        with os.fdopen(os.open(receipt, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600),
                       'w', encoding='utf-8') as stream:
            report = {'schema': 1, 'kind': 'tiny_offline_smoke_not_benchmark_permission', 'status': 'running',
                      'sha': inventory['sha'], 'tree': tree, 'base_image_id': base_id,
                      'run_id': inventory['run_id'], 'started_utc': datetime.now(timezone.utc).isoformat(),  # noqa: UP017
                      'before': before, 'rehearsal_authorized': False, 'release_authorized': False}
            save(stream, report)
            try:
                report['cases'] = []
                def progress(case):
                    report['cases'] = [value for value in report['cases'] if value['case'] != case['case']] + [case]
                    save(stream, report)
                report['cases'] = exercise(inventory, base[0], output, on_progress=progress)
                require(exact_source(repo, inventory['sha']) == tree, 'Source drift during smoke')
                report['after'] = inspect_current(inventory)
                report['status'] = 'verified_tiny_smoke_only'
            except BaseException:
                report['status'] = 'failed_or_cleanup_unconfirmed'
                save(stream, report)
                raise
            report['ended_utc'] = datetime.now(timezone.utc).isoformat()  # noqa: UP017
            save(stream, report)
            return report
    finally:
        os.close(descriptor)


def save(stream, report):
    stream.seek(0)
    json.dump(report, stream, indent=2)
    stream.write('\n')
    stream.truncate()
    stream.flush()
    os.fsync(stream.fileno())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--base-image', required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args(argv)
    result = run(json.loads(args.inventory.read_text()), args.repo, args.base_image, args.receipt)
    print(json.dumps({'status': result['status'], 'rehearsal_authorized': False, 'release_authorized': False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
