"""C4: ejecucion de la ingesta REAL del repo contra el corpus sintetico.

Cada caso del dataset dice QUE ejecutar (escenario + fixtures) y el harness lo
ejecuta contra el codigo de produccion, sin red:

- SEC/EDGAR: `FinancialIngestionService.refresh_from_sec` con `SECClient` real
  (__init__.py de app/services/connectors/sec.py) montado sobre
  `httpx.MockTransport`; los payloads salen de `tests/fixtures/ingest_eval/`.
- Instancias XBRL por clases: `class_filer_eps_service.backfill_class_based_eps`
  con los recuperadores de submissions/indice/instancia inyectados.
- FMP: `FinancialIngestionService.refresh_from_fmp` con `FMPClient` real; solo se
  sustituye la construccion del `httpx.AsyncClient` (el repo ya lo hace asi en
  tests/test_fmp_stable_client.py) para que apunte al MockTransport.
- ESEF: `connectors.esef.normalize_xbrl_json` real sobre el render xBRL-JSON del
  fixture, snapshot local en disco y `refresh_from_esef` real.
- Procedencia: `ingest_filings` (scripts/ingest_sec_filings.py) con
  `sec_filing_evidence.verify_entry` real para la regla de oro del repo (un
  filing solo es `primary_official` si su indice lo verifica) y
  `thesis_provenance.classify_origin` real para decidir OFICIAL / INFERIDO.

Cero red: `no_network()` bloquea `socket.socket.connect`, `socket.create_connection`
y `socket.getaddrinfo` para todo lo que no sea loopback. Ningun LLM: el clasificador
de anomalias se sustituye por `None` (repo: nada de LLM juzgando a LLM).

El harness no calcula ningun valor esperado: solo ejecuta y describe lo que la
ingesta persistio. Los esperables viven en `evals/ingest/ingest_v1.json`.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
import socket
import tempfile
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "ingest_eval"

FAMILIES = ("sec", "fmp", "esef")
PROBE_PERIOD = "<ingestion-date>"

_LOOPBACK = {"127.0.0.1", "::1", "localhost", "0.0.0.0", ""}


class OfflineViolation(RuntimeError):
    """El eval intentó salir a la red: eso es un fallo del runner, no del pipeline."""


class NetworkBlocked(OfflineViolation):
    pass


# --------------------------------------------------------------------------
# Guardian de red
# --------------------------------------------------------------------------


@contextmanager
def no_network():
    """Bloquea toda salida a la red que no sea loopback durante el bloque."""

    real_connect = socket.socket.connect
    real_create = socket.create_connection
    real_getaddrinfo = socket.getaddrinfo

    def _host(address) -> str:
        if isinstance(address, tuple) and address:
            return str(address[0])
        return str(address)

    def _guard(original, what):
        def wrapper(self_or_address, *args, **kwargs):
            target = args[0] if args else self_or_address
            host = _host(target)
            if host not in _LOOPBACK:
                raise NetworkBlocked(f"{what} bloqueado: el eval de ingesta es offline ({host})")
            return original(self_or_address, *args, **kwargs)

        return wrapper

    socket.socket.connect = _guard(real_connect, "socket.connect")
    socket.create_connection = _guard(real_create, "create_connection")
    socket.getaddrinfo = _guard(real_getaddrinfo, "getaddrinfo")
    try:
        yield
    finally:
        socket.socket.connect = real_connect
        socket.create_connection = real_create
        socket.getaddrinfo = real_getaddrinfo


# --------------------------------------------------------------------------
# Utilidades de fixture
# --------------------------------------------------------------------------


def fixture_path(relative: str) -> Path:
    path = FIXTURES / relative
    if not path.exists():
        raise FileNotFoundError(f"fixture de ingesta inexistente: {relative}")
    return path


def load_fixture(relative: str) -> Any:
    return json.loads(fixture_path(relative).read_text(encoding="utf-8"))


def declared_fixtures(case: dict) -> list[str]:
    """Rutas de fixture que el caso declara, en las rutas que puede usar el harness."""
    found: list[str] = []
    args = case.get("scenario_args") or {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str) and "/" in node and not node.startswith("http"):
            found.append(node)

    walk(args)
    return found


# --------------------------------------------------------------------------
# Base de datos en memoria
# --------------------------------------------------------------------------


@contextmanager
def session_scope():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.models.entities import Base, Tenant

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as db:
        tenant = Tenant(external_id="c4-ingest-eval", name="C4 ingest eval")
        db.add(tenant)
        db.commit()
        db.info["tenant_id"] = tenant.id
        yield db
    engine.dispose()


def make_company(db, ticker: str, *, industry: str = "Software", cik: str | None = "0000000001"):
    from app.models.entities import Company

    company = Company(
        ticker=ticker,
        name=f"{ticker} Synthetic Holdings PLC",
        exchange="NASDAQ",
        currency="USD",
        sector="Technology",
        industry=industry,
        cik=cik,
        company_type="standard",
        valuation_model="standard_dcf",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


# --------------------------------------------------------------------------
# Descripcion de la observacion
# --------------------------------------------------------------------------


def _fact_rows(db, company_id: int) -> list[dict]:
    from sqlalchemy import select

    from app.models.entities import FinancialFact

    rows = db.scalars(
        select(FinancialFact)
        .where(FinancialFact.company_id == company_id)
        .order_by(FinancialFact.id)
    ).all()
    out = []
    for row in rows:
        period = row.period
        if row.source_type == "FMP_profile":
            period = PROBE_PERIOD
        out.append(
            {
                "id": row.id,
                "metric": row.metric,
                "period": period,
                "raw_period": row.period,
                "value": float(row.value) if row.value is not None else None,
                "unit": row.unit,
                "fiscal_year": row.fiscal_year,
                "fiscal_quarter": row.fiscal_quarter,
                "source_type": row.source_type,
                "source_id": row.source_id,
                "is_reported": bool(row.is_reported),
                "accession": row.accession_number,
            }
        )
    return out


def _statement_rows(db, company_id: int) -> list[dict]:
    from sqlalchemy import select

    from app.models.entities import FinancialStatement

    rows = db.scalars(
        select(FinancialStatement)
        .where(FinancialStatement.company_id == company_id)
        .order_by(FinancialStatement.id)
    ).all()
    return [
        {
            "statement_type": row.statement_type,
            "period": row.period,
            "fiscal_year": row.fiscal_year,
            "fiscal_quarter": row.fiscal_quarter,
        }
        for row in rows
    ]


def _document_rows(db, company_id: int) -> list[dict]:
    from sqlalchemy import select

    from app.models.entities import Document

    rows = db.scalars(
        select(Document).where(Document.company_id == company_id).order_by(Document.id)
    ).all()
    out = []
    for row in rows:
        metadata = row.metadata_ or {}
        out.append(
            {
                "id": row.id,
                "title": row.title,
                "source_type": row.source_type,
                "source_url": row.source_url,
                "published_at": row.published_at.isoformat() if row.published_at else None,
                "date_source": metadata.get("date_source"),
                "accession": metadata.get("accession"),
                "origin_verification": metadata.get("origin_verification"),
            }
        )
    return out


def _market_rows(db, company_id: int) -> list[dict]:
    from sqlalchemy import select

    from app.models.entities import MarketPrice

    rows = db.scalars(
        select(MarketPrice).where(MarketPrice.company_id == company_id).order_by(MarketPrice.date)
    ).all()
    return [
        {
            "date": row.date.isoformat(),
            "close": float(row.close) if row.close is not None else None,
            "adj_close": float(row.adj_close) if row.adj_close is not None else None,
            "volume": row.volume,
            "source": row.source,
        }
        for row in rows
    ]


def _provenance(db, facts: list[dict]) -> dict[str, dict]:
    """Origen OFICIAL/INFERIDO de cada hecho con el clasificador real del repo.

    `classify_origin` exige que el input sea EL PROPIO hecho (misma metrica,
    valor, unidad y periodo) y que la fuente sea verificable; por eso el mapa
    `sources` lleva tanto el documento resuelto desde `FinancialFact.source_id`
    como los campos del hecho, igual que hace el motor real.
    """
    from app.models.entities import Document
    from app.services.thesis_provenance import DIRECT_READING_SOURCE_TYPE, classify_origin

    sources: dict[int, dict] = {}
    for fact in facts:
        document = db.get(Document, fact["source_id"]) if fact["source_id"] else None
        metadata = getattr(document, "metadata_", None) or {}
        sources[fact["id"]] = {
            "url": getattr(document, "source_url", None),
            "date": (
                document.published_at.date().isoformat()
                if getattr(document, "published_at", None)
                else None
            ),
            "title": getattr(document, "title", None),
            "source_type": getattr(document, "source_type", None),
            # La ingesta persiste el accn por hecho (filing anclado); el
            # metadata del Document queda como respaldo para hechos sonda.
            "accession": fact.get("accession") or metadata.get("accession"),
            "metric": fact["metric"],
            "fact_value": fact["value"],
            "unit": fact["unit"],
            "period": fact["raw_period"],
            "is_reported": fact["is_reported"],
        }
    items = [
        {
            "key": fact["metric"],
            "label": fact["metric"],
            "value": fact["value"],
            "unit": fact["unit"],
            "method": f"{fact['metric']} reportado (periodo {fact['raw_period']})",
            "source_fact_ids": [fact["id"]],
            "confidence": 0.9,
            "source_type": DIRECT_READING_SOURCE_TYPE,
            "period": fact["raw_period"],
        }
        for fact in facts
    ]
    out: dict[str, dict] = {}
    for fact, classified in zip(facts, classify_origin(items, sources), strict=True):
        out[f"{fact['metric']}@{fact['raw_period']}"] = {
            "origin": classified["origen"],
            "url": classified["fuentes"][0]["url"] if classified["fuentes"] else None,
            "date": classified["fuentes"][0]["fecha"] if classified["fuentes"] else None,
            "inference_base": classified["base_inferencia"],
            "documented_base": bool(classified.get("base_documentada")),
            "accession": sources[fact["id"]]["accession"],
            "document_source_type": sources[fact["id"]]["source_type"],
        }
    return out


def _observe(db, company, *, extra: dict | None = None) -> dict:
    facts = _fact_rows(db, company.id)
    observation = {
        "status": "ok",
        "facts": facts,
        "statements": _statement_rows(db, company.id),
        "documents": _document_rows(db, company.id),
        "market_prices": _market_rows(db, company.id),
        "provenance": _provenance(db, facts),
        "index_verification": {},
        "requests": [],
        "errors": [],
        "notes": [],
    }
    if extra:
        observation.update(extra)
    return observation


# --------------------------------------------------------------------------
# Escenario: SEC companyfacts / submissions
# --------------------------------------------------------------------------


class _OfflineSEC:
    """SECClient real sobre MockTransport, sin el throttle de peticiones."""

    def __new__(cls, handler, *, user_agent="CavaAI ingest eval contact@example.com"):
        from app.services.connectors.sec import SECClient

        class _Client(SECClient):
            def __init__(self):
                import httpx

                super().__init__(
                    client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
                    user_agent=user_agent,
                    requests_per_second=10,
                    # El contrato del eval es 1 peticion por URL con el fixture
                    # del caso: ni cache entre casos ni reintentos con backoff.
                    use_cache=False,
                    max_retries=0,
                )

            async def _throttle(self):
                return None

        return _Client()


def run_sec_companyfacts(case: dict) -> dict:
    import httpx

    from app.services import financial_ingestion_service as ingestion
    from app.services.financial_ingestion_service import FinancialIngestionService

    args = case.get("scenario_args") or {}
    companyfacts = load_fixture(args["companyfacts"])
    submissions = load_fixture(args["submissions"])
    statuses = {key: int(value) for key, value in (args.get("http_status") or {}).items()}
    ticker = args.get("ticker", "SYNQ")
    industry = args.get("industry", "Software")
    # Mapa ticker->CIK que sirve la SEC. Por defecto, uno sintetico que casa
    # con el ticker pedido; un caso puede declarar el mapa real de la SEC,
    # donde el mismo ticker tiene DOS emisores (tickers reutilizados tras un
    # delisting) y `cik_for_ticker` resuelve el primero (FIX5-6).
    ticker_map = args.get("ticker_map") or {
        "1": {"cik_str": 1, "ticker": ticker, "title": "Synthetic Holdings PLC"}
    }
    # Corte de informacion de la corrida (FIX5-1): lo que la ingesta puede
    # saber en esa fecha. Sin declararlo, la ingesta no filtra por fecha y lo
    # declara en su resultado.
    as_of_arg = args.get("as_of")
    as_of = date.fromisoformat(str(as_of_arg)[:10]) if as_of_arg else None
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        requests.append(url)
        if "company_tickers.json" in url:
            return httpx.Response(200, json=ticker_map)
        if "companyfacts" in url:
            status = statuses.get("companyfacts", 200)
            if status != 200:
                return httpx.Response(status, text="upstream unavailable")
            return httpx.Response(200, json=companyfacts)
        if "submissions" in url:
            status = statuses.get("submissions", 200)
            if status != 200:
                return httpx.Response(status, text="upstream unavailable")
            return httpx.Response(200, json=submissions)
        return httpx.Response(404, text=f"ruta no servida: {url}")

    original_client = ingestion.SECClient
    ingestion.SECClient = lambda *a, **k: _OfflineSEC(handler)
    observation: dict
    try:
        with session_scope() as db:
            company = make_company(db, ticker, industry=industry, cik=args.get("cik"))
            errors: list[str] = []
            try:
                result = asyncio.run(
                    FinancialIngestionService().refresh_from_sec(
                        db=db, company=company, as_of=as_of
                    )
                )
            except Exception as exc:  # degradacion honesta: no hay hechos, no hay invented
                errors.append(f"{type(exc).__name__}: {exc}")
                observation = _observe(db, company)
                observation["status"] = "unavailable"
                observation["errors"] = errors
                observation["requests"] = requests
                observation["notes"].append("proveedor SEC caido: la ingesta no publica hechos")
                return observation
            observation = _observe(db, company)
            observation["result"] = {
                key: value for key, value in result.items() if key != "free_data"
            }
            observation["free_data"] = result.get("free_data") or {}
    finally:
        ingestion.SECClient = original_client
    observation["requests"] = requests
    # Verificacion de indice fiel: el fixture submissions ES el indice que la
    # ingesta tuvo a la vista. Cada accession citado por un hecho OFICIAL se
    # evalua contra ese indice (listado o ancla anual); lo no listado queda
    # registrado como NO verificado, nunca se supone.
    index_accns, anchor_accns = _submissions_index(submissions)
    cited = sorted(
        {
            prov.get("accession")
            for prov in observation["provenance"].values()
            if prov.get("origin") == "OFICIAL" and prov.get("accession")
        }
    )
    observation["index_verification"] = {
        accn: (
            {
                "verified": True,
                "status": (
                    "annual_anchor" if accn in anchor_accns else "listed_in_submissions"
                ),
                "reason": None,
            }
            if accn in index_accns
            else {
                "verified": False,
                "status": "not_in_index",
                "reason": "el accession no aparece en el indice submissions servido",
            }
        )
        for accn in cited
    }
    return observation


def _submissions_index(submissions: dict) -> tuple[set[str], set[str]]:
    """(accessions listados, anclas anuales) del indice submissions servido."""
    from app.services.connectors.sec import ANNUAL_REPORT_FORMS

    filings = submissions.get("filings", {}) or {}
    index_accns: set[str] = set()
    anchor_accns: set[str] = set()

    def _absorb(recent: dict) -> None:
        forms = recent.get("form", []) or []
        for pos, accession in enumerate(recent.get("accessionNumber", []) or []):
            if not accession:
                continue
            index_accns.add(str(accession))
            form = str(forms[pos]) if pos < len(forms) else ""
            if form in ANNUAL_REPORT_FORMS:
                anchor_accns.add(str(accession))

    _absorb(filings.get("recent", {}) or {})
    for extra in filings.get("files", []) or []:
        if isinstance(extra, dict):
            accession = extra.get("accessionNumber")
            if accession:
                index_accns.add(str(accession))
    return index_accns, anchor_accns


# --------------------------------------------------------------------------
# Escenario: instancia XBRL por clases
# --------------------------------------------------------------------------


def _ingest_sec_filings_module():
    spec = importlib.util.spec_from_file_location(
        "c4_ingest_sec_filings", ROOT / "scripts" / "ingest_sec_filings.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_sec_instance(case: dict) -> dict:
    from app.services.class_filer_eps_service import backfill_class_based_eps

    args = case.get("scenario_args") or {}
    instance_bytes = fixture_path(args["instance"]).read_bytes()
    instance_name = args["instance_name"]
    submissions = load_fixture(args["submissions"])
    requests: list[str] = []

    def fetch_json(url: str) -> dict:
        requests.append(url)
        if "/submissions/" in url:
            return submissions
        return {"directory": {"item": [{"name": instance_name}]}}

    def fetch_bytes(url: str) -> bytes:
        requests.append(url)
        return instance_bytes

    with session_scope() as db:
        company = make_company(db, args.get("ticker", "V"), cik="0000000001")
        result = backfill_class_based_eps(
            db, company, cik="0000000001", fetch_json=fetch_json, fetch_bytes=fetch_bytes
        )
        observation = _observe(db, company)
        observation["requests"] = requests
        # La instancia XBRL del 10-K no es el filing verificado contra su indice:
        # se registra como NO verificada para que la puerta de procedencia no la
        # pueda dar por OFICIAL por el hecho de salir del mismo accession.
        observation["index_verification"] = {
            args["accession"]: {
                "verified": False,
                "status": "xbrl_instance",
                "reason": "una instancia XBRL no es el documento listado en el indice",
            }
        }
        observation["result"] = {
            "facts_written": result.facts_written,
            "member_used": result.member_used,
            "periods": list(result.periods),
            "skipped_reason": result.skipped_reason,
        }
        observation["status"] = "ok" if result.facts_written else "degraded"
    return observation


# --------------------------------------------------------------------------
# Escenario: verificacion contra el indice SEC (regla de oro)
# --------------------------------------------------------------------------


def run_sec_index(case: dict) -> dict:
    from app.services.document_store import DocumentStore

    args = case.get("scenario_args") or {}
    bundle = load_fixture(args["bundle"])
    ingest = _ingest_sec_filings_module()
    original_put = DocumentStore.put_bytes
    DocumentStore.put_bytes = lambda self, *a, **k: "memory://c4-ingest-eval"
    requests: list[str] = []
    try:
        with tempfile.TemporaryDirectory(prefix="c4-sec-index-") as tmp:
            base = Path(tmp)
            index_html = bundle["index_html"]
            document = bundle["document"]
            submissions = bundle["submissions_capture"]
            document_body = document.encode("utf-8")
            (base / "doc.htm").write_bytes(document_body)
            (base / "submissions.json").write_text(submissions, encoding="utf-8", newline="")
            index_bytes = index_html.encode("utf-8")
            if bundle.get("missing_index"):
                # El operador no trajo el indice: el documento no puede acreditarse.
                index_bytes = b""
            (base / "index.htm").write_bytes(index_bytes)
            entry = {
                "file": "doc.htm",
                "index_file": "index.htm",
                "url": bundle["document_url"],
                "index_url": f"https://www.sec.gov/Archives/edgar/data/"
                f"{int(bundle['company']['cik'])}/{bundle['accession'].replace('-', '')}/"
                f"{bundle['accession']}-index.htm",
                "index_sha256": bundle["index_sha256"],
                "sha256": bundle["document_sha256"],
                "capture": {
                    **bundle["capture"],
                    "submissions_file": "submissions.json",
                    "submissions_sha256": hashlib.sha256(
                        submissions.encode("utf-8")
                    ).hexdigest(),
                },
            }
            with session_scope() as db:
                company = make_company(
                    db,
                    bundle["company"]["ticker"],
                    cik=str(int(bundle["company"]["cik"])),
                )
                results = ingest.ingest_filings(db, company, [entry], base, dry_run=False)
                observation = _observe(db, company)
                observation["requests"] = requests
                observation["ingest_results"] = results
                observation["index_verification"] = {
                    bundle["accession"]: {
                        "verified": results[0]["status"] in {"ingested", "duplicate"},
                        "status": results[0]["status"],
                        "reason": results[0].get("reason"),
                    }
                }
                if args.get("probe_fact") and results[0]["status"] == "ingested":
                    # Hecho sonda: no lo escribe la ingesta de fundamentales (esa
                    # crea su propio Document), lo escribe el eval para que la regla
                    # de procedencia tenga algo que clasificar. Lo declara.
                    from app.models.entities import FinancialFact

                    probe = FinancialFact(
                        company_id=company.id,
                        metric=args.get("probe_metric", "revenue"),
                        value=Decimal(args.get("probe_value", "5000000")),
                        unit="USD",
                        period="2025-12-31:FY",
                        fiscal_year=2025,
                        fiscal_quarter="FY",
                        source_id=results[0]["document_id"],
                        source_type="primary_official",
                        is_reported=True,
                        confidence=Decimal("0.95"),
                    )
                    db.add(probe)
                    db.commit()
                    observation = _observe(db, company)
                    observation["ingest_results"] = results
                    observation["index_verification"] = {
                        bundle["accession"]: {
                            "verified": True,
                            "status": results[0]["status"],
                            "reason": results[0].get("reason"),
                        }
                    }
                    observation["notes"].append(
                    "el hecho sonda lo escribe el eval para pasar por classify_origin; "
                    "el documento oficial si lo verifica verify_entry"
                )
    finally:
        DocumentStore.put_bytes = original_put
    return observation


# --------------------------------------------------------------------------
# Escenario: FMP
# --------------------------------------------------------------------------


def run_fmp_statements(case: dict) -> dict:
    import httpx

    from app.services.connectors import fmp as fmp_module
    from app.services.financial_ingestion_service import FinancialIngestionService

    args = case.get("scenario_args") or {}
    routes = dict(args.get("endpoints") or {})
    statuses = {key: int(value) for key, value in (args.get("http_status") or {}).items()}
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = request.url
        endpoint = url.path.rsplit("/", 1)[-1]
        requests.append({"path": url.path, "params": dict(url.params)})
        status = statuses.get(endpoint, 200)
        if status != 200:
            return httpx.Response(status, text="upstream error")
        relative = routes.get(endpoint)
        if relative is None:
            return httpx.Response(200, json=[])
        payload = load_fixture(relative)
        rows = payload.get("rows", payload) if isinstance(payload, dict) else payload
        return httpx.Response(200, json=rows)

    real_client_cls = httpx.AsyncClient

    class _MockedClient(real_client_cls):
        def __init__(self, *args, **kwargs):
            kwargs.pop("transport", None)
            kwargs.pop("headers", None)
            super().__init__(*args, transport=httpx.MockTransport(handler), **kwargs)

    original_client = fmp_module.httpx.AsyncClient
    original_key = os.environ.get("FMP_API_KEY")
    fmp_module.httpx.AsyncClient = _MockedClient
    os.environ["FMP_API_KEY"] = args.get("api_key", "c4-ingest-eval-key")
    from app.core.config import get_settings

    get_settings.cache_clear()
    observation: dict
    try:
        with session_scope() as db:
            company = make_company(db, args.get("ticker", "SYNQ"), industry=args.get("industry", "Software"))
            errors: list[str] = []
            try:
                result = asyncio.run(
                    FinancialIngestionService().refresh_from_fmp(
                        db=db, company=company, limit=args.get("limit", 5)
                    )
                )
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {exc}")
                observation = _observe(db, company)
                observation["status"] = "unavailable"
                observation["errors"] = errors
                observation["requests"] = requests
                observation["notes"].append(
                    "proveedor FMP caido o sin entitlement: cobertura no disponible"
                )
                return observation
            observation = _observe(db, company)
            observation["result"] = {
                key: value
                for key, value in result.items()
                if key not in {"latest_periods", "valuation_input_ready"}
            }
            observation["latest_periods"] = result.get("latest_periods")
    finally:
        fmp_module.httpx.AsyncClient = original_client
        if original_key is None:
            os.environ.pop("FMP_API_KEY", None)
        else:
            os.environ["FMP_API_KEY"] = original_key
        get_settings.cache_clear()
    observation["requests"] = requests
    return observation


# --------------------------------------------------------------------------
# Escenario: ESEF
# --------------------------------------------------------------------------


def run_esef_snapshot(case: dict) -> dict:
    from app.core.config import get_settings
    from app.services.connectors import esef as esef_connector
    from app.services.financial_ingestion_service import FinancialIngestionService

    args = case.get("scenario_args") or {}
    relative = args["xbrl"]
    ticker = args.get("ticker", "SYNQ")
    lei = args.get("lei", "9598SYNTHETIC0000001")
    normalize = args.get("normalize", True)
    document = load_fixture(relative)
    errors: list[str] = []
    notes: list[str] = []
    snapshot: dict | None = None
    if normalize:
        try:
            facts = esef_connector.normalize_xbrl_json(document)
        except esef_connector.EsefError as exc:
            errors.append(f"EsefError: {exc}")
            notes.append("el render no trae bloque facts: degrada a sin datos, nunca a OFICIAL")
            facts = {}
        snapshot = {
            "lei": lei,
            "ticker": ticker,
            "entity_name": "Synthetic Holdings PLC",
            "period_end": args.get("period_end", "2025-12-31"),
            "fxo_id": f"{lei}-{args.get('period_end', '2025-12-31')}",
            "fetched_at": args.get("fetched_at", "2026-01-05"),
            "facts": facts,
        }
    original_dir = os.environ.get("ESEF_SNAPSHOT_DIR")
    original_reader = esef_connector.read_esef_snapshot
    esef_connector.read_esef_snapshot = lambda t: snapshot if t.upper() == ticker.upper() else None
    get_settings.cache_clear()
    observation: dict
    try:
        with session_scope() as db:
            company = make_company(db, ticker, industry="Construction")
            try:
                result = asyncio.run(
                    FinancialIngestionService().refresh_from_esef(db=db, company=company)
                )
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {exc}")
                notes.append("sin snapshot utilizable: la ingesta ESEF no publica hechos")
                observation = _observe(db, company)
                observation["status"] = "unavailable"
                observation["errors"] = errors
                observation["notes"] += notes
                return observation
            observation = _observe(db, company)
            observation["result"] = {
                key: value
                for key, value in result.items()
                if key not in {"latest_periods", "valuation_input_ready"}
            }
    finally:
        esef_connector.read_esef_snapshot = original_reader
        if original_dir is None:
            os.environ.pop("ESEF_SNAPSHOT_DIR", None)
        else:
            os.environ["ESEF_SNAPSHOT_DIR"] = original_dir
        get_settings.cache_clear()
    observation["errors"] = errors
    observation["notes"] += notes
    return observation


def run_esef_client(case: dict) -> dict:
    """El contrato del conector ESEF contra filings.xbrl.org, con MockTransport."""
    import httpx

    from app.services.connectors.esef import EsefClient, EsefError

    args = case.get("scenario_args") or {}
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        requests.append(url)
        path = url.split("xbrl.org", 1)[-1]
        if path.startswith("/api/filings"):
            return httpx.Response(200, json=load_fixture(args["filings_page"]))
        if path.startswith("/api/entities/"):
            return httpx.Response(200, json=load_fixture(args["entity"]))
        if args.get("http_status"):
            return httpx.Response(int(args["http_status"]), text="upstream error")
        if "/xbrl-json/" in path:
            return httpx.Response(200, json=load_fixture(args["xbrl"]))
        return httpx.Response(404, text=f"ruta no servida: {path}")

    client = EsefClient(
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="https://filings.xbrl.org"
        )
    )
    observation: dict = {
        "status": "ok",
        "facts": [],
        "statements": [],
        "documents": [],
        "market_prices": [],
        "provenance": {},
        "index_verification": {},
        "requests": requests,
        "errors": [],
        "notes": [],
    }
    try:
        filings, total = asyncio.run(client.list_filings_page("ES", page=1, page_size=10))
    except EsefError as exc:
        observation["status"] = "unavailable"
        observation["errors"] = [f"EsefError: {exc}"]
        return observation
    observation["filings"] = [
        {
            "fxo_id": filing.fxo_id,
            "lei": filing.lei,
            "period_end": filing.period_end,
            "json_url": filing.json_url,
            "package_url": filing.package_url,
        }
        for filing in filings
    ]
    observation["total_filings"] = total
    target = next(
        (f for f in filings if f.fxo_id == args.get("target_fxo_id")),
        next((f for f in filings if f.json_url), None),
    )
    if target is None:
        observation["status"] = "degraded"
        observation["notes"].append("sin render xBRL-JSON: no se parsea iXBRL, se declara ausente")
        return observation
    observation["target_fxo_id"] = target.fxo_id
    try:
        document = asyncio.run(client.fetch_filing_json(target))
    except EsefError as exc:
        observation["status"] = "degraded"
        observation["errors"] = [f"EsefError: {exc}"]
        observation["notes"].append("el informe no trae render: se declara no disponible")
        return observation
    from app.services.connectors.esef import normalize_xbrl_json

    try:
        facts = normalize_xbrl_json(document)
    except EsefError as exc:
        observation["status"] = "degraded"
        observation["errors"] = [f"EsefError: {exc}"]
        observation["notes"].append("informe sin etiquetar: nunca se presenta como OFICIAL")
        return observation
    observation["facts"] = [
        {"concept": concept, "unit": unit, "entries": len(entries)}
        for concept, units in sorted(facts.items())
        for unit, entries in sorted(units.items())
    ]
    return observation


# --------------------------------------------------------------------------
# Despacho
# --------------------------------------------------------------------------


SCENARIOS = {
    "sec_companyfacts": run_sec_companyfacts,
    "sec_instance": run_sec_instance,
    "sec_index": run_sec_index,
    "fmp_statements": run_fmp_statements,
    "esef_snapshot": run_esef_snapshot,
    "esef_client": run_esef_client,
}


@contextmanager
def _llm_disabled():
    """El clasificador de anomalias es un LLM: en un eval determinista no corre."""
    from app.services import jev_gates

    original = jev_gates.mark_only
    jev_gates.mark_only = lambda *a, **k: None
    try:
        yield
    finally:
        jev_gates.mark_only = original


def run_case(case: dict) -> dict:
    """Ejecuta el escenario del caso y devuelve la observacion (sin ningun valor esperado)."""
    scenario = case.get("scenario")
    runner = SCENARIOS.get(scenario)
    if runner is None:
        raise KeyError(f"escenario de ingesta desconocido: {scenario!r}")
    with no_network(), _llm_disabled():
        return runner(case)

