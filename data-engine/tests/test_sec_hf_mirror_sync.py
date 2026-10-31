"""Mirror SEC->HF: el sync resuelve CIK, descarga companyfacts + submissions
+ historicos y sube al dataset SOLO lo que cambio (sha1). Sin credenciales
falla cerrado (exit 2) antes de tocar la red."""

import json
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sec_hf_mirror_sync as sync  # noqa: E402


class _Resp:
    def __init__(self, payload, status=200, headers=None):
        self._payload = payload
        self.status_code = status
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _FakeSECClient:
    """httpx.Client falso: sirve company_tickers, companyfacts y submissions
    (con un fichero historico) desde memoria."""

    def __init__(self, *a, **k):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url):
        self.calls.append(url)
        if url.endswith("company_tickers.json"):
            return _Resp({"0": {"cik_str": 123, "ticker": "XYZ", "title": "XYZ Corp"}})
        if "companyfacts" in url:
            return _Resp({"cik": 123, "facts": {"us-gaap": {}}})
        if url.endswith("CIK0000000123-submissions-001.json"):
            return _Resp({"accessionNumber": ["A9"], "form": ["10-K"], "reportDate": ["2019-12-31"]})
        if "submissions" in url:
            return _Resp({"filings": {
                "recent": {"accessionNumber": ["A1"], "form": ["10-K"], "reportDate": ["2025-12-31"]},
                "files": [{"name": "CIK0000000123-submissions-001.json"}],
            }})
        raise AssertionError(f"URL inesperada: {url}")


class _CommitOperationAdd:
    """Sustituto de huggingface_hub.CommitOperationAdd para el test."""

    def __init__(self, *, path_in_repo, path_or_fileobj):
        self.path_in_repo = path_in_repo
        self.path_or_fileobj = path_or_fileobj


class _FakeHfApi:
    def __init__(self, token=None):
        self.uploads = {}
        self.commits = []
        self.remote_manifest = None  # dict "files" ya publicado, o None

    def create_repo(self, *a, **k):
        self.created = True

    def create_commit(self, *, repo_id, repo_type, operations, commit_message):
        # Un unico commit atomico por corrida.
        self.commits.append(list(operations))
        for op in operations:
            self.uploads[op.path_in_repo] = op.path_or_fileobj


@pytest.fixture
def fake_hf(monkeypatch):
    api = _FakeHfApi()
    module = types.ModuleType("huggingface_hub")
    module.HfApi = lambda token=None: api
    module.CommitOperationAdd = _CommitOperationAdd

    def _hf_hub_download(repo_id, filename, repo_type=None, token=None):
        if api.remote_manifest is None:
            raise FileNotFoundError("sin manifest remoto")
        f = Path(api._tmpdir) / filename
        f.write_text(json.dumps({"files": api.remote_manifest}))
        return str(f)

    import tempfile
    api._tmpdir = tempfile.mkdtemp()
    module.hf_hub_download = _hf_hub_download
    monkeypatch.setitem(sys.modules, "huggingface_hub", module)
    monkeypatch.setattr(sync.httpx, "Client", _FakeSECClient)
    monkeypatch.setattr(sync.time, "sleep", lambda *_a: None)
    return api


def _tickers_file(tmp_path, monkeypatch, text="XYZ\n# comentario\n\n"):
    f = tmp_path / "sec_mirror_tickers.txt"
    f.write_text(text)
    monkeypatch.setattr(sync, "TICKERS_FILE", f)
    return f


def test_sync_sube_layout_oficial_y_manifest(tmp_path, monkeypatch, fake_hf):
    _tickers_file(tmp_path, monkeypatch)
    monkeypatch.setenv("HF_TOKEN", "t")
    monkeypatch.setenv("HF_DATASET", "owner/cavaai-sec-mirror")
    monkeypatch.setenv("SEC_USER_AGENT", "GerarAI research nicoiglesiasgarcia10@gmail.com")
    assert sync.main() == 0
    esperado = {
        "company_tickers.json",
        "companyfacts/CIK0000000123.json",
        "submissions/CIK0000000123.json",
        "submissions/CIK0000000123-submissions-001.json",
        "manifest.json",
    }
    assert set(fake_hf.uploads) == esperado
    manifest = json.loads(fake_hf.uploads["manifest.json"])
    assert manifest["tickers"] == {"XYZ": "0000000123"}
    assert manifest["synced_at"].endswith("Z")
    # proveniencia por archivo: sha1 de cada contenido oficial servido
    import hashlib
    assert manifest["files"]["companyfacts/CIK0000000123.json"] == hashlib.sha1(  # nosemgrep: python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1 -- fixture: replica el contrato de proveniencia sha1 del mirror HF (no criptografia; decision mia/main en scripts/sec_hf_mirror_sync.py)
        fake_hf.uploads["companyfacts/CIK0000000123.json"]).hexdigest()


def test_sync_no_resube_lo_que_no_cambio(tmp_path, monkeypatch, fake_hf):
    _tickers_file(tmp_path, monkeypatch)
    monkeypatch.setenv("HF_TOKEN", "t")
    monkeypatch.setenv("HF_DATASET", "d")
    monkeypatch.setenv("SEC_USER_AGENT", "GerarAI research nicoiglesiasgarcia10@gmail.com")
    assert sync.main() == 0
    assert len(fake_hf.commits) == 1  # publicacion atomica: un solo commit
    # Segunda corrida: el manifest remoto declara los sha1 ya publicados.
    import hashlib
    fake_hf.remote_manifest = {
        path: hashlib.sha1(content).hexdigest()  # nosemgrep: python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1 -- fixture: replica el contrato de proveniencia sha1 del mirror HF (no criptografia; decision mia/main en scripts/sec_hf_mirror_sync.py)
        for path, content in fake_hf.uploads.items()
        if path != "manifest.json"
    }
    fake_hf.uploads = {}
    assert sync.main() == 0
    # Solo se republica el manifest (synced_at nuevo); los datos no cambian.
    assert set(fake_hf.uploads) == {"manifest.json"}


def test_sync_sin_credenciales_falla_cerrado(tmp_path, monkeypatch):
    _tickers_file(tmp_path, monkeypatch)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HF_DATASET", raising=False)
    assert sync.main() == 2


def test_sync_ua_placeholder_falla_cerrado(tmp_path, monkeypatch, fake_hf):
    """SEC banea User-Agent placeholder (example.com/.local) con 403: el sync
    falla cerrado ANTES de tocar la red si el contacto no es real."""
    _tickers_file(tmp_path, monkeypatch)
    monkeypatch.setenv("HF_TOKEN", "t")
    monkeypatch.setenv("HF_DATASET", "d")
    for ua_malo in ("", "GerarAI/0.1 contact@example.com",
                    "GerarAI research contact@gerarai.local",
                    "sin-arroba"):
        monkeypatch.setenv("SEC_USER_AGENT", ua_malo)
        assert sync.main() == 2
    assert not fake_hf.uploads  # no llego a subir nada


class _FakeSECClientBRK:
    """EDGAR nombra Berkshire BRK-B; la lista local usa BRK.B. El alias del
    sync resuelve el CIK y el manifest conserva la identidad local."""

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url):
        if url.endswith("company_tickers.json"):
            return _Resp({"0": {"cik_str": 1067983, "ticker": "BRK-B", "title": "Berkshire Hathaway"}})
        if "companyfacts" in url:
            return _Resp({"cik": 1067983, "facts": {"us-gaap": {}}})
        if "submissions" in url:
            return _Resp({"filings": {
                "recent": {"accessionNumber": ["A1"], "form": ["10-K"], "reportDate": ["2025-12-31"]},
                "files": [],
            }})
        raise AssertionError(f"URL inesperada: {url}")


def test_sync_alias_brk_punto_resuelve_cik_de_brk_guion(tmp_path, monkeypatch, fake_hf):
    _tickers_file(tmp_path, monkeypatch, text="BRK.B\n")
    monkeypatch.setattr(sync.httpx, "Client", _FakeSECClientBRK)
    monkeypatch.setenv("HF_TOKEN", "t")
    monkeypatch.setenv("HF_DATASET", "owner/cavaai-sec-mirror")
    monkeypatch.setenv("SEC_USER_AGENT", "GerarAI research nicoiglesiasgarcia10@gmail.com")
    assert sync.main() == 0
    manifest = json.loads(fake_hf.uploads["manifest.json"])
    # identidad local conservada; CIK de BRK-B
    assert manifest["tickers"] == {"BRK.B": "0001067983"}
    assert "companyfacts/CIK0001067983.json" in fake_hf.uploads
