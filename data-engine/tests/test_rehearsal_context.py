"""Real local Git/archive fixtures, no Docker or VM."""
import hashlib
import importlib.util
import json
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[2] / 'scripts/ops'
sys.path.insert(0, str(OPS))
try:
    spec = importlib.util.spec_from_file_location('rehearsal_context', OPS / 'rehearsal_context.py')
    context = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(context)
finally:
    sys.path.remove(str(OPS))


@pytest.fixture
def source(tmp_path):
    repo = tmp_path / 'source'
    repo.mkdir()
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    files = {'Dockerfile': 'FROM local\nRUN true\n', 'package-lock.json': '{}',
             'scripts/install-hooks.mjs': '// fixture', 'data-engine/main.py': '# fixture',
             '.gitignore': 'ignored-secret\n', '.dockerignore': '*.log\n',
             '.env.production': 'SYNTHETIC_NOT_A_SECRET', 'nested/docker.env': 'SYNTHETIC_NOT_A_SECRET'}
    for name, value in files.items():
        path = repo / name
        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_text(value)
    subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Synthetic', '-c', 'user.email=synthetic@example.invalid',
                    'commit', '-qm', 'Synthetic context'], check=True)
    sha = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    (repo / 'ignored-secret').write_text('SYNTHETIC_NOT_A_SECRET')
    return repo, sha


def test_exact_committed_context_never_includes_ignored_or_environment(source, tmp_path):
    repo, sha = source
    result = context.package(repo, sha, 'frontend', 'FROM local\nRUN true\n', tmp_path/'context.tar', tmp_path/'manifest.json')
    assert not result['release_authorized']
    assert result['archive_sha256'] == hashlib.sha256((tmp_path/'context.tar').read_bytes()).hexdigest()
    assert json.loads((tmp_path/'manifest.json').read_text()) == result
    with tarfile.open(tmp_path/'context.tar') as archive:
        names = archive.getnames()
        assert 'ignored-secret' not in names and '.env.production' not in names and 'nested/docker.env' not in names
        assert 'Dockerfile.bench' in names and '.dockerignore' in names and 'data-engine/main.py' in names
        assert archive.extractfile('Dockerfile.bench').read() == b'FROM local\nRUN true\n'
    assert result['excluded_environment_paths'] == ['.env.production', 'nested/docker.env']
    with pytest.raises(FileExistsError):
        context.package(repo, sha, 'frontend', 'FROM local', tmp_path/'context.tar', tmp_path/'other.json')


def test_backend_prefix_and_determinism(source, tmp_path):
    repo, sha = source
    args = (repo, sha, 'backend', 'FROM local\nRUN true\n')
    first = context.package(*args, tmp_path/'one.tar', tmp_path/'one.json')
    second = context.package(*args, tmp_path/'two.tar', tmp_path/'two.json')
    assert first['archive_sha256'] == second['archive_sha256']
    with tarfile.open(tmp_path/'one.tar') as archive:
        assert set(archive.getnames()) == {'main.py', 'Dockerfile.bench'}
    for name in ('package-lock.json', 'scripts/install-hooks.mjs', 'Dockerfile'):
        assert context.fingerprint(repo, sha, name) == hashlib.sha256((repo/name).read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        context.fingerprint(repo, sha, '.env.production')


@pytest.mark.parametrize('role,generated', [('rollout', 'FROM local'), ('frontend', ''), ('frontend', None)])
def test_bad_input(source, tmp_path, role, generated):
    with pytest.raises(ValueError):
        context.package(*source, role, generated, tmp_path/'one.tar', tmp_path/'one.json')


def test_checkout_change_and_unsafe_output(source, tmp_path):
    repo, sha = source
    with pytest.raises(ValueError):
        context.package(repo, sha, 'frontend', 'FROM local', repo/'one.tar', tmp_path/'one.json')
    with pytest.raises(ValueError):
        context.package(repo, sha, 'frontend', 'FROM local', tmp_path/'same', tmp_path/'same')
    (repo/'Dockerfile').write_text('changed')
    with pytest.raises(ValueError):
        context.package(repo, sha, 'frontend', 'FROM local', tmp_path/'one.tar', tmp_path/'one.json')


def test_manifest_reuse_never_overwrites(source, tmp_path):
    manifest = tmp_path/'manifest.json'
    manifest.write_text('old evidence')
    with pytest.raises(FileExistsError):
        context.package(*source, 'frontend', 'FROM local', tmp_path/'one.tar', manifest)
    assert manifest.read_text() == 'old evidence'



def test_tracked_symlink_is_rejected_without_reading_target(source, tmp_path):
    repo, _ = source
    (repo/'link').symlink_to('/etc/passwd')
    subprocess.run(['git', '-C', str(repo), 'add', 'link'], check=True)
    subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Synthetic', '-c', 'user.email=synthetic@example.invalid',
                    'commit', '-qm', 'Synthetic symlink'], check=True)
    sha = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    with pytest.raises(ValueError):
        context.package(repo, sha, 'frontend', 'FROM local', tmp_path/'one.tar', tmp_path/'one.json')
    assert not (tmp_path/'one.json').exists()
