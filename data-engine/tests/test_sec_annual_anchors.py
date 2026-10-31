"""F353: SECClient.annual_report_anchors - la evidencia de calendario fiscal
a nivel de filing (submissions): fusiona recent + ficheros historicos, filtra
a filings anuales (10-K y variantes) y descarta ficheros que fallan con
cobertura parcial (nunca rompe la ingesta)."""

import asyncio
import hashlib
import json

from app.services.connectors.sec import SECClient


def _subs(rows, files=None):
    recent = {"accessionNumber": [], "form": [], "reportDate": []}
    for accn, form, report in rows:
        recent["accessionNumber"].append(accn)
        recent["form"].append(form)
        recent["reportDate"].append(report)
    return {"filings": {"recent": recent, "files": files or []}}


class _FakeHTTPSEC(SECClient):
    def __init__(self, payloads):
        self._payloads = payloads  # {url-suffix: dict | Exception}

    async def _get_json(self, url):
        for suffix, payload in self._payloads.items():
            if url.endswith(suffix):
                if isinstance(payload, Exception):
                    raise payload
                return payload
        raise AssertionError(f"URL inesperada: {url}")


def test_fusiona_recent_e_historicos_y_filtra_formularios():
    main = _subs(
        [
            ("A1", "10-K", "2025-12-31"),
            ("A2", "10-Q", "2025-09-30"),   # trimestral: fuera
            ("A3", "8-K", ""),              # sin cierre: fuera
            ("A4", "10-K/A", "2024-12-31"), # enmienda: dentro
            ("A5", "20-F", "2023-12-31"),   # emisor extranjero: dentro
        ],
        files=[{"name": "CIK0000000001-submissions-001.json"}],
    )
    # Los ficheros historicos llevan las columnas en primer nivel (formato
    # real de la SEC), no bajo filings.recent.
    extra = _subs([("A6", "10-K", "2019-03-31"), ("A7", "S-1", "2019-01-01")])["filings"]["recent"]
    client = _FakeHTTPSEC({
        "CIK0000000001.json": main,
        "CIK0000000001-submissions-001.json": extra,
    })
    anchors = asyncio.run(client.annual_report_anchors("1"))
    assert anchors == {
        "A1": "2025-12-31",
        "A4": "2024-12-31",
        "A5": "2023-12-31",
        "A6": "2019-03-31",
    }


def test_fichero_historico_roto_es_cobertura_parcial_no_error():
    main = _subs(
        [("A1", "10-K", "2025-12-31")],
        files=[{"name": "CIK0000000001-submissions-001.json"}],
    )
    client = _FakeHTTPSEC({
        "CIK0000000001.json": main,
        "CIK0000000001-submissions-001.json": RuntimeError("SEC 403"),
    })
    assert asyncio.run(client.annual_report_anchors("1")) == {"A1": "2025-12-31"}


# --- Mirror HF como fallback de lectura (ban de IP de datacenter) ---

def test_fallback_a_mirror_hf_en_403(monkeypatch):
    from app.core.config import get_settings
    from app.services.connectors import sec_edgar

    get_settings.cache_clear()
    monkeypatch.setenv("SEC_HF_MIRROR_DATASET", "owner/cavaai-sec-mirror")
    get_settings.cache_clear()

    payload = {"filings": {"recent": {}}}
    payload_bytes = json.dumps(payload).encode()
    llamadas = {}
    monkeypatch.setattr(sec_edgar, "_MANIFEST_CACHE", {})
    sec_edgar.drain_mirror_serves()

    class _Resp:
        def __init__(self, data, status=200, content=None):
            self._data = data
            self.status_code = status
            self.headers = {}
            self.content = content if content is not None else json.dumps(data).encode()
        def raise_for_status(self):
            if self.status_code >= 400:
                import httpx as _httpx
                raise _httpx.HTTPStatusError(str(self.status_code), request=None, response=None)
        def json(self):
            return self._data

    class _H:
        """SEC directo da 403; el mirror sirve manifest fresco + documento."""
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, headers=None):
            from urllib.parse import urlparse
            host = urlparse(url).hostname or ""
            if host == "sec.gov" or host.endswith(".sec.gov"):
                return _Resp({}, status=403)
            if url.endswith("/manifest.json"):
                from datetime import UTC, datetime
                return _Resp({
                    "tickers": {},
                    "synced_at": datetime.now(UTC).isoformat(),
                    "files": {"submissions/CIK0000000001.json": hashlib.sha1(payload_bytes).hexdigest()},  # nosemgrep: python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1 -- fixture: replica el contrato de proveniencia sha1 del mirror HF (no criptografia; decision mia/main en scripts/sec_hf_mirror_sync.py)
                })
            llamadas["url"] = url
            return _Resp(payload, content=payload_bytes)

    monkeypatch.setattr(sec_edgar.httpx, "AsyncClient", _H)
    data = asyncio.run(sec_edgar._get_json(
        "https://data.sec.gov/submissions/CIK0000000001.json"))
    assert data == payload
    assert llamadas["url"].endswith(
        "/datasets/owner/cavaai-sec-mirror/resolve/main/submissions/CIK0000000001.json")
    get_settings.cache_clear()


# --- Fallback mirror por la ruta SECClient (la de la ingesta real) ---

def _mirror_env(monkeypatch):
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("SEC_HF_MIRROR_DATASET", "owner/cavaai-sec-mirror")
    get_settings.cache_clear()
    return get_settings


def test_secclient_403_cae_al_mirror(monkeypatch):
    """La ruta de ingesta (SECClient._get_json: company_facts, submissions,
    annual_report_anchors) cae al mirror HF ante 403 directo."""
    from app.services.connectors import sec_edgar
    from app.services.connectors.sec import SECClient

    _mirror_env(monkeypatch)
    payload = {"cik": 1, "facts": {"us-gaap": {}}}
    payload_bytes = json.dumps(payload).encode()
    llamadas = {}
    monkeypatch.setattr(sec_edgar, "_MANIFEST_CACHE", {})
    sec_edgar.drain_mirror_serves()

    class _Resp:
        def __init__(self, data, content=None):
            self._data = data
            self.status_code = 200
            self.content = content if content is not None else json.dumps(data).encode()
        def raise_for_status(self): pass
        def json(self): return self._data

    class _MirrorHTTP:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url):
            if url.endswith("/manifest.json"):
                from datetime import UTC, datetime
                return _Resp({
                    "tickers": {},
                    "synced_at": datetime.now(UTC).isoformat(),
                    "files": {"companyfacts/CIK0000000001.json": hashlib.sha1(payload_bytes).hexdigest()},  # nosemgrep: python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1 -- fixture: replica el contrato de proveniencia sha1 del mirror HF (no criptografia; decision mia/main en scripts/sec_hf_mirror_sync.py)
                })
            llamadas["url"] = url
            return _Resp(payload, content=payload_bytes)

    monkeypatch.setattr(sec_edgar.httpx, "AsyncClient", _MirrorHTTP)

    client = SECClient()
    import httpx as _httpx

    async def _get_403(url):
        req = _httpx.Request("GET", url)
        resp = _httpx.Response(403, request=req)
        resp.raise_for_status()

    client._get = _get_403
    data = asyncio.run(client.company_facts("0000000001"))
    assert data == payload
    assert llamadas["url"].endswith(
        "/datasets/owner/cavaai-sec-mirror/resolve/main/companyfacts/CIK0000000001.json")
    from app.core.config import get_settings
    get_settings.cache_clear()


def test_secclient_404_no_se_enmascara(monkeypatch):
    """Un 404 de la SEC es un fallo de dato: NO se consulta el mirror y el
    error original propaga."""
    from app.services.connectors import sec_edgar
    from app.services.connectors.sec import SECClient

    _mirror_env(monkeypatch)
    llamadas = {}

    class _MirrorHTTP:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url):
            llamadas["url"] = url
            raise AssertionError("el mirror no debe consultarse ante un 404")

    monkeypatch.setattr(sec_edgar.httpx, "AsyncClient", _MirrorHTTP)

    client = SECClient()
    import httpx as _httpx

    async def _get_404(url):
        req = _httpx.Request("GET", url)
        resp = _httpx.Response(404, request=req)
        resp.raise_for_status()

    client._get = _get_404
    try:
        asyncio.run(client.company_facts("0000000001"))
        raise AssertionError("debio propagar el 404")
    except _httpx.HTTPStatusError:
        pass
    assert llamadas == {}
    from app.core.config import get_settings
    get_settings.cache_clear()


def test_mirror_caducado_fail_closed(monkeypatch):
    """Manifest con synced_at > 48h: el mirror NO se sirve (dato viejo nunca
    como fresco); el error es claro."""
    from app.core.config import get_settings
    from app.services.connectors import sec_edgar

    get_settings.cache_clear()
    monkeypatch.setenv("SEC_HF_MIRROR_DATASET", "owner/cavaai-sec-mirror")
    get_settings.cache_clear()
    monkeypatch.setattr(sec_edgar, "_MANIFEST_CACHE", {})
    sec_edgar.drain_mirror_serves()

    class _Resp:
        def __init__(self, data):
            self._data = data
            self.status_code = 200
            self.headers = {}
        def raise_for_status(self): pass
        def json(self): return self._data

    class _StaleMirror:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, headers=None):
            assert url.endswith("/manifest.json"), "no debe pedir el documento"
            return _Resp({"tickers": {}, "synced_at": "2026-09-20T00:00:00Z"})

    monkeypatch.setattr(sec_edgar.httpx, "AsyncClient", _StaleMirror)
    try:
        asyncio.run(sec_edgar.mirror_get_json(
            "https://data.sec.gov/submissions/CIK0000000001.json"))
        raise AssertionError("debio fallar cerrado")
    except RuntimeError as e:
        assert "caducado" in str(e)
    get_settings.cache_clear()


def test_mirror_sin_synced_at_fail_closed(monkeypatch):
    """Manifest sin synced_at valido: fail closed igualmente."""
    from app.core.config import get_settings
    from app.services.connectors import sec_edgar

    get_settings.cache_clear()
    monkeypatch.setenv("SEC_HF_MIRROR_DATASET", "owner/cavaai-sec-mirror")
    get_settings.cache_clear()
    monkeypatch.setattr(sec_edgar, "_MANIFEST_CACHE", {})
    sec_edgar.drain_mirror_serves()

    class _Resp:
        status_code = 200
        headers = {}
        def raise_for_status(self): pass
        def json(self): return {"tickers": {}}

    class _NoDate:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, headers=None):
            return _Resp()

    monkeypatch.setattr(sec_edgar.httpx, "AsyncClient", _NoDate)
    try:
        asyncio.run(sec_edgar.mirror_get_json(
            "https://data.sec.gov/submissions/CIK0000000001.json"))
        raise AssertionError("debio fallar cerrado")
    except RuntimeError as e:
        assert "synced_at" in str(e)
    get_settings.cache_clear()


# --- Integridad del mirror: path declarado + sha1 verificado ---

def _manifest_fresco(files):
    from datetime import UTC, datetime
    return {
        "tickers": {},
        "synced_at": datetime.now(UTC).isoformat(),
        "files": files,
    }


def _resp(data, content=None):
    class _Resp:
        def __init__(self):
            self._data = data
            self.status_code = 200
            self.headers = {}
            self.content = content if content is not None else json.dumps(data).encode()
        def raise_for_status(self): pass
        def json(self): return self._data
    return _Resp()


def _mirror_http(monkeypatch, sec_edgar, manifest, documento, doc_bytes):
    class _HTTP:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, headers=None):
            if url.endswith("/manifest.json"):
                return _resp(manifest)
            if url.endswith(f"/{documento}"):
                return _resp({}, content=doc_bytes)
            raise AssertionError(f"URL inesperada: {url}")
    monkeypatch.setattr(sec_edgar.httpx, "AsyncClient", _HTTP)


def test_mirror_sha1_no_casa_fail_closed(monkeypatch):
    """Sync parcial que deja mezcla de versiones: el manifest (fresco) declara
    un sha1 y el archivo remoto tiene otro contenido. Fail closed: la mezcla
    nuevo/viejo NUNCA se sirve."""
    from app.core.config import get_settings
    from app.services.connectors import sec_edgar

    get_settings.cache_clear()
    monkeypatch.setenv("SEC_HF_MIRROR_DATASET", "owner/cavaai-sec-mirror")
    get_settings.cache_clear()
    monkeypatch.setattr(sec_edgar, "_MANIFEST_CACHE", {})
    sec_edgar.drain_mirror_serves()

    doc = "submissions/CIK0000000001.json"
    viejo = json.dumps({"filings": {"recent": {"old": True}}}).encode()
    manifest = _manifest_fresco({doc: hashlib.sha1(b"contenido nuevo").hexdigest()})  # nosemgrep: python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1 -- fixture: replica el contrato de proveniencia sha1 del mirror HF (no criptografia; decision mia/main en scripts/sec_hf_mirror_sync.py)
    _mirror_http(monkeypatch, sec_edgar, manifest, doc, viejo)

    try:
        asyncio.run(sec_edgar.mirror_get_json(
            "https://data.sec.gov/submissions/CIK0000000001.json"))
        raise AssertionError("debio fallar cerrado")
    except RuntimeError as e:
        assert "sha1" in str(e)
    get_settings.cache_clear()


def test_mirror_path_no_listado_fail_closed(monkeypatch):
    """Archivo huerfano (existe en el dataset pero no declarado en el manifest
    nuevo, p.ej. un ticker omitido): NO se sirve aunque el manifest sea fresco."""
    from app.core.config import get_settings
    from app.services.connectors import sec_edgar

    get_settings.cache_clear()
    monkeypatch.setenv("SEC_HF_MIRROR_DATASET", "owner/cavaai-sec-mirror")
    get_settings.cache_clear()
    monkeypatch.setattr(sec_edgar, "_MANIFEST_CACHE", {})
    sec_edgar.drain_mirror_serves()

    doc = "submissions/CIK0000000001.json"
    contenido = json.dumps({"filings": {"recent": {}}}).encode()
    # El manifest lista OTROS archivos, no el pedido.
    manifest = _manifest_fresco({"companyfacts/CIK0000000099.json": "abc123"})
    _mirror_http(monkeypatch, sec_edgar, manifest, doc, contenido)

    try:
        asyncio.run(sec_edgar.mirror_get_json(
            "https://data.sec.gov/submissions/CIK0000000001.json"))
        raise AssertionError("debio fallar cerrado")
    except RuntimeError as e:
        assert "no esta declarado" in str(e)
    get_settings.cache_clear()


def test_mirror_sirve_solo_si_hash_casa(monkeypatch):
    """Camino feliz de integridad: path declarado + sha1 coincidente -> se
    sirve, y la telemetria queda registrada en la corrida."""
    from app.core.config import get_settings
    from app.services.connectors import sec_edgar

    get_settings.cache_clear()
    monkeypatch.setenv("SEC_HF_MIRROR_DATASET", "owner/cavaai-sec-mirror")
    get_settings.cache_clear()
    monkeypatch.setattr(sec_edgar, "_MANIFEST_CACHE", {})
    sec_edgar.drain_mirror_serves()

    doc = "submissions/CIK0000000001.json"
    payload = {"filings": {"recent": {"x": 1}}}
    contenido = json.dumps(payload).encode()
    manifest = _manifest_fresco({doc: hashlib.sha1(contenido).hexdigest()})  # nosemgrep: python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1 -- fixture: replica el contrato de proveniencia sha1 del mirror HF (no criptografia; decision mia/main en scripts/sec_hf_mirror_sync.py)
    _mirror_http(monkeypatch, sec_edgar, manifest, doc, contenido)

    data = asyncio.run(sec_edgar.mirror_get_json(
        "https://data.sec.gov/submissions/CIK0000000001.json"))
    assert data == payload
    serves = sec_edgar.drain_mirror_serves()
    assert len(serves) == 1
    assert serves[0]["url"].endswith(doc)
    assert serves[0]["synced_at"] == manifest["synced_at"]
    get_settings.cache_clear()


# --- Regresion de procedencia: la clave mirror no sobrevive a una corrida directa ---

def test_mirror_metadata_no_sobrevive_a_corrida_directa(monkeypatch):
    """Secuencia en el mismo documento: corrida 1 con SEC bloqueada (403 ->
    mirror HF, metadata declara mirror), corrida 2 con SEC directo OK ->
    metadata_['mirror'] y resultado['mirror'] quedan en None (la API nunca
    atribuye al mirror una ingesta directa)."""
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from app.core.config import get_settings
    from app.models.entities import Base, Company, Document
    from app.services import financial_ingestion_service as ingestion
    from app.services.connectors import sec_edgar
    from app.services.connectors.sec import SECClient
    from app.services.financial_ingestion_service import FinancialIngestionService

    get_settings.cache_clear()
    monkeypatch.setenv("SEC_HF_MIRROR_DATASET", "owner/cavaai-sec-mirror")
    monkeypatch.delenv("SEC_SNAPSHOT_DIR", raising=False)
    get_settings.cache_clear()
    monkeypatch.setattr(sec_edgar, "_MANIFEST_CACHE", {})

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    db = factory()
    db.info["tenant_id"] = "tenant-test"
    company = Company(
        ticker="ACME", name="ACME", exchange="NASDAQ", currency="USD",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=[])
    db.add(company)
    db.commit()

    tickers_payload = {"0": {"cik_str": 1, "ticker": "ACME", "title": "ACME Corp"}}
    facts_payload = {"cik": 1, "facts": {"us-gaap": {}}}
    subs_payload = {"filings": {"recent": {}}}
    bodies = {
        "company_tickers.json": json.dumps(tickers_payload).encode(),
        "companyfacts/CIK0000000001.json": json.dumps(facts_payload).encode(),
        "submissions/CIK0000000001.json": json.dumps(subs_payload).encode(),
    }
    files = {p: hashlib.sha1(c).hexdigest() for p, c in bodies.items()}  # nosemgrep: python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1 -- fixture: replica el contrato de proveniencia sha1 del mirror HF (no criptografia; decision mia/main en scripts/sec_hf_mirror_sync.py)

    class _Resp:
        def __init__(self, data, content):
            self._data = data
            self.status_code = 200
            self.headers = {}
            self.content = content
        def raise_for_status(self): pass
        def json(self): return self._data

    class _MirrorHTTP:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, headers=None):
            if url.endswith("/manifest.json"):
                from datetime import UTC, datetime
                return _Resp(
                    {"tickers": {}, "synced_at": datetime.now(UTC).isoformat(),
                     "files": files}, b"{}")
            for path, content in bodies.items():
                if url.endswith(f"/{path}"):
                    return _Resp(json.loads(content), content)
            raise AssertionError(f"URL inesperada: {url}")

    monkeypatch.setattr(sec_edgar.httpx, "AsyncClient", _MirrorHTTP)

    client = SECClient()
    import httpx as _httpx

    async def _get_403(url):
        req = _httpx.Request("GET", url)
        _httpx.Response(403, request=req).raise_for_status()
    client._get = _get_403
    monkeypatch.setattr(ingestion, "SECClient", lambda *a, **k: client)

    service = FinancialIngestionService()
    res1 = asyncio.run(service.refresh_from_sec(db=db, company=company))
    assert res1["mirror"] is not None
    assert res1["mirror"]["documents"] == 3  # tickers + facts + submissions
    doc = db.scalar(select(Document).where(
        Document.company_id == company.id, Document.source_type == "SEC"))
    assert doc.metadata_["mirror"]["documents"] == 3
    assert doc.metadata_["mirror"]["synced_at"]

    # Corrida 2: SEC directo vuelve (200). El mirror no se consulta.
    class _DirectResp:
        def __init__(self, data): self._d = data
        def json(self): return self._d

    async def _get_200(url):
        if "company_tickers" in url:
            return _DirectResp(tickers_payload)
        if "companyfacts" in url:
            return _DirectResp(facts_payload)
        if "submissions" in url:
            return _DirectResp(subs_payload)
        raise AssertionError(f"URL inesperada: {url}")
    client._get = _get_200
    res2 = asyncio.run(service.refresh_from_sec(db=db, company=company))
    assert res2["mirror"] is None
    db.expire_all()
    doc = db.scalar(select(Document).where(
        Document.company_id == company.id, Document.source_type == "SEC"))
    assert doc.metadata_["mirror"] is None
    get_settings.cache_clear()
