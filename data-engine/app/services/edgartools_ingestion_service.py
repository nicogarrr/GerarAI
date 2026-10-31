"""Ingesta SEC paralela basada en edgartools (via nueva, mismo contrato).

- Detras del flag ``EDGARTOOLS_ENABLED`` (off por defecto: dependencia de
  bus-factor 1, BUG-1 en vuelo, y el enchufado al scheduler/Dramatiq es un
  follow-up explicito). Con ``force=True`` (tests/herramientas) se salta el
  flag; NO hay wiring al scheduler ni a Dramatiq en este modulo.
- ``refresh_from_edgartools(db, company)``: 10-K/10-Q -> ``FinancialFact``
  con ``source_type="SEC"`` (cero cambios en consumidores) en un ``Document``
  propio (``source_type="SEC"``, titulo "...(edgartools)..."); el replace solo
  borra lo que escribio ESTE documento (frontera de propiedad como
  ``_replace_esef_data``), nunca filas de otras vias. Re-ejecutar es
  idempotente. Derivadas (FCF, margenes...) NO se recalculan aqui: las
  calcula ``metric_calculation_service`` como siempre.
- Form 4 / 13F: ``refresh_form4_from_edgartools`` y
  ``refresh_13f_from_edgartools`` devuelven el MISMO shape que
  ``insider_service.get_signals_for_ticker`` (transacciones) y
  ``ManagerHoldingIngestionService.latest_holdings`` (filas), sin escribir
  tablas de insider/holdings (el persistido es follow-up tras BUG-1).
- Transporte: live edgartools (solo dev con red) o snapshot local
  (produccion OCI: 401/403 -> snapshot, 429 -> racha del breaker + snapshot,
  jamas reintento en bucle). El resultado declara ``transport`` +
  ``snapshot_synced_at`` siempre.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import redact_secrets
from app.models import Company, Document, FinancialFact
from app.services.connectors import edgartools_client as client
from app.services.connectors.edgartools_facts import (
    anchors_from_submissions,
    facts_from_companyfacts,
    facts_from_edgartools_entity,
)
from app.services.connectors.edgartools_ownership import (
    enrich_like_insider_service,
    ownership_transactions,
)
from app.services.connectors.edgartools_thirteenf import infotable_holdings
from app.services.fact_deletion import (
    delete_financial_facts,
    drop_shadowed_facts,
    tenant_condition,
)
from app.services.financial_ingestion_service import BANK_REVENUE_TICKERS
from app.services.provenance import Coverage, SourceKind, provenance

SOURCE = "sec_edgar_edgartools"
PROVIDER = "SEC"
PIPELINE = "edgartools"


def is_enabled() -> bool:
    from app.core.config import get_settings

    return bool(get_settings().edgartools_enabled)


def _disabled(ticker: str) -> dict[str, Any]:
    return {
        "status": "disabled",
        "ticker": ticker.upper(),
        "reason": "EDGARTOOLS_ENABLED=false (via off por defecto; ver informe de enchufado)",
        "provenance": provenance(SOURCE, SourceKind.OFFICIAL, coverage=Coverage.UNAVAILABLE),
    }


def _is_bank_like(company: Any) -> bool:
    """Gate de composicion de revenue bancario (misma regla que la via actual)."""
    industry = str(getattr(company, "industry", "") or "").strip().lower()
    if any(k in industry for k in ("bank", "thrift", "savings", "capital markets")):
        return True
    return str(getattr(company, "ticker", "") or "").strip().upper() in BANK_REVENUE_TICKERS


def _tenant_filter(db: Session, model: Any) -> Any:
    tenant_id = db.info.get("tenant_id")
    if tenant_id is not None:
        return model.tenant_id == tenant_id
    return model.tenant_id.is_(None)


def _source_document(db: Session, company: Company, ticker: str) -> Document:
    title = f"SEC XBRL facts (edgartools) - {ticker}"
    document = db.scalar(
        select(Document).where(
            Document.company_id == company.id,
            Document.source_type == PROVIDER,
            Document.title == title,
        )
    )
    if document is not None:
        return document
    document = Document(
        company_id=company.id,
        title=title,
        source_type=PROVIDER,
        source_url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&ticker={ticker}&type=10-K",
        metadata_={"provider": PROVIDER, "pipeline": PIPELINE, "normalized": True},
    )
    db.add(document)
    db.flush()
    return document


def _replace_own_facts(db: Session, company: Company, document: Document) -> None:
    """Borra solo lo escrito por ESTE documento (frontera como _replace_esef_data)."""
    delete_financial_facts(
        db,
        FinancialFact.company_id == company.id,
        FinancialFact.source_id == document.id,
        _tenant_filter(db, FinancialFact),
    )


def _pad_cik(value: Any) -> str | None:
    """CIK a 10 digitos, o None si no hay CIK.

    ``"".zfill(10)`` devuelve "0000000000" (truthy): un CIK vacio se convertia
    en un CIK fabricado que saltaba el lookup por ticker, generaba URLs SEC
    falsas y llegaba a la respuesta como si fuera real.
    """
    text = str(value or "").strip()
    return text.zfill(10) if text else None


def _fetch_live_entity_facts(cik_or_ticker: str) -> tuple[Any | None, str | None]:
    """``(entity_facts, cik)`` live via edgartools (solo dev con red).

    Punto unico de red de la via: los tests lo sustituyen para simular
    403/429 sin tocar la red jamas.
    """
    from edgar import Company as EdgarCompany

    client.throttle_sync()
    edgar_company = EdgarCompany(cik_or_ticker)
    cik = _pad_cik(getattr(edgar_company, "cik", ""))
    return edgar_company.get_facts(), cik


def _snapshot_payloads(
    ticker: str, root: Any = None
) -> tuple[str | None, dict | None, dict | None, str | None]:
    """``(cik, companyfacts, submissions, synced_at)`` desde snapshot, o Nones."""
    cik = client.manifest_cik(ticker, root)
    if not cik:
        return None, None, None, None
    facts = client.read_companyfacts(cik, root)
    subs = client.read_submissions(cik, root)
    if facts is None:
        return None, None, None, None
    return cik, facts, subs, client.manifest_synced_at(root)


def _degrade_to_snapshot(ticker: str, reason: str, root: Any = None) -> tuple[Any, ...]:
    cik, facts, subs, synced_at = _snapshot_payloads(ticker, root)
    state = client.TransportState(transport="snapshot", synced_at=synced_at, reason=reason)
    return cik, facts, subs, state


def refresh_from_edgartools(
    db: Session,
    company: Company,
    *,
    force: bool = False,
    bank_like: bool | None = None,
    companyfacts: dict | None = None,
    submissions: dict | None = None,
    annual_anchors: dict[str, str] | None = None,
    entity_facts: Any | None = None,
    snapshot_root: Any | None = None,
) -> dict[str, Any]:
    """10-K/10-Q -> FinancialFact (source_type="SEC"). Lista para enchufar.

    Payloads inyectables (tests hermeticos, cero red). Sin inyeccion: intenta
    live edgartools y degrada al snapshot ante 401/403/429 o sin libreria.
    """
    ticker = str(company.ticker).upper()
    if not force and not is_enabled():
        return _disabled(ticker)
    client.ensure_identity()

    transport = "live"
    synced_at: str | None = None
    cik = _pad_cik(getattr(company, "cik", ""))
    facts_payload = companyfacts
    subs_payload = submissions
    anchors = annual_anchors
    used_entity_facts = entity_facts

    if facts_payload is None and used_entity_facts is None:
        live_cik = cik or client.manifest_cik(ticker, snapshot_root)
        if live_cik:
            cik = live_cik
            facts_payload = client.read_companyfacts(live_cik, snapshot_root)
            subs_payload = (
                subs_payload if subs_payload is not None else client.read_submissions(live_cik, snapshot_root)
            )
            if facts_payload is not None:
                synced_at = client.manifest_synced_at(snapshot_root)
                transport = "snapshot"
        if facts_payload is None and client.is_installed():
            try:
                used_entity_facts, live_cik = _fetch_live_entity_facts(cik or ticker)
                if not cik:
                    cik = live_cik
                client.default_breaker().record_success()
                client.report_sec_success_to_health()
            except Exception as exc:  # noqa: BLE001 - degrada a snapshot, nunca reintenta
                status = client.http_status_from_error(exc)
                # Registry central de salud: 400/404 no degradan (dato por ticker)
                client.report_sec_failure_to_health(status)
                if status == 429:
                    client.default_breaker().record_429()
                    reason = f"429 rate-limited ({type(exc).__name__}); breaker cuenta la racha"
                elif status in (401, 403):
                    reason = f"SEC bloqueada ({status}, caso OCI); snapshot sin reintento"
                else:
                    reason = f"live no disponible ({type(exc).__name__}); snapshot"
                cik, facts_payload, subs_payload, state = _degrade_to_snapshot(ticker, reason, snapshot_root)
                transport, synced_at = state.transport, state.synced_at
                if facts_payload is None and used_entity_facts is None:
                    return {
                        "status": "unavailable",
                        "ticker": ticker,
                        "provider": PROVIDER,
                        "pipeline": PIPELINE,
                        "transport": transport,
                        "snapshot_synced_at": synced_at,
                        "reason": redact_secrets(f"{reason}: sin snapshot local para {ticker}"),
                        "provenance": provenance(SOURCE, SourceKind.OFFICIAL, coverage=Coverage.UNAVAILABLE),
                    }
        elif facts_payload is None:
            cik, facts_payload, subs_payload, state = _degrade_to_snapshot(
                ticker, "edgartools no instalado; snapshot", snapshot_root
            )
            transport, synced_at = state.transport, state.synced_at
            if facts_payload is None:
                return {
                    "status": "unavailable",
                    "ticker": ticker,
                    "provider": PROVIDER,
                    "pipeline": PIPELINE,
                    "transport": transport,
                    "snapshot_synced_at": synced_at,
                    "reason": f"edgartools no instalado y sin snapshot local para {ticker}",
                    "provenance": provenance(SOURCE, SourceKind.OFFICIAL, coverage=Coverage.UNAVAILABLE),
                }
    if cik is None:
        cik = client.manifest_cik(ticker, snapshot_root)

    like_bank = bank_like if bank_like is not None else _is_bank_like(company)
    if used_entity_facts is not None and facts_payload is None:
        if anchors is None and subs_payload is not None:
            anchors = anchors_from_submissions(subs_payload)
        facts, concept_usage = facts_from_edgartools_entity(
            used_entity_facts, bank_like=like_bank, annual_anchors=anchors
        )
    elif facts_payload is not None:
        if transport == "live":
            synced_at = None
        facts, concept_usage = facts_from_companyfacts(
            facts_payload, bank_like=like_bank, annual_anchors=anchors, submissions=subs_payload
        )
    else:
        return {
            "status": "unavailable",
            "ticker": ticker,
            "provider": PROVIDER,
            "pipeline": PIPELINE,
            "transport": transport,
            "snapshot_synced_at": synced_at,
            "reason": f"sin companyfacts para {ticker}",
            "provenance": provenance(SOURCE, SourceKind.OFFICIAL, coverage=Coverage.UNAVAILABLE),
        }

    document = _source_document(db, company, ticker)
    _replace_own_facts(db, company, document)
    for fact in facts:
        fact.pop("_concept", None)
        db.add(
            FinancialFact(
                company_id=company.id,
                metric=fact["metric"],
                value=fact["value"],
                unit=fact["unit"],
                period=fact["period"],
                fiscal_year=fact["fiscal_year"],
                fiscal_quarter=fact["fiscal_quarter"],
                source_id=document.id,
                source_type=PROVIDER,
                is_reported=True,
                confidence=fact.get("confidence", Decimal("0.95")),
            )
        )
    drop_shadowed_facts(db, company.id, document.id, tenant_condition(db))
    fy_periods = sorted({f["period"] for f in facts if f["period"].endswith(":FY")}, reverse=True)
    fetched_at = datetime.now(UTC)
    document.metadata_ = {
        **(document.metadata_ or {}),
        "provider": PROVIDER,
        "pipeline": PIPELINE,
        "cik": cik,
        "transport": transport,
        "snapshot_synced_at": synced_at,
        "xbrl_concept_by_metric_period": concept_usage,
        "fy_periods": fy_periods,
        "last_refreshed_at": fetched_at.isoformat(),
    }
    db.commit()

    return {
        "status": "ingested",
        "ticker": ticker,
        "provider": PROVIDER,
        "pipeline": PIPELINE,
        "source_document_id": document.id,
        "facts_imported": len(facts),
        "cik": cik,
        "fy_periods": fy_periods,
        "transport": transport,
        "snapshot_synced_at": synced_at,
        "provenance": provenance(
            SOURCE,
            SourceKind.OFFICIAL,
            fetched_at=fetched_at,
            source_url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=10-K"
            if cik
            else None,
            note=f"via edgartools ({transport}"
            + (f"; snapshot synced_at {synced_at}" if synced_at else "")
            + ")",
        ),
    }


def _form4_filings_from_submissions(submissions: dict, *, cik: str, limit: int) -> list[dict]:
    recent = (submissions.get("filings") or {}).get("recent") or {}
    accessions = recent.get("accessionNumber", []) or []
    items: list[dict] = []
    cik_number = str(int(str(cik).strip())) if str(cik).strip().isdigit() else str(cik).strip().lstrip("0")

    def _col(name: str, index: int) -> Any:
        values = recent.get(name, []) or []
        return values[index] if index < len(values) else None

    for index, accession in enumerate(accessions):
        form = str(_col("form", index) or "").strip().upper()
        if form not in {"4", "4/A"}:
            continue
        primary = _col("primaryDocument", index)
        nodash = str(accession).replace("-", "")
        base = f"https://www.sec.gov/Archives/edgar/data/{cik_number}/{nodash}/"
        items.append(
            {
                "form": form,
                "accession_number": accession,
                "filing_date": _col("filingDate", index),
                "report_date": _col("reportDate", index),
                "primary_document": primary,
                "document_url": f"{base}{primary}" if primary else base,
            }
        )
        if len(items) >= limit:
            break
    return items


def refresh_form4_from_edgartools(
    ticker: str,
    *,
    force: bool = False,
    cik: str | None = None,
    limit: int = 20,
    submissions: dict | None = None,
    filing_xml: dict[str, str] | None = None,
    snapshot_root: Any | None = None,
) -> dict[str, Any]:
    """Form 4 con el shape de ``insider_service`` (sin persistir: follow-up).

    ``filing_xml`` (``{accession: xml}``) inyecta el XML en tests; sin el, lee
    el snapshot (``filings/<acc>/form4.xml`` o el primary del snapshot).
    """
    wanted = ticker.strip().upper()
    if not force and not is_enabled():
        return _disabled(wanted)
    resolved = _pad_cik(cik) or client.manifest_cik(wanted, snapshot_root)
    if not resolved and submissions is None:
        return {
            "ticker": wanted,
            "status": "unavailable",
            "reason": "not a US SEC filer",
            "signals": [],
            "transactions": [],
            "transport": "snapshot",
            "snapshot_synced_at": client.manifest_synced_at(snapshot_root),
        }
    subs = submissions if submissions is not None else client.read_submissions(resolved or "", snapshot_root)
    if subs is None:
        return {
            "ticker": wanted,
            "cik": resolved,
            "status": "unavailable",
            "reason": f"sin submissions (snapshot) para {wanted}",
            "transactions": [],
            "transport": "snapshot",
            "snapshot_synced_at": client.manifest_synced_at(snapshot_root),
        }
    filings = _form4_filings_from_submissions(subs, cik=resolved or "", limit=limit)
    transactions: list[dict] = []
    errors: list[str] = []
    for filing in filings:
        accession = str(filing["accession_number"])
        xml = (filing_xml or {}).get(accession)
        if xml is None:
            xml = client.read_filing_xml(
                accession, str(filing.get("primary_document") or "form4.xml"), snapshot_root
            )
        if xml is None:
            xml = client.read_filing_xml(accession, "form4.xml", snapshot_root)
        if xml is None:
            errors.append(f"{accession}: sin XML en snapshot")
            continue
        try:
            parsed = ownership_transactions(xml)
            filing_tx = enrich_like_insider_service(
                list(parsed.get("transactions", [])), {**filing, "ticker": wanted}
            )
            transactions.extend(filing_tx)
        except Exception as exc:  # noqa: BLE001 - best-effort por filing
            errors.append(f"{accession}: {type(exc).__name__}: {redact_secrets(str(exc))[:200]}")
    synced_at = client.manifest_synced_at(snapshot_root)
    return {
        "ticker": wanted,
        "cik": resolved,
        "status": "ok" if not errors else ("partial" if transactions else "degraded"),
        "filings_scanned": len(filings),
        "transactions": transactions,
        "filing_errors": errors,
        "transport": "snapshot",
        "snapshot_synced_at": synced_at,
        "fetched_at": datetime.now(UTC).isoformat(),
        "provenance": provenance(
            SOURCE,
            SourceKind.OFFICIAL,
            source_url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={resolved}&type=4",
            coverage=Coverage.PARTIAL if errors else Coverage.OK,
            note="Form 4 via edgartools (snapshot); codigo P = mercado abierto o privado.",
        ),
    }


def _thirteenf_filings_from_submissions(submissions: dict, *, limit: int) -> list[dict]:
    recent = (submissions.get("filings") or {}).get("recent") or {}
    accessions = recent.get("accessionNumber", []) or []
    items: list[dict] = []

    def _col(name: str, index: int) -> Any:
        values = recent.get(name, []) or []
        return values[index] if index < len(values) else None

    for index, accession in enumerate(accessions):
        form = str(_col("form", index) or "").strip().upper()
        if form not in {"13F-HR", "13F-HR/A"}:
            continue
        items.append(
            {
                "accession_number": accession,
                "form": form,
                "is_amendment": form.endswith("/A"),
                "report_date": _col("reportDate", index),
                "filing_date": _col("filingDate", index),
                "primary_document": _col("primaryDocument", index),
            }
        )
        if len(items) >= limit:
            break
    return items


def refresh_13f_from_edgartools(
    cik: str,
    *,
    force: bool = False,
    limit: int = 8,
    submissions: dict | None = None,
    infotable_xml: dict[str, str] | None = None,
    snapshot_root: Any | None = None,
) -> dict[str, Any]:
    """13F con el shape de ``manager_holding_ingestion_service`` (sin persistir).

    Devuelve ``holdings`` con las claves de ``parse_information_table`` para
    el ultimo report_date del snapshot (+ ``limitations`` y proveniencia).
    """
    from app.services.manager_holding_ingestion_service import LIMITATIONS

    padded = str(cik).strip().zfill(10)
    if not force and not is_enabled():
        out = _disabled(padded)
        out["cik"] = padded
        return out
    subs = submissions if submissions is not None else client.read_submissions(padded, snapshot_root)
    if subs is None:
        return {
            "cik": padded,
            "status": "unavailable",
            "reason": f"sin submissions (snapshot) para {padded}",
            "holdings": [],
            "transport": "snapshot",
            "snapshot_synced_at": client.manifest_synced_at(snapshot_root),
            "provenance": provenance(SOURCE, SourceKind.OFFICIAL, coverage=Coverage.UNAVAILABLE),
        }
    filings = _thirteenf_filings_from_submissions(subs, limit=limit)
    if not filings:
        return {
            "cik": padded,
            "status": "unavailable",
            "reason": "no 13F-HR filings found",
            "holdings": [],
            "transport": "snapshot",
            "snapshot_synced_at": client.manifest_synced_at(snapshot_root),
            "provenance": provenance(SOURCE, SourceKind.OFFICIAL, coverage=Coverage.UNAVAILABLE),
        }
    latest_report = filings[0]["report_date"]
    group = [f for f in filings if f["report_date"] == latest_report]
    holdings: list[dict] = []
    errors: list[dict] = []
    for filing in group:
        accession = str(filing["accession_number"])
        xml = (infotable_xml or {}).get(accession)
        if xml is None:
            xml = client.read_filing_xml(accession, "infotable.xml", snapshot_root)
        if xml is None:
            errors.append({"accession": accession, "error": "information_table_not_found"})
            continue
        try:
            holdings.extend(infotable_holdings(xml))
        except Exception as exc:  # noqa: BLE001 - cobertura parcial, se sigue
            errors.append({"accession": accession, "error": redact_secrets(f"{type(exc).__name__}: {exc}")})
    synced_at = client.manifest_synced_at(snapshot_root)
    return {
        "cik": padded,
        "status": "ok",
        "report_date": latest_report,
        "filings": [
            {"accession_number": f["accession_number"], "form": f["form"], "is_amendment": f["is_amendment"]}
            for f in group
        ],
        "holdings": holdings,
        "errors": errors,
        "limitations": list(LIMITATIONS),
        "transport": "snapshot",
        "snapshot_synced_at": synced_at,
        "provenance": provenance(
            SOURCE,
            SourceKind.OFFICIAL,
            fetched_at=datetime.now(UTC),
            coverage=Coverage.PARTIAL if errors else Coverage.OK,
        ),
    }
