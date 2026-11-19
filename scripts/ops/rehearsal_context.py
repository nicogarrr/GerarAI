"""Package committed build inputs, not ignored/untracked working-tree files.

This is local file preparation only. It does not connect to Docker or a VM.
The caller supplies an already-reviewed generated gated Dockerfile. No archive
is trusted as a release image or build/restore gate merely because it exists.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import tarfile
from pathlib import PurePosixPath

from deploy_preparation import exact_source
from rehearsal_guard import require


def fingerprint(repo, sha, name):
    require(name in ('package-lock.json', 'scripts/install-hooks.mjs', 'Dockerfile'), 'Closed frontend fingerprint inputs')
    exact_source(repo, sha)
    content = subprocess.check_output(['git', '-C', str(repo), 'show', sha + ':' + name])
    return hashlib.sha256(content).hexdigest()


def excluded(name):
    parts = PurePosixPath(name).parts
    return any(part.startswith('.env') or part == 'docker.env' or part == '.git' for part in parts)


def package(repo, sha, role, generated, output, manifest):
    """Exclusive deterministic tar of git archive SHA plus generated recipe.

    Backend path names are stripped of their data-engine/ prefix. Frontend tar
    retains the committed .dockerignore for daemon-side filtering. Manifest
    records all tar inputs, including ones Docker may later ignore. Generated
    recipe is checked separately and never confused with a tracked source file.
    All files come from commit blobs, not mutable filesystem reads.
    """
    tree = exact_source(repo, sha)
    require(role in ('backend', 'frontend'), 'Closed source context roles only')
    require(isinstance(generated, str) and generated.strip(), 'Reviewed generated Dockerfile required')
    require(output.is_absolute() and manifest.is_absolute() and output != manifest, 'Distinct absolute output paths required')
    for path in (output, manifest):
        require(not path.resolve().is_relative_to(repo.resolve()), 'Context evidence must be outside checkout')
    hashes = {}
    omitted = []
    process = None
    # x never reuses a previous context. An error leaves a non-ready partial
    # artifact, never a completed manifest. Do not infer success from tar alone.
    with os.fdopen(os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb') as stream:
        try:
            process = subprocess.Popen(['git', '-C', str(repo), 'archive', '--format=tar', sha], stdout=subprocess.PIPE)
            with tarfile.open(fileobj=process.stdout, mode='r|') as source, tarfile.open(fileobj=stream, mode='w|', format=tarfile.PAX_FORMAT) as target:
                for entry in source:
                    require(not entry.name.startswith('/') and '..' not in PurePosixPath(entry.name).parts, 'Unsafe git archive path')
                    if entry.isdir():
                        continue
                    require(entry.isfile(), 'Only regular committed files allowed in build context')
                    name = entry.name
                    if role == 'backend':
                        if not name.startswith('data-engine/'):
                            continue
                        name = name[len('data-engine/'):]
                    if excluded(name):
                        omitted.append(name)
                        continue
                    require(name != 'Dockerfile.bench' and name not in hashes, 'Generated recipe collision/duplicate input')
                    data = source.extractfile(entry).read()
                    hashes[name] = hashlib.sha256(data).hexdigest()
                    add(target, name, data, entry.mode)
                add(target, 'Dockerfile.bench', generated.encode(), 0o600)
            process.stdout.close()
            require(process.wait(timeout=30) == 0, 'git archive failed')
        finally:
            if process is not None:
                process.stdout.close()
                if process.poll() is None:
                    process.kill()
                    process.wait()
        require(exact_source(repo, sha) == tree, 'Checkout changed during packaging')
    require(hashes, 'No committed context inputs selected')
    hasher = hashlib.sha256()
    with output.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            hasher.update(chunk)
    digest = hasher.hexdigest()
    result = {'schema': 1, 'kind': 'committed_context_not_build_gate', 'sha': sha, 'tree': tree, 'role': role,
              'files': hashes, 'excluded_environment_paths': sorted(omitted),
              'generated_dockerfile_sha256': hashlib.sha256(generated.encode()).hexdigest(),
              'archive_sha256': digest, 'release_authorized': False,
              'warning': 'Manifest includes committed tar inputs, not proof of effective image contents; daemon .dockerignore may exclude more.'}
    with os.fdopen(os.open(manifest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600),
                   'w', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write('\n')
    return result


def add(archive, name, data, mode):
    record = tarfile.TarInfo(name)
    record.size = len(data)
    record.mode = mode & 0o777  # no setuid/setgid metadata from source tree
    record.uid = record.gid = record.mtime = 0
    archive.addfile(record, io.BytesIO(data))
