#!/usr/bin/env python3
"""Time approved preparation commands or simulate a fixed preparation DAG.

No deployment, SSH, Docker, backup or migration commands are built in. Timing
runs only the operator's explicit argv, not a security sandbox. Plans never run
commands and are estimates, not gate receipts or permission to release.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

PHASES = (
    'pyright', 'ruff', 'backend', 'frontend', 'pg', 'backup_dump',
    'backup_restore', 'build_backend', 'build_front', 'migration_image',
)


def exact_source(repo: Path, sha: str) -> str:
    if not re.fullmatch('[0-9a-f]{40}', sha):
        raise ValueError('Expected a full lowercase 40-character commit SHA')
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()
    if git('rev-parse', 'HEAD') != sha:
        raise ValueError('Repository HEAD does not match frozen SHA')
    if git('status', '--porcelain', '--untracked-files=all'):
        raise ValueError('Repository must be clean, including untracked files')
    return git('rev-parse', 'HEAD^{tree}')


def _stop(process):
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        process.wait()
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass  # Child exited between timeout and signal; still reap it.
        process.wait()


def time_phase(repo: Path, sha: str, phase: str, output: Path,
               command: list[str], timeout: float) -> dict:
    """Exclusive receipt, UTC timestamps plus monotonic command wall time.

    Receipts attest only the supplied command's exit, not the semantics of any
    suite/backup. Operator must use the approved full scripts. Output/arguments/
    environment are never copied into receipts. Child output stays on its
    original stdout/stderr, so existing approved logging keeps working.
    """
    if phase not in PHASES or not command:
        raise ValueError('Known preparation phase and explicit command required')
    if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('Positive finite command timeout required')
    repo = repo.resolve()
    if output.resolve().is_relative_to(repo):
        raise ValueError('Receipt must be outside the source checkout')
    tree = exact_source(repo, sha)
    receipt = {'schema': 1, 'phase': phase, 'sha': sha, 'tree': tree,
               'status': 'running', 'started_utc': datetime.now(timezone.utc).isoformat()}  # noqa: UP017 - ops Python 3.10
    # x refuses old receipts and symlinks. Keep the descriptor, not a path-based
    # rewrite; an interruption leaves running/non-passing evidence, never green.
    with output.open('x', encoding='utf-8') as stream:
        json.dump(receipt, stream)
        stream.flush()
        os.fsync(stream.fileno())
        started = time.monotonic()
        process = None
        try:
            process = subprocess.Popen(command, cwd=repo, start_new_session=True)
            code = process.wait(timeout=timeout)
            receipt.update(status='passed' if code == 0 else 'failed', exit_code=code)
        except subprocess.TimeoutExpired:
            _stop(process)
            receipt.update(status='timeout', exit_code=124)
        except KeyboardInterrupt:
            if process is not None:
                _stop(process)
            receipt.update(status='interrupted', exit_code=130)
        except OSError:
            receipt.update(status='launch_failed', exit_code=127)
        receipt.update(ended_utc=datetime.now(timezone.utc).isoformat(),  # noqa: UP017 - ops Python 3.10
                       command_seconds=round(time.monotonic() - started, 6))
        try:
            if exact_source(repo, sha) != tree:
                raise ValueError('Source tree changed')
        except (ValueError, subprocess.CalledProcessError):
            receipt.update(status='source_changed', exit_code=125)
        stream.seek(0)
        json.dump(receipt, stream, indent=2)
        stream.write('\n')
        stream.truncate()
        stream.flush()
        os.fsync(stream.fileno())
    return receipt


def plan(durations: dict, mode: str, rollout_reserve: float = 600) -> dict:
    """Deterministic estimate. Never reads or accepts a green gate receipt."""
    if set(durations) != set(PHASES):
        raise ValueError('Provide all and only the ten preparation phase durations')
    for value in [*durations.values(), rollout_reserve]:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError('Durations and reserve must be finite non-negative seconds')
    if rollout_reserve < 300:
        raise ValueError('Keep at least 300 seconds of rollout/freshness reserve')
    if mode not in ('serial', 'overlap-build-backup'):
        raise ValueError('Unknown preparation mode')
    schedule = {}
    for index, phase in enumerate(PHASES):
        dependencies = [] if index == 0 else [PHASES[index - 1]]
        if mode == 'overlap-build-backup':
            if phase == 'build_backend':
                dependencies = ['pg']
            elif phase == 'migration_image':
                dependencies = ['build_front']
        start = max((schedule[item]['end_seconds'] for item in dependencies), default=0)
        schedule[phase] = {'after': dependencies, 'start_seconds': start,
                           'end_seconds': start + durations[phase]}
    ready = max(item['end_seconds'] for item in schedule.values())
    age = ready + rollout_reserve - schedule['backup_dump']['start_seconds']
    return {'kind': 'estimate_only_not_gate_evidence', 'mode': mode,
            'phases': schedule, 'preparation_seconds': ready,
            'rollout_reserve_seconds': rollout_reserve,
            'backup_age_at_reserved_change_seconds': age,
            'backup_freshness_budget_seconds': 7200,
            'backup_within_estimated_budget': age < 7200,
            'release_authorized': False,
            'barrier': list(PHASES),
            'warning': 'No execution. Recheck all exact-SHA gates, restore proof, hash and actual dump age before change. Parallel times assume no resource contention.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    timing = commands.add_parser('time')
    timing.add_argument('--repo', type=Path, required=True)
    timing.add_argument('--sha', required=True)
    timing.add_argument('--phase', choices=PHASES, required=True)
    timing.add_argument('--output', type=Path, required=True)
    timing.add_argument('--timeout', type=float, required=True)
    timing.add_argument('command', nargs=argparse.REMAINDER)
    simulation = commands.add_parser('plan')
    simulation.add_argument('--durations', type=Path, required=True)
    simulation.add_argument('--mode', choices=('serial', 'overlap-build-backup'), default='serial')
    simulation.add_argument('--rollout-reserve', type=float, default=600)
    args = parser.parse_args(argv)
    if args.action == 'plan':
        result = plan(json.loads(args.durations.read_text()), args.mode, args.rollout_reserve)
        print(json.dumps(result, indent=2))
        return 0
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    result = time_phase(args.repo, args.sha, args.phase, args.output, command, args.timeout)
    print(json.dumps({'phase': result['phase'], 'status': result['status'],
                      'command_seconds': result['command_seconds']}))
    code = result['exit_code']
    return code if 0 <= code <= 255 else 1


if __name__ == '__main__':
    raise SystemExit(main())
