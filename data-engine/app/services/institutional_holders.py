"""Institucionales de TODO el mercado 13F para una acción: quién la tiene, quién compra y quién vende.

Complementa a los ~24 superinversores revisados (``investor_overlap``): aquí
entran todos los gestores que presentan 13F (BlackRock, Vanguard, fondos de
pensiones...), leídos de los Form 13F Data Sets oficiales de la SEC
(``connectors.form13f_dataset``). Determinista, sin modelo, EUR 0.

- Identidad: CUSIP exacto con las mismas comprobaciones que el resto de 13F
  (``investor_overlap._cusip``); sin CUSIP verificado no se afirma nada.
- Trimestre actual = el periodo con más 13F del ZIP más reciente; el anterior =
  el periodo con más 13F del ZIP previo. Se comparan acciones (no valor: la SEC
  no corrige filas declaradas en miles por error).
- Estado por gestor: nuevo (presentó el 13F anterior sin la acción), aumenta,
  reduce, igual, vende_todo (presentó el 13F del trimestre sin la acción),
  sin_13f_aun (tenía la acción y aún no consta su 13F del trimestre: NO es
  venta) o sin_13f_previo (la tiene y no consta su 13F anterior: NO es compra).
- Se guarda en ``public_source_documents`` / ``public_financial_facts`` (datos
  públicos, globales, sin migración): un documento por empresa y trimestre con
  el ZIP citado, y una fila por cifra con la accession del 13F de origen.
"""

from __future__ import annotations

import hashlib
import logging
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import redact_secrets
from app.models.entities import Company, ConnectorState, InstrumentReference
from app.models.public_market_data import PublicFinancialFact, PublicSourceDocument
from app.services.connectors import form13f_dataset as ds
from app.services.data_source_health import get_data_source_registry
from app.services.investor_overlap import _cusip

_REGISTRY_KEY = "form13f_dataset"

logger = logging.getLogger("gerarai.institutional_holders")

PROVIDER = "sec_13f"
NAMESPACE = "sec13f"
TOTAL = "__total__"
TOP_N = 10
MOVERS_N = 10
DETAIL_VERSION = "a1:"
STATUSES = ("nuevo", "aumenta", "reduce", "igual", "vende_todo", "sin_13f_aun", "sin_13f_previo")
LIMITATIONS = (
    "13F: solo gestores con más de 100 M$ en acciones de EE. UU.; trimestral, hasta 45 días de retraso; solo largos (sin cortos ni opciones).",
    "Un gestor puede declarar posiciones que otro también declara (subasesores): la suma del 13F no es igual a las acciones en circulación.",
    "«Sin 13F aún» = tenía la acción el trimestre anterior y su 13F del trimestre no consta en el fichero de la SEC; no se cuenta como venta.",
    "«Sin 13F previo» = la tiene ahora y no consta su 13F del trimestre anterior (gestor nuevo o que no presentó); no se cuenta como compra.",
)


def _quarter(day: date) -> str:
    return f"Q{(day.month - 1) // 3 + 1}"


def _mode_period(parse: ds.DatasetParse) -> date | None:
    counts: dict[date, int] = {}
    for filing in parse.filings.values():
        if filing.form == "13F-HR":
            counts[filing.period] = counts.get(filing.period, 0) + 1
    return max(counts, key=lambda p: (counts[p], p)) if counts else None


@dataclass
class HolderRow:
    cik: str
    manager: str
    shares: Decimal
    prev_shares: Decimal
    status: str
    accession: str | None
    filed: date | None
    prev_accession: str | None
    prev_filed: date | None
    value_usd: Decimal | None = None
    accessions: list[str] = field(default_factory=list)

    @property
    def change(self) -> Decimal:
        return self.shares - self.prev_shares


def _status(cur: Decimal, prev: Decimal, filed_now: bool, held_before: bool, filed_before: bool = True) -> str:
    if cur > 0 and not held_before:
        return "nuevo" if filed_before else "sin_13f_previo"
    if cur > 0:
        return "aumenta" if cur > prev else "reduce" if cur < prev else "igual"
    return "vende_todo" if filed_now else "sin_13f_aun"


def summarize(periods: dict[date, dict[str, ds.ManagerPeriod]], cusip: str, current: date, prior: date) -> dict[str, Any]:
    """Agregado determinista de un CUSIP entre dos trimestres (sin BD)."""
    now = periods.get(current, {})
    before = periods.get(prior, {})
    rows: list[HolderRow] = []
    for cik in set(now) | set(before):
        mnow, mbefore = now.get(cik), before.get(cik)
        cur = mnow.shares.get(cusip, Decimal(0)) if mnow else Decimal(0)
        prev = mbefore.shares.get(cusip, Decimal(0)) if mbefore else Decimal(0)
        if cur <= 0 and prev <= 0:
            continue
        src = mnow or mbefore
        rows.append(HolderRow(
            cik=cik,
            manager=src.manager if src is not None else "",
            shares=cur, prev_shares=prev,
            status=_status(cur, prev, mnow is not None, prev > 0, mbefore is not None),
            accession=mnow.accession if mnow else None, filed=mnow.filed if mnow else None,
            prev_accession=mbefore.accession if mbefore else None,
            prev_filed=mbefore.filed if mbefore else None,
            value_usd=mnow.values_usd.get(cusip) if mnow else None,
            accessions=list(dict.fromkeys([mnow.accession, *mnow.amendments])) if mnow else [],
        ))
    holders = [r for r in rows if r.shares > 0]
    total = sum((r.shares for r in holders), Decimal(0))
    total_prev = sum((r.prev_shares for r in rows), Decimal(0))
    # Neto comparable: solo gestores con 13F en ambos trimestres (un gestor nuevo
    # en el 13F o uno que aún no ha presentado no mueven este neto).
    both = set(now) & set(before)
    comparable = [r for r in rows if r.cik in both]
    counts = {s: sum(1 for r in rows if r.status == s) for s in STATUSES}
    key = lambda r: (r.cik,)  # noqa: E731 - desempate estable
    top = sorted(holders, key=lambda r: (-r.shares, key(r)))[:TOP_N]
    # Compras y ventas solo entre quien presentó ambos trimestres o abre/cierra
    # posición con 13F en los dos (sin 13F previo / aún no son movimientos).
    buyers = sorted((r for r in rows if r.change > 0 and r.status not in ("sin_13f_aun", "sin_13f_previo")), key=lambda r: (-r.change, key(r)))[:MOVERS_N]
    sellers = sorted((r for r in rows if r.change < 0 and r.status not in ("sin_13f_aun", "sin_13f_previo")), key=lambda r: (r.change, key(r)))[:MOVERS_N]
    new = [r for r in rows if r.status == "nuevo"]
    valued_new = [r for r in new if r.value_usd is not None]
    return {
        "new_by_shares": sorted(new, key=lambda r: (-r.shares, r.cik))[:TOP_N],
        "new_by_value": sorted(valued_new, key=lambda r: (-r.value_usd, r.cik))[:TOP_N],
        "new_value_known_count": len(valued_new),
        "current": current, "prior": prior,
        "totals": {
            "holders": len(holders),
            "holders_prior": sum(1 for r in rows if r.prev_shares > 0),
            "shares": total, "shares_prior": total_prev,
            "net_comparable": sum((r.change for r in comparable), Decimal(0)),
            **counts,
        },
        "top": top, "buyers": buyers, "sellers": sellers, "activity": rows,
    }


def _name(row: HolderRow) -> str:
    return f"{row.cik}|{row.manager}"[:200]


def _listing_cusip(listing_key: str) -> str | None:
    """CUSIP con el que se calculó el snapshot (None = documento de antes de la vinculación)."""
    parts = listing_key.split(":")
    return parts[2] if len(parts) > 2 else None


def persist(db: Session, company: Company, summary: dict[str, Any], *, cusip: str, dataset_url: str, prior_url: str, checksum: str) -> PublicSourceDocument | None:
    """Guarda el agregado (idempotente por checksum de los ZIP y CUSIP usado).

    El CUSIP va en el listing_key: corregir el CUSIP de la empresa crea un
    snapshot nuevo en vez de servir las posiciones calculadas para el anterior.
    """
    current: date = summary["current"]
    prior: date = summary["prior"]
    listing = f"13f:{current.isoformat()}:{cusip}"
    existing = db.scalar(select(PublicSourceDocument).where(
        PublicSourceDocument.company_id == company.id, PublicSourceDocument.listing_key == listing,
        PublicSourceDocument.provider == PROVIDER, PublicSourceDocument.checksum == checksum))
    if existing is not None:
        return None
    doc = PublicSourceDocument(company_id=company.id, listing_key=listing, provider=PROVIDER, source_url=dataset_url,
                               checksum=checksum, fetched_at=datetime.now(UTC), official=True)
    db.add(doc)
    db.flush()
    facts: list[PublicFinancialFact] = []

    def add(metric: str, value: Decimal | int, unit: str, period: date, concept: str, *, accession: str | None = None,
            filed: date | None = None, refs: list[str] | None = None, derived: bool = False) -> None:
        facts.append(PublicFinancialFact(
            source_document_id=doc.id, metric=metric, value=Decimal(value), unit=unit, period_end=period,
            fiscal_quarter=_quarter(period), filed=filed, concept_namespace=NAMESPACE, concept_name=concept,
            accession=accession, confidence=Decimal(1), derived=derived, derived_from_refs=refs or []))

    totals = summary["totals"]
    refs = [f"dataset:{dataset_url}", f"prior_dataset:{prior_url}"]
    add("13f.total.holders", totals["holders"], "count", current, TOTAL, refs=refs)
    add("13f.total.holders", totals["holders_prior"], "count", prior, TOTAL, refs=refs)
    add("13f.total.shares", totals["shares"], "shares", current, TOTAL, refs=refs)
    add("13f.total.shares", totals["shares_prior"], "shares", prior, TOTAL, refs=refs)
    add("13f.total.net_comparable", totals["net_comparable"], "shares", current, TOTAL, refs=refs, derived=True)
    for status in STATUSES:
        add(f"13f.count.{status}", totals[status], "count", current, TOTAL, refs=refs, derived=True)
    if "new_by_shares" in summary:
        add("13f.count.new_detail_version", 1, "count", current, TOTAL, refs=refs)
        add("13f.count.new_value_known", summary["new_value_known_count"], "count", current, TOTAL, refs=refs)
    if "activity" in summary:
        add("13f.count.activity_detail_version", 1, "count", current, TOTAL, refs=refs)
    roles_to_store = ("top", "buyers", "sellers", "new_by_shares", "new_by_value", "activity")
    seen: set[str] = set()
    roles: dict[str, list[str]] = {}
    for role in roles_to_store:
        for row in summary.get(role, []):
            roles.setdefault(row.cik, []).append(role)
    for role in roles_to_store:
        for row in summary.get(role, []):
            if row.cik in seen:
                continue
            seen.add(row.cik)
            # New roles use their own namespace so an older reader can ignore
            # them during rollback rather than indexing an unknown role key.
            tags = [f"status:{row.status}",
                    *("activity_role:all" if r == "activity" else f"{'new_role' if r.startswith('new_') else 'role'}:{r}" for r in roles[row.cik]),
                    *(f"value_accession:{acc}" for acc in row.accessions)]
            if row.value_usd is not None:
                add("13f.holder.value_usd", row.value_usd, "USD", current, _name(row),
                    accession=row.accession, filed=row.filed, refs=tags)
            # Old readers treat unknown metrics as current shares. Put the
            # actual shares last so rollback still sees the correct quantity.
            add("13f.holder.shares", row.shares, "shares", current, _name(row), accession=row.accession, filed=row.filed, refs=tags)
            add("13f.holder.prev_shares", row.prev_shares, "shares", prior, _name(row), accession=row.prev_accession,
                filed=row.prev_filed, refs=tags)
    db.add_all(facts)
    db.flush()
    return doc


def _holder_out(cik: str, name: str, shares: Decimal, prev: Decimal, status: str, total: Decimal,
                accession: str | None, filed: date | None, prev_accession: str | None) -> dict[str, Any]:
    change = shares - prev
    return {
        "cik": cik, "name": name, "shares": float(shares), "prev_shares": float(prev), "change": float(change),
        "change_pct": float(change / prev * 100) if prev > 0 else None,
        "pct_of_13f": float(shares / total * 100) if total > 0 and shares > 0 else None,
        "status": status, "accession": accession, "filed": filed.isoformat() if filed else None,
        "filing_url": ds.filing_index_url(cik, accession) if accession else None,
        "prev_filing_url": ds.filing_index_url(cik, prev_accession) if prev_accession else None,
    }


@dataclass
class LinkedSnapshot:
    """Empresa + snapshot calculado para su CUSIP actual (o el motivo de no servir)."""

    company: Company
    cusip: str | None
    identity: str | None
    doc: PublicSourceDocument | None
    status: str | None = None  # None = hay documento vinculado que servir
    reason: str | None = None


def linked_cusip_snapshot(db: Session, ticker: str, *, provider: str) -> LinkedSnapshot | None:
    """Localiza el último snapshot del proveedor vinculado al CUSIP actual del ticker.

    None si el ticker no existe. ``status`` queda None cuando hay documento
    vinculado que servir; si no, indica el motivo (``sin_identificador``,
    ``sin_snapshot_vinculado`` o ``sin_datos``).

    Fail-closed: solo se sirve el snapshot calculado para el CUSIP actual.
    Un documento legado (listing_key sin CUSIP, de antes de la vinculación)
    se calculó para otra identidad o para ninguna: servirlo mostraría
    posiciones de otro identificador, así que la lectura da N/D con motivo
    hasta que el refresh grabe uno vinculado. La historia no se borra. El
    filtro va en SQL: sin tope arbitrario que pueda tapar el válido.
    """
    normalized = ticker.strip().upper()
    company = db.scalar(select(Company).where(Company.ticker == normalized))
    if company is None:
        return None
    reference = db.scalar(select(InstrumentReference).where(InstrumentReference.ticker_normalized == normalized))
    cusip, identity = _cusip(company, reference)
    if cusip is None:
        return LinkedSnapshot(company=company, cusip=cusip, identity=identity, doc=None, status="sin_identificador")
    listing = PublicSourceDocument.listing_key
    doc = db.scalars(select(PublicSourceDocument).where(
        PublicSourceDocument.company_id == company.id, PublicSourceDocument.provider == provider,
        listing.like(f"%:{cusip}"))
        .order_by(listing.desc(), PublicSourceDocument.fetched_at.desc(), PublicSourceDocument.id.desc())).first()
    if doc is None:
        pendiente = db.scalar(select(PublicSourceDocument.id).where(
            PublicSourceDocument.company_id == company.id,
            PublicSourceDocument.provider == provider).limit(1))
        if pendiente is not None:
            return LinkedSnapshot(company=company, cusip=cusip, identity=identity, doc=None,
                                  status="sin_snapshot_vinculado",
                                  reason="hay snapshots guardados pero ninguno calculado para el CUSIP actual; "
                                         "el refresh lo recalcula (un snapshot legado u otro identificador no se sirve)")
        return LinkedSnapshot(company=company, cusip=cusip, identity=identity, doc=None, status="sin_datos")
    return LinkedSnapshot(company=company, cusip=cusip, identity=identity, doc=doc)


def institutional_holders(db: Session, ticker: str) -> dict[str, Any] | None:
    """Lectura para la ficha (sin red): el último trimestre guardado. None si el ticker no existe."""
    snap = linked_cusip_snapshot(db, ticker, provider=PROVIDER)
    if snap is None:
        return None
    base: dict[str, Any] = {"ticker": snap.company.ticker, "name": snap.company.name, "cusip": snap.cusip,
                            "identity_source": snap.identity, "limitations": list(LIMITATIONS),
                            "top_holders": [], "buyers": [], "sellers": [],
                            "new_positions": {"status": "sin_datos", "count": None, "value_known_count": None,
                                              "top_by_shares": [], "top_by_value": []}}
    if snap.status is not None:
        out_status: dict[str, Any] = {**base, "status": snap.status}
        if snap.reason is not None:
            out_status["reason"] = snap.reason
        return out_status
    doc = snap.doc
    facts = list(db.scalars(select(PublicFinancialFact).where(PublicFinancialFact.source_document_id == doc.id).order_by(PublicFinancialFact.id)))
    current = date.fromisoformat(doc.listing_key.split(":")[1])
    totals: dict[str, Any] = {}
    prior: date | None = None
    prior_url = None
    holders: dict[str, dict[str, Any]] = {}
    for f in facts:
        if f.concept_name == TOTAL:
            for ref in f.derived_from_refs or []:
                if ref.startswith("prior_dataset:"):
                    prior_url = ref.split(":", 1)[1]
            suffix = "_prior" if f.period_end != current else ""
            if f.period_end != current:
                prior = f.period_end
            totals[f.metric.split(".", 2)[2] + suffix] = float(f.value)
            continue
        h = holders.setdefault(f.concept_name, {"tags": list(f.derived_from_refs or [])})
        field = {"13f.holder.prev_shares": "prev", "13f.holder.value_usd": "value"}.get(f.metric, "cur")
        h[field] = f
    total_shares = Decimal(str(totals.get("shares", 0)))
    out: dict[str, list[dict[str, Any]]] = {key: [] for key in ("top", "buyers", "sellers", "new_by_shares", "new_by_value")}
    for concept, h in holders.items():
        cik, _, name = concept.partition("|")
        cur, prev = h.get("cur"), h.get("prev")
        status = next((t.split(":", 1)[1] for t in h["tags"] if t.startswith("status:")), "")
        row = _holder_out(cik, name, cur.value if cur else Decimal(0), prev.value if prev else Decimal(0), status, total_shares,
                          cur.accession if cur else None, cur.filed if cur else None, prev.accession if prev else None)
        row["value_usd"] = float(h["value"].value) if h.get("value") is not None else None
        row["value_filing_urls"] = [ds.filing_index_url(cik, tag.split(":", 1)[1])
                                    for tag in h["tags"] if tag.startswith("value_accession:")] if row["value_usd"] is not None else []
        for tag in h["tags"]:
            if tag.startswith(("role:", "new_role:")):
                out[tag.split(":", 1)[1]].append(row)
    out["new_by_shares"].sort(key=lambda r: (-r["shares"], r["cik"]))
    out["new_by_value"].sort(key=lambda r: (-r["value_usd"], r["cik"]))
    new_detail = "new_detail_version" in totals
    new_count = int(totals.get("nuevo", 0))
    known_count = int(totals.get("new_value_known", 0)) if new_detail else None
    out["top"].sort(key=lambda r: (-r["shares"], r["cik"]))
    out["buyers"].sort(key=lambda r: (-r["change"], r["cik"]))
    out["sellers"].sort(key=lambda r: (r["change"], r["cik"]))
    return {
        **base, "status": "ok", "period": current.isoformat(), "prior_period": prior.isoformat() if prior else None,
        "source": {"dataset_url": doc.source_url, "prior_dataset_url": prior_url, "fetched_at": doc.fetched_at.isoformat(),
                   "page": ds.DATASETS_PAGE},
        "totals": {
            "holders": int(totals.get("holders", 0)), "holders_prior": int(totals.get("holders_prior", 0)),
            "shares": totals.get("shares", 0.0), "shares_prior": totals.get("shares_prior", 0.0),
            "net_comparable": totals.get("net_comparable", 0.0),
            **{s: int(totals.get(f"{s}", 0)) for s in STATUSES},
        },
        "top_holders": out["top"], "buyers": out["buyers"], "sellers": out["sellers"],
        "new_positions": {
            "status": ("ok" if known_count == new_count else "valor_parcial") if new_detail else "sin_detalle",
            "count": new_count, "value_known_count": known_count,
            "top_by_shares": out["new_by_shares"], "top_by_value": out["new_by_value"],
            "value_basis": "Valor USD declarado en el 13F al cierre del trimestre; no valor actual. Errores del declarante no corregidos.",
        },
    }


def universe_cusips(db: Session) -> dict[str, Company]:
    """CUSIP verificado -> empresa, para todo el universo (general, nunca por ticker)."""
    refs = {r.ticker_normalized: r for r in db.scalars(select(InstrumentReference))}
    out: dict[str, Company] = {}
    for company in db.scalars(select(Company).order_by(Company.id)):
        cusip, _ = _cusip(company, refs.get(company.ticker.strip().upper()))
        if cusip:
            out.setdefault(cusip, company)
    return out


def ingest_parsed(db: Session, parses: list[ds.DatasetParse], checksums: list[str], cusips: dict[str, Company]) -> dict[str, Any]:
    """Agrega y guarda para cada empresa del universo (parses[0] = ZIP más reciente)."""
    if len(parses) < 2:
        return {"status": "sin_datos", "reason": "hacen falta dos ficheros trimestrales"}
    current, prior = _mode_period(parses[0]), _mode_period(parses[1])
    if current is None or prior is None or prior >= current:
        return {"status": "sin_datos", "reason": "periodos no comparables"}
    periods, ignored = ds.resolve_periods(parses)
    missing = [label for label, period in (("actual", current), ("previo", prior)) if not periods.get(period)]
    if missing:
        # Un trimestre sin 13F VÁLIDOS (todos ignorados: incompletos o cabeceras
        # cambiadas) NO es ausencia observada: N/D sin persistir. Guardar ceros
        # sería inventar «no aparece en este fichero», marcaría el fichero como
        # procesado y congelaría el reintento del refresh semanal.
        return {"status": "sin_datos", "reason": f"sin 13F válidos en el trimestre {' y '.join(missing)}",
                "period": current.isoformat(), "prior": prior.isoformat(), "companies": 0, "filings_skipped": ignored}
    checksum = DETAIL_VERSION + hashlib.sha256("|".join(checksums).encode()).hexdigest()[:61]
    stored = 0
    for cusip, company in cusips.items():
        summary = summarize(periods, cusip, current, prior)
        # Snapshot aunque no haya holders en ningún periodo: sin documento la
        # ficha serviría el trimestre anterior como actual y el refresh no
        # sabría que esta empresa ya está procesada para este fichero.
        if persist(db, company, summary, cusip=cusip, dataset_url=parses[0].url, prior_url=parses[1].url, checksum=checksum) is not None:
            stored += 1
    db.commit()
    return {"status": "ok", "period": current.isoformat(), "prior": prior.isoformat(), "companies": stored,
            "filings_skipped": ignored}


def _download(http: httpx.Client, url: str) -> tuple[str, str, str | None]:
    digest = hashlib.sha256()
    handle = tempfile.NamedTemporaryFile(prefix="sec13f_", suffix=".zip", delete=False)  # noqa: SIM115 - se borra al final
    with handle, http.stream("GET", url) as resp:
        resp.raise_for_status()
        etag = resp.headers.get("etag")
        for chunk in resp.iter_bytes(1 << 20):
            digest.update(chunk)
            handle.write(chunk)
    return handle.name, digest.hexdigest(), etag


def _head_etag(http: httpx.Client, url: str) -> str | None:
    """ETag del ZIP por HEAD; None si la SEC no lo sirve (no bloquea el salto)."""
    try:
        resp = http.head(url)
    except httpx.HTTPError:
        return None
    if resp.status_code >= 400:
        return None
    return resp.headers.get("etag")


def _save_etag(session: Session, connector: str, url: str, state: ConnectorState | None, etag: str | None) -> None:
    """Persiste el ETag del ZIP procesado (fila global, sin tenant) para que una
    republicacion del mismo URL con contenido corregido fuerce recalculo."""
    if state is None:
        state = ConnectorState(connector=connector, feed_url=url, metadata_={})
        session.add(state)
    if etag:
        state.etag = etag
    state.last_success_at = datetime.now(UTC)
    session.commit()


def refresh_institutional_holders(db: Session | None = None, client: httpx.Client | None = None) -> dict[str, Any]:
    """Job semanal: si la SEC publicó un ZIP nuevo, recalcula todo el universo. Nunca lanza.

    3 peticiones como mucho (página + 2 ZIP de ~100 MB), User-Agent de
    contacto de la configuración (acceso justo de la SEC)."""
    import os

    from app.core.config import get_settings
    from app.core.database import SessionLocal

    own_db = db is None
    session = db or SessionLocal()
    http = client or httpx.Client(timeout=120, follow_redirects=True, headers={"User-Agent": get_settings().sec_user_agent})
    paths: list[str] = []
    registry = get_data_source_registry()
    started = time.perf_counter()
    try:
        page = http.get(ds.DATASETS_PAGE)
        page.raise_for_status()
        refs = ds.list_datasets(page.text)[:2]
        if len(refs) < 2:
            registry.record_failure(_REGISTRY_KEY, "la pagina de la SEC no lista dos ficheros")
            return {"status": "sin_datos", "reason": "la página de la SEC no lista dos ficheros"}
        cusips = universe_cusips(session)
        if not cusips:
            return {"status": "sin_datos", "reason": "ninguna empresa con CUSIP verificado"}
        # Procesado = TODAS las empresas del universo tienen documento de este
        # fichero; una sola sin procesar obliga a recalcular (persist es
        # idempotente por empresa y checksum, así que solo se guardan las nuevas).
        # Procesado = TODAS las empresas del universo tienen documento de este
        # fichero CALCULADO CON SU CUSIP ACTUAL; un documento sin CUSIP grabado
        # (anterior a la vinculación) o con otro CUSIP obliga a recalcular, así
        # corregir la identidad de una empresa invalida su snapshot (persist es
        # idempotente por empresa, CUSIP y checksum: solo se guardan las nuevas).
        company_cusip = {company.id: cusip for cusip, company in cusips.items()}
        rows = session.execute(select(PublicSourceDocument.company_id, PublicSourceDocument.listing_key).where(
            PublicSourceDocument.provider == PROVIDER, PublicSourceDocument.source_url == refs[0].url,
            PublicSourceDocument.checksum.startswith(DETAIL_VERSION))).all()
        processed = {cid for cid, key in rows if _listing_cusip(key) is not None and _listing_cusip(key) == company_cusip.get(cid)}
        # El salto no vale solo por URL: si la SEC republica un ZIP con
        # contenido corregido (otro ETag), hay que recalcular aunque todas las
        # empresas tengan documento de ese URL. Se vigilan AMBOS ZIP: el
        # resumen compara el trimestre actual con el previo, así que una
        # corrección republicada del previo también cambia el resultado.
        head_etags = [_head_etag(http, ref.url) for ref in refs]
        states = {
            ref.url: session.scalars(select(ConnectorState).where(
                ConnectorState.connector == _REGISTRY_KEY,
                ConnectorState.company_id.is_(None),
                ConnectorState.feed_url == ref.url)).first()
            for ref in refs
        }
        etag_changed = any(
            states[ref.url] is not None and states[ref.url].etag and head_etags[i]
            and states[ref.url].etag != head_etags[i]
            for i, ref in enumerate(refs))
        # Datos procesados ANTES de la vigilancia por ETag (o con el HEAD
        # caído aquel día): sin ETag guardado el salto «sin_cambios» se
        # repetiría para siempre aunque la SEC republicara el ZIP. Si la SEC
        # sí sirve ETag y no hay ninguno guardado, hay que descargar una vez
        # y fijarlo (migración pre-ETag).
        etag_missing = any(
            head_etags[i] and not (states[ref.url] is not None and states[ref.url].etag)
            for i, ref in enumerate(refs))
        if not etag_changed and not etag_missing and all(company.id in processed for company in cusips.values()):
            registry.record_success(_REGISTRY_KEY, (time.perf_counter() - started) * 1000)
            return {"status": "sin_cambios", "dataset": refs[0].url}
        parses, checksums, etags = [], [], []
        for ref in refs:
            path, checksum, etag = _download(http, ref.url)
            paths.append(path)
            parses.append(ds.parse_dataset(path, set(cusips), url=ref.url))
            checksums.append(checksum)
            etags.append(etag)
        result = ingest_parsed(session, parses, checksums, cusips)
        if result.get("status") != "ok":
            # Dataset ilegible (parseador roto o cabeceras cambiadas): no se
            # afirma salud ni se fija el ETag — la próxima pasada reintenta.
            registry.record_failure(_REGISTRY_KEY, f"dataset ilegible: {result.get('reason', '')[:120]}")
            return result
        for i, ref in enumerate(refs):
            _save_etag(session, _REGISTRY_KEY, ref.url, states[ref.url], etags[i] or head_etags[i])
        registry.record_success(_REGISTRY_KEY, (time.perf_counter() - started) * 1000)
        return result
    except Exception as exc:  # noqa: BLE001 - job programado: se informa, no se cae
        registry.record_failure(_REGISTRY_KEY, type(exc).__name__)
        logger.warning("institutional_holders refresh fallo: %s", redact_secrets(str(exc)))
        session.rollback()
        return {"status": "error", "error": redact_secrets(str(exc))[:300]}
    finally:
        for path in paths:
            try:
                os.unlink(path)
            except OSError:
                pass
        if client is None:
            http.close()
        if own_db:
            session.close()
