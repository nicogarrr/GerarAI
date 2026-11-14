"""Fondos y ETF que tienen una acción, con su peso (SEC Form N-PORT Data Sets).

«Escribe una acción y mira qué ETF la tienen»: todas las series registradas que
presentan N-PORT (ETF y fondos de inversión de EE. UU.), leídas del ZIP
trimestral oficial (``connectors.form_nport_dataset``). Determinista, sin
modelo, EUR 0. Identidad por CUSIP exacto (``investor_overlap._cusip``).

Dos listas: los fondos con más acciones (dónde está el volumen pasivo) y los
fondos donde más PESA (qué ETF temáticos la llevan como apuesta). Se guarda en
``public_source_documents`` / ``public_financial_facts`` (sin migración), un
documento por empresa y fichero, una fila por cifra con su informe N-PORT.
"""

from __future__ import annotations

import hashlib
import logging
import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import redact_secrets
from app.models.entities import Company
from app.models.public_market_data import PublicFinancialFact, PublicSourceDocument
from app.services.connectors import form_nport_dataset as nport
from app.services.institutional_holders import linked_cusip_snapshot, universe_cusips

logger = logging.getLogger("gerarai.fund_holders")

PROVIDER = "sec_nport"
NAMESPACE = "secnport"
TOTAL = "__total__"
INTEGRITY_REF = "nport:component-integrity-v1"
TOP_N = 10
LIMITATIONS = (
    "N-PORT: fondos y ETF registrados en EE. UU.; la cartera pública es la del último mes de cada trimestre fiscal del fondo, con hasta 60 días de retraso.",
    "Cada fondo tiene su propia fecha de cartera (se muestra); no son todas del mismo día.",
    "Peso = % del patrimonio neto que declara el propio fondo.",
)


def summarize(latest: dict[str, nport.FundReport], cusip: str) -> dict[str, Any]:
    holders = [r for r in latest.values() if r.shares.get(cusip, Decimal(0)) > 0]
    total_shares = sum((r.shares[cusip] for r in holders), Decimal(0))
    values = [r.value.get(cusip) for r in holders]
    known_values = [value for value in values if value is not None]
    # Valor incompleto: se rechaza (None), nunca se fabrica un subtotal.
    total_value = sum(known_values, Decimal(0)) if len(known_values) == len(values) else None
    key = lambda r: (r.series_id, r.accession)  # noqa: E731
    top = sorted(holders, key=lambda r: (-r.shares[cusip], key(r)))[:TOP_N]
    by_weight = sorted((r for r in holders if r.weight.get(cusip) is not None), key=lambda r: (-r.weight[cusip], key(r)))[:TOP_N]
    return {"funds": len(holders), "shares": total_shares, "value": total_value, "top": top, "by_weight": by_weight}


def _concept(rep: nport.FundReport) -> str:
    return f"{rep.series_id or '-'}|{rep.display_name}"[:200]


def _listing_cusip(listing_key: str) -> str | None:
    """CUSIP con el que se calculó el snapshot (None = documento de antes de la vinculación)."""
    parts = listing_key.split(":")
    return parts[2] if len(parts) > 2 else None


def persist(db: Session, company: Company, cusip: str, summary: dict[str, Any], *, dataset: nport.NportDatasetRef, checksum: str) -> PublicSourceDocument | None:
    # El CUSIP va en el listing_key: corregir el CUSIP de la empresa crea un
    # snapshot nuevo en vez de servir las posiciones calculadas para el anterior.
    listing = f"nport:{dataset.label}:{cusip}"
    exists = db.scalar(select(PublicSourceDocument.id).where(
        PublicSourceDocument.company_id == company.id, PublicSourceDocument.listing_key == listing,
        PublicSourceDocument.provider == PROVIDER, PublicSourceDocument.checksum == checksum))
    if exists is not None:
        return None
    doc = PublicSourceDocument(company_id=company.id, listing_key=listing, provider=PROVIDER, source_url=dataset.url,
                               checksum=checksum, fetched_at=datetime.now(UTC), official=True)
    db.add(doc)
    db.flush()
    today = datetime.now(UTC).date()
    facts = [
        PublicFinancialFact(source_document_id=doc.id, metric=metric, value=Decimal(value), unit=unit, period_end=today,
                            fiscal_quarter=f"Q{dataset.quarter}", filed=None, concept_namespace=NAMESPACE, concept_name=TOTAL,
                            accession=None, confidence=Decimal(1), derived=True, derived_from_refs=[f"dataset:{dataset.url}", INTEGRITY_REF])
        for metric, value, unit in (("nport.total.funds", summary["funds"], "count"), ("nport.total.shares", summary["shares"], "shares"),
                                    ("nport.total.value", summary["value"], "USD"))
        if value is not None
    ]
    roles: dict[str, list[str]] = {}
    reps: dict[str, nport.FundReport] = {}
    for role in ("top", "by_weight"):
        for rep in summary[role]:
            roles.setdefault(rep.accession, []).append(role)
            reps[rep.accession] = rep
    for acc, rep in reps.items():
        tags = [*(f"role:{r}" for r in roles[acc]), f"cik:{rep.cik}"]
        if rep.net_assets is not None:
            tags.append(f"net_assets:{rep.net_assets}")
        for metric, value, unit in (("nport.fund.shares", rep.shares[cusip], "shares"), ("nport.fund.value", rep.value.get(cusip), "USD"),
                                    ("nport.fund.weight_pct", rep.weight.get(cusip), "pct")):
            if value is None:
                continue
            facts.append(PublicFinancialFact(
                source_document_id=doc.id, metric=metric, value=value, unit=unit, period_end=rep.report_date,
                fiscal_quarter=f"Q{(rep.report_date.month - 1) // 3 + 1}", filed=rep.filed, concept_namespace=NAMESPACE,
                concept_name=_concept(rep), accession=rep.accession, confidence=Decimal(1), derived=False, derived_from_refs=tags))
    db.add_all(facts)
    db.flush()
    return doc


def fund_holders(db: Session, ticker: str) -> dict[str, Any] | None:
    """Lectura para la ficha (sin red). None si el ticker no existe."""
    snap = linked_cusip_snapshot(db, ticker, provider=PROVIDER)
    if snap is None:
        return None
    base: dict[str, Any] = {"ticker": snap.company.ticker, "name": snap.company.name, "cusip": snap.cusip,
                            "identity_source": snap.identity, "limitations": list(LIMITATIONS),
                            "top_funds": [], "by_weight": []}
    if snap.status is not None:
        out_status: dict[str, Any] = {**base, "status": snap.status}
        if snap.reason is not None:
            out_status["reason"] = snap.reason
        return out_status
    doc = snap.doc
    totals: dict[str, float] = {}
    funds: dict[str, dict[str, Any]] = {}
    integrity_checked = False
    for f in db.scalars(select(PublicFinancialFact).where(PublicFinancialFact.source_document_id == doc.id).order_by(PublicFinancialFact.id)):
        if f.concept_name == TOTAL:
            integrity_checked |= INTEGRITY_REF in (f.derived_from_refs or [])
            totals[f.metric.rsplit(".", 1)[1]] = float(f.value)
            continue
        acc = f.accession or ""
        series_id, _, name = f.concept_name.partition("|")
        row = funds.setdefault(acc, {"series_id": series_id, "name": name, "accession": acc, "report_date": f.period_end.isoformat(),
                                     "filed": f.filed.isoformat() if f.filed else None, "shares": None, "value_usd": None,
                                     "weight_pct": None, "net_assets_usd": None, "filing_url": None, "_tags": f.derived_from_refs or []})
        row[{"nport.fund.shares": "shares", "nport.fund.value": "value_usd", "nport.fund.weight_pct": "weight_pct"}[f.metric]] = float(f.value)
    top, by_weight = [], []
    for row in funds.values():
        tags = row.pop("_tags")
        for tag in tags:
            if tag.startswith("cik:") and row["accession"]:
                row["filing_url"] = nport.filing_index_url(tag[4:], row["accession"])
            elif tag.startswith("net_assets:"):
                row["net_assets_usd"] = float(tag.split(":", 1)[1])
        if "role:top" in tags:
            top.append(row)
        if "role:by_weight" in tags:
            by_weight.append(row)
    top.sort(key=lambda r: (-(r["shares"] or 0), r["series_id"]))
    by_weight.sort(key=lambda r: (-(r["weight_pct"] or 0), r["series_id"]))
    if not integrity_checked:
        base["limitations"].append(
            "Snapshot N-PORT previo: integridad de importes y pesos no verificada hasta recalcular."
        )
    if "value" not in totals or any(row["value_usd"] is None or row["weight_pct"] is None for row in funds.values()):
        base["limitations"].append(
            "Datos N-PORT incompletos: los importes o pesos con componentes ausentes no se presentan como totales completos."
        )
    return {**base, "status": "ok", "dataset": doc.listing_key.split(":")[1],
            "source": {"dataset_url": doc.source_url, "page": nport.DATASETS_PAGE, "fetched_at": doc.fetched_at.isoformat()},
            "totals": {"funds": int(totals.get("funds", 0)), "shares": totals.get("shares", 0.0), "value_usd": totals.get("value")},
            "top_funds": top, "by_weight": by_weight}


def ingest_reports(db: Session, reports: dict[str, nport.FundReport], dataset: nport.NportDatasetRef, checksum: str,
                   cusips: dict[str, Company]) -> dict[str, Any]:
    latest = nport.latest_by_series(reports)
    if not latest:
        # Sin informes válidos no se guarda nada: un parser que devuelve {}
        # (cabeceras o fechas cambiadas, sin lanzar) no puede convertirse en
        # «0 fondos» ni marcar el fichero como procesado (congelaría el
        # reintento). N/D y a reintentar en la próxima pasada.
        return {"status": "sin_datos", "reason": "el fichero no trae informes N-PORT válidos", "dataset": dataset.label,
                "series": 0, "companies": 0}
    stored = 0
    for cusip, company in cusips.items():
        summary = summarize(latest, cusip)
        # Snapshot aunque no haya fondos: sin documento la ficha serviría el
        # trimestre anterior como si fuera el actual, y el refresh no sabría
        # que esta empresa ya está procesada para este fichero.
        if persist(db, company, cusip, summary, dataset=dataset, checksum=checksum) is not None:
            stored += 1
    db.commit()
    return {"status": "ok", "dataset": dataset.label, "series": len(latest), "companies": stored}


def refresh_fund_holders(db: Session | None = None, client: httpx.Client | None = None) -> dict[str, Any]:
    """Job semanal: si la SEC publicó un ZIP N-PORT nuevo (~460 MB), recalcula. Nunca lanza."""
    import os

    from app.core.config import get_settings
    from app.core.database import SessionLocal

    own_db = db is None
    session = db or SessionLocal()
    http = client or httpx.Client(timeout=300, follow_redirects=True, headers={"User-Agent": get_settings().sec_user_agent})
    path = None
    try:
        page = http.get(nport.DATASETS_PAGE)
        page.raise_for_status()
        refs = nport.list_datasets(page.text)
        if not refs:
            return {"status": "sin_datos", "reason": "la página de la SEC no lista ficheros N-PORT"}
        ref = refs[0]
        cusips = universe_cusips(session)
        if not cusips:
            return {"status": "sin_datos", "reason": "ninguna empresa con CUSIP verificado"}
        # Procesado = TODAS las empresas del universo tienen documento de este
        # fichero; una sola sin procesar obliga a recalcular (persist es
        # idempotente por empresa y checksum, así que solo se guardan las nuevas).
        # Procesado = TODAS las empresas del universo tienen documento de este
        # fichero CALCULADO CON SU CUSIP ACTUAL; un documento sin CUSIP grabado
        # (anterior a la vinculación) o con otro CUSIP obliga a recalcular, así
        # corregir la identidad de una empresa invalida su snapshot.
        company_cusip = {company.id: cusip for cusip, company in cusips.items()}
        rows = session.execute(select(PublicSourceDocument.company_id, PublicSourceDocument.listing_key).where(
            PublicSourceDocument.provider == PROVIDER, PublicSourceDocument.source_url == ref.url)).all()
        processed = {cid for cid, key in rows if _listing_cusip(key) is not None and _listing_cusip(key) == company_cusip.get(cid)}
        if all(company.id in processed for company in cusips.values()):
            return {"status": "sin_cambios", "dataset": ref.url}
        digest = hashlib.sha256()
        handle = tempfile.NamedTemporaryFile(prefix="secnport_", suffix=".zip", delete=False)  # noqa: SIM115 - se borra al final
        path = handle.name
        with handle, http.stream("GET", ref.url) as resp:
            resp.raise_for_status()
            for chunk in resp.iter_bytes(1 << 20):
                digest.update(chunk)
                handle.write(chunk)
        return ingest_reports(session, nport.parse_dataset(path, set(cusips)), ref, digest.hexdigest(), cusips)
    except Exception as exc:  # noqa: BLE001 - job programado
        logger.warning("fund_holders refresh fallo: %s", redact_secrets(str(exc)))
        session.rollback()
        return {"status": "error", "error": redact_secrets(str(exc))[:300]}
    finally:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass
        if client is None:
            http.close()
        if own_db:
            session.close()
