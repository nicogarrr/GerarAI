"""Inputs INFERIDO: estimacion con base explicita y URLs web.

Relajacion acotada de #691: el motor pre-revenue solo calcula escenarios con
un margen FCF inferido cuando este lleva base ("dado X, inferimos Y") y al
menos una URL https. Sin base o sin URL no hay numero (fail closed).
"""

from __future__ import annotations

import hashlib
import re
import threading
from decimal import Decimal
from urllib.parse import urlparse

from sqlalchemy import desc, select, text
from sqlalchemy.orm import Session

from app.models import Company, InferredInput

# clave -> (min exclusivo, max inclusivo) del valor aceptado.
ALLOWED_KEYS: dict[str, tuple[float, float]] = {
    "fcf_margin": (-1.0, 0.60),
    # WACC y g terminal: solo cuando no hay CalculatedMetric/dato oficial.
    "wacc": (0.04, 0.30),
    "terminal_growth": (0.0, 0.05),
}
MIN_BASE_CHARS = 20
MAX_URLS = 10
# run_dcf exige WACC > g; el par inferido debe dejar al menos este margen.
MIN_WACC_TERMINAL_SPREAD = 0.02


class InferredInputError(ValueError):
    pass


_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def is_valid_https_url(raw: str | None) -> bool:
    """URL https publica y bien formada: hostname real (con dominio, no IP ni
    localhost), sin credenciales (userinfo) y con puerto valido. Una URL con
    credenciales nunca se guarda ni se muestra."""
    url = (raw or "").strip()
    if not url or url != (raw or "") or any(ch.isspace() or ord(ch) < 32 for ch in url):
        return False
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        return False
    if parsed.scheme != "https" or "@" in parsed.netloc:
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    host = (parsed.hostname or "").lower()
    if not host or host == "localhost" or host.endswith(".localhost"):
        return False
    labels = host.split(".")
    if len(labels) < 2 or not all(_HOST_LABEL.match(label) for label in labels):
        return False
    if labels[-1].isdigit():  # IPv4 literal
        return False
    return port is None or 0 < port <= 65535


def clean_urls(urls: list[str]) -> list[str]:
    out: list[str] = []
    for url in urls:
        if is_valid_https_url(url) and url not in out:
            out.append(url)
    return out[:MAX_URLS]


def validate(key: str, value: float | Decimal | None, base: str | None, urls: list[str]) -> list[str]:
    """Devuelve la lista de problemas; vacia = INFERIDO valido."""
    problems: list[str] = []
    if key not in ALLOWED_KEYS:
        return [f"input no inferible: {key}"]
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ["valor no numerico"]
    low, high = ALLOWED_KEYS[key]
    if not (low < number <= high):
        problems.append("valor fuera de rango")
    if len((base or "").strip()) < MIN_BASE_CHARS:
        problems.append("base explícita ausente o demasiado corta")
    if not urls or not all(is_valid_https_url(u) for u in urls):
        problems.append("falta al menos una URL https válida, o hay URLs inválidas o con credenciales")
    if len(urls) > MAX_URLS:
        problems.append("demasiadas URLs")
    return problems


_company_locks_guard = threading.Lock()
_company_locks: dict[int, threading.Lock] = {}


def validate_rate_spread(db: Session, company: Company, input_key: str, value: Decimal) -> None:
    """Validate the proposed rate against current global company inputs, without fallback."""
    if input_key not in {"wacc", "terminal_growth"}:
        return
    from app.valuation.engines.base import default_terminal_growth, default_wacc, traceable_wacc

    service = InferredInputService()
    if input_key == "wacc":
        other = service.latest_valid(db, company.id, "terminal_growth")
        wacc = float(value)  # Check the proposed WACC even if a calculated WACC exists.
        terminal = float(other.value) if other is not None else default_terminal_growth(company)
    else:
        calculated = traceable_wacc(db, company)
        other = service.latest_valid(db, company.id, "wacc") if calculated is None else None
        wacc = calculated if calculated is not None else (
            float(other.value) if other is not None else default_wacc(company)
        )
        terminal = float(value)
    if wacc - terminal < MIN_WACC_TERMINAL_SPREAD - 1e-9:
        raise InferredInputError("spread_wacc_terminal_insuficiente")


class InferredInputService:
    def create(
        self,
        db: Session,
        company: Company,
        *,
        input_key: str,
        value: Decimal,
        base: str,
        source_urls: list[str],
        origin: str = "llm",
    ) -> InferredInput:
        problems = validate(input_key, value, base, source_urls)
        if problems:
            raise InferredInputError("; ".join(problems))
        row = InferredInput(
            tenant_id=db.info.get("tenant_id"),  # autoria informativa, no filtro
            company_id=company.id,
            input_key=input_key,
            value=value,
            base=base.strip(),
            source_urls=clean_urls(source_urls),
            origin=origin,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    def create_guarded(
        self,
        db: Session,
        company_id: int,
        *,
        input_key: str,
        value: Decimal,
        base: str,
        source_urls: list[str],
        origin: str = "llm",
    ) -> InferredInput:
        """Serialize global rate validation and save for both HTTP write paths.

        Callers commit their read transaction BEFORE entering their write locks.
        LLM callers take the tenant/day quota lock first, then this company lock;
        manual callers take only this company lock. Neither path reverses the order.
        PostgreSQL lock lasts until create commits (or the error rollback).
        Legacy create remains available for historical/imported rows; HTTP writes
        always use this guarded path.
        """
        with _company_locks_guard:
            lock = _company_locks.setdefault(company_id, threading.Lock())
        with lock:
            try:
                if db.get_bind().dialect.name == "postgresql":
                    raw = f"inferred-rate-pair:company:{company_id}".encode()
                    key = int.from_bytes(hashlib.sha256(raw).digest()[:8], "big") >> 1
                    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": key})
                company = db.get(Company, company_id, populate_existing=True)
                if company is None:
                    raise InferredInputError("empresa_no_encontrada")
                problems = validate(input_key, value, base, source_urls)
                if problems:
                    raise InferredInputError("; ".join(problems))
                validate_rate_spread(db, company, input_key, value)
                return self.create(db, company, input_key=input_key, value=value, base=base,
                                   source_urls=source_urls, origin=origin)
            except Exception:
                db.rollback()
                raise

    def latest_valid(self, db: Session, company_id: int, input_key: str) -> InferredInput | None:
        """Ultimo input vigente que sigue siendo valido; el resto se ignora."""
        row = db.scalar(
            select(InferredInput)
            .where(InferredInput.company_id == company_id, InferredInput.input_key == input_key)
            .order_by(desc(InferredInput.id))
            .limit(1)
        )
        if row is None or validate(row.input_key, row.value, row.base, list(row.source_urls or [])):
            return None
        return row


def payload(row: InferredInput) -> dict:
    return {
        "id": row.id,
        "input_key": row.input_key,
        "value": float(row.value),
        "unit": row.unit,
        "base": row.base,
        "source_urls": list(row.source_urls or []),
        "origin": row.origin,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def pick_rate_pair(
    *,
    wacc: float,
    wacc_inferred: bool,
    terminal: float,
    terminal_inferred: bool,
    default_wacc_value: float,
    default_terminal_value: float,
) -> tuple[float, float, list[str]]:
    """Par (wacc, g) con spread minimo. Si un INFERIDO rompe el spread se
    ignora (primero g, luego wacc) y se devuelve la lista de inferidos
    descartados para dejar constancia en trace/limitaciones."""
    dropped: list[str] = []
    if wacc - terminal < MIN_WACC_TERMINAL_SPREAD - 1e-9 and terminal_inferred:
        terminal = default_terminal_value
        dropped.append("terminal_growth")
    if wacc - terminal < MIN_WACC_TERMINAL_SPREAD - 1e-9 and wacc_inferred:
        wacc = default_wacc_value
        dropped.append("wacc")
    return wacc, terminal, dropped
