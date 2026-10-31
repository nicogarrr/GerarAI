"""Per-manager 13F holdings ingestion from SEC EDGAR (tier_1 official, free).

Decision value: what reviewed institutional managers hold, add and trim is
real evidence for theses and watchlists. Boundaries (parent-approved):
- only managers in REVIEWED_MANAGERS (exact CIK <-> official EDGAR name,
  reviewed one by one); unreviewed CIKs are refused, never guessed;
- holdings are stored as filed: CUSIP + issuer name, tickers never inferred;
- amendments (13F-HR/A) are separate immutable accessions; prior filings are
  never rewritten;
- 13F is quarterly, up to a 45-day lag, long-only US-listed - consumers must
  show these limits; per-company ownership is out of scope until an
  authoritative CUSIP mapping exists.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import redact_secrets

logger = logging.getLogger(__name__)
from app.core.tenancy import tenant_filters
from app.models import FundManager, ManagerHolding
from app.services.connectors import form13f
from app.services.provenance import Coverage, SourceKind, provenance

SOURCE = "sec_edgar_13f"

# Reviewed one by one before adding: exact CIK <-> official EDGAR name.
# Small by design; the owner extends this table explicitly. Verified against EDGAR
# submissions (13F-HR for the 2026-06-30 period) on 2026-10-06.
REVIEWED_MANAGERS: dict[str, str] = {
    "0001067983": "Berkshire Hathaway Inc",
    "0002026053": "PERSHING SQUARE INC.",
    "0001709323": "Himalaya Capital Management LLC",
    "0000783412": "DAILY JOURNAL CORP",
    "0001549575": "Dalal Street, LLC",
    "0001112520": "AKRE CAPITAL MANAGEMENT LLC",
    "0001061768": "BAUPOST GROUP LLC/MA",
    "0001536411": "Duquesne Family Office LLC",
    "0001656456": "Appaloosa LP",
    "0001040273": "Third Point LLC",
    "0001056831": "FAIRHOLME CAPITAL MANAGEMENT LLC",
    "0000732905": "Tweedy, Browne Co LLC",
    "0000813917": "HARRIS ASSOCIATES L P",
    "0001345471": "TRIAN FUND MANAGEMENT, L.P.",
    "0001061165": "LONE PINE CAPITAL LLC",
    "0000807985": "SOUTHEASTERN ASSET MANAGEMENT INC/TN/",
    "0001167483": "TIGER GLOBAL MANAGEMENT LLC",
    "0001034524": "POLEN CAPITAL MANAGEMENT LLC",
    "0001569205": "Fundsmith LLP",
    "0001096343": "MARKEL GROUP INC.",
    "0001166559": "GATES FOUNDATION TRUST",
    "0001317588": "ABRAMS BISON INVESTMENTS, LLC",
    "0001376879": "AKO CAPITAL LLP",
    "0001063296": "ATLANTIC INVESTMENT MANAGEMENT, INC.",
}

LIMITATIONS = [
    "Quarterly cadence with up to a 45-day reporting lag",
    "Long-only US-listed positions; no shorts, no non-13F securities",
    "Holdings as filed: CUSIP + issuer name; tickers never inferred",
    "Amendments are separate immutable filings",
]


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


SCALE_JUMP_RATIO = Decimal(100)


def detect_scale_jump(period_totals: dict[str, Decimal]) -> dict | None:
    """Total de dos trimestres del mismo gestor que difiere >100x: casi seguro un error de escala.

    Un gestor no multiplica ni divide su cartera por 100 de un trimestre al siguiente; si pasa,
    la escala inferida de uno de los dos filings es sospechosa. Solo avisa, no corrige.
    """
    usable = sorted((d, t) for d, t in period_totals.items() if t and t > 0)
    for (d0, t0), (d1, t1) in zip(usable, usable[1:]):
        ratio = max(t0, t1) / min(t0, t1)
        if ratio > SCALE_JUMP_RATIO:
            return {"periods": [d0, d1], "totals": [str(t0), str(t1)], "ratio": str(round(ratio, 1))}
    return None


def _verify_totals(
    summary: dict | None, raw_rows: list[dict], merged: list[dict], factor: int = 1
) -> dict:
    """Compara lo guardado con lo que el propio filing declara (tableValueTotal/EntryTotal)."""
    stored = sum((_decimal(r.get("value_usd_thousands")) or Decimal(0) for r in merged), Decimal(0))
    if summary is None or summary["table_value_total"] is None:
        return {"status": "unverified", "stored_value_total": str(stored)}
    declared = summary["table_value_total"] * factor
    entries = summary["table_entry_total"]
    ok = stored == declared and (entries is None or entries == len(raw_rows))
    return {
        "status": "ok" if ok else "mismatch",
        "stored_value_total": str(stored),
        "declared_value_total": str(declared),
        "raw_rows": len(raw_rows),
        "declared_entry_total": entries,
    }


# Auditoria A: el estado de verificacion del filing servido se guarda en
# ``FundManager.coverage`` (String(20), sin migracion) con dos valores mas que
# el enum ``Coverage``: "mismatch" (los totales no cuadran con el resumen del
# propio 13F) y "unverified" (resumen ilegible, sin contraste). Hacia fuera
# ambos son cobertura "partial", asi que toda pantalla que ya mostraba «Datos
# parciales» sigue haciendolo; el motivo exacto viaja en ``verification``.
VERIFICATION_COVERAGES = frozenset({"mismatch", "unverified"})



# --- Splits entre dos trimestres 13F ------------------------------------------
# Un split 10:1 entre dos 13F multiplica por 10 las acciones de TODOS los
# tenedores sin que nadie compre nada (NVDA 10:1, 2024-06-10: Q1 2024 → Q2 2024).
# Comparar acciones a pelo marcaba a cada gestor como «increased» y la lista
# «lo que mas compran» se llenaba de compras inventadas. El propio filing trae
# la evidencia: un tenedor que no opera tiene EXACTAMENTE ratio × acciones y el
# precio implicito (valor / acciones) cae en la misma proporcion.
SPLIT_MIN_RATIO = Fraction(3, 2)
SPLIT_MAX_NUMERATOR = 50
SPLIT_MAX_DENOMINATOR = 4
SPLIT_PRICE_TOLERANCE = 1.5
_DOLLAR_VALUE_FROM = date(2022, 12, 31)


def _value_dollars(row: Any) -> Decimal | None:
    value = getattr(row, "value_usd_thousands", None)
    report = getattr(row, "report_date", None)
    if value is None or report is None:
        return None
    return Decimal(value) if report >= _DOLLAR_VALUE_FROM else Decimal(value) * 1000


def implied_split_ratio(now: Any, before: Any) -> Fraction | None:
    """Ratio de split (acciones despues / antes) que explica el cambio, o None.

    Exige las dos evidencias: acciones en proporcion EXACTA y sencilla (2:1,
    3:2, 10:1, 1:10...) y precio implicito del filing movido en esa misma
    proporcion (tolerancia x1,5 para el movimiento del mercado en el
    trimestre). Un gestor que de verdad duplica su posicion conserva el precio
    implicito y no pasa la segunda prueba.
    """
    if (getattr(now, "share_type", None) or "SH").upper() != "SH":
        return None
    if (getattr(before, "share_type", None) or "SH").upper() != "SH":
        return None
    now_shares, before_shares = now.shares, before.shares
    if not now_shares or not before_shares or now_shares <= 0 or before_shares <= 0:
        return None
    ratio = Fraction(Decimal(now_shares)) / Fraction(Decimal(before_shares))
    magnitude = ratio if ratio > 1 else 1 / ratio
    if (
        magnitude < SPLIT_MIN_RATIO
        or magnitude.numerator > SPLIT_MAX_NUMERATOR
        or magnitude.denominator > SPLIT_MAX_DENOMINATOR
    ):
        return None
    now_value, before_value = _value_dollars(now), _value_dollars(before)
    if not now_value or not before_value or now_value <= 0 or before_value <= 0:
        return None
    price_ratio = float((before_value / Decimal(before_shares)) / (now_value / Decimal(now_shares)))
    if not float(ratio) / SPLIT_PRICE_TOLERANCE <= price_ratio <= float(ratio) * SPLIT_PRICE_TOLERANCE:
        return None
    return ratio


def share_change_label(now: Any, before: Any) -> str:
    """increased / decreased / unchanged por acciones, neutralizando un split."""
    # nosemgrep: gerarai-money-none-to-zero -- variacion de acciones 13F: posicion ausente en un trimestre = 0 acciones por definicion del filing
    now_shares = Decimal(now.shares or 0)
    # nosemgrep: gerarai-money-none-to-zero -- variacion de acciones 13F: posicion ausente en un trimestre = 0 acciones por definicion del filing
    before_shares = Decimal(before.shares or 0)
    if implied_split_ratio(now, before) is not None:
        return "unchanged"
    if now_shares > before_shares:
        return "increased"
    if now_shares < before_shares:
        return "decreased"
    return "unchanged"


def public_coverage(raw: str | None) -> str | None:
    """Cobertura publica (enum Coverage) a partir del valor guardado."""
    return Coverage.PARTIAL.value if raw in VERIFICATION_COVERAGES else raw


def verification_status(raw: str | None) -> str | None:
    """verified | mismatch | unverified | partial | unavailable (None sin datos)."""
    if raw is None:
        return None
    if raw in VERIFICATION_COVERAGES:
        return raw
    return "verified" if raw == Coverage.OK.value else raw


def _latest_accession(rows: list) -> str:
    """Accession vigente de un periodo: gana la enmienda con filing_date mas
    reciente (desempate por accession). Las filas de TODOS los filings quedan
    guardadas inmutables; esta regla solo decide cual se sirve."""
    return max(
        {row.accession_number for row in rows},
        key=lambda acc: (
            max(
                (r.filing_date or date.min)
                for r in rows
                if r.accession_number == acc
            ),
            acc,
        ),
    )



def _snapshot_holdings_payload(fallback: dict) -> dict:
    """Payload de lectura para holdings servidos desde el snapshot edgartools.

    Mismo contrato de claves que la via persistida; lo que el snapshot no
    tiene queda en None. status="snapshot" (nunca "ok"): el snapshot no
    contrasta totales contra el filing, asi que no es "verified".
    """
    holdings = []
    for h in fallback.get("holdings") or []:
        value = h.get("value_usd_thousands")
        shares = h.get("ssh_prnamt")
        holdings.append(
            {
                "accession_number": None,
                "is_amendment": False,
                "name_of_issuer": h.get("name_of_issuer"),
                "name_of_issuer_filed": h.get("name_of_issuer"),
                "title_of_class": h.get("title_of_class"),
                "cusip": h.get("cusip"),
                "value_usd_thousands": float(value) if value is not None else None,
                "shares": float(shares) if shares is not None else None,
                "share_type": h.get("ssh_prnamt_type"),
                "put_call": h.get("put_call") or None,
                "investment_discretion": h.get("investment_discretion"),
                "filing_url": None,
            }
        )
    return {
        "cik": fallback.get("cik"),
        "manager": REVIEWED_MANAGERS.get(str(fallback.get("cik") or "").zfill(10)),
        "status": "snapshot",
        "verification": "snapshot_unverified",
        "report_date": fallback.get("report_date"),
        "coverage": "snapshot",
        "holdings": holdings,
        "errors": fallback.get("errors") or [],
        "limitations": fallback.get("limitations") or list(LIMITATIONS),
        "transport": fallback.get("transport"),
        "snapshot_synced_at": fallback.get("snapshot_synced_at"),
        "provenance": fallback.get("provenance"),
    }


class ManagerHoldingIngestionService:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client

    def sync_manager(self, db: Session, *, cik: str) -> dict[str, Any]:
        cik = str(cik).strip().zfill(10)
        if cik not in REVIEWED_MANAGERS:
            return {
                "cik": cik,
                "status": "unreviewed_manager",
                "provenance": provenance(
                    SOURCE, SourceKind.OFFICIAL, coverage=Coverage.UNAVAILABLE,
                    note="CIK not in the reviewed manager table",
                ),
            }

        manager = db.scalar(select(FundManager).where(FundManager.cik == cik))
        if manager is None:
            manager = FundManager(cik=cik, name=REVIEWED_MANAGERS[cik])
            db.add(manager)
            db.flush()

        try:
            filings = form13f.recent_13f_filings(cik, client=self.client)
        except Exception as exc:  # noqa: BLE001 - honest unavailable, never break
            # Detalle completo al log (redactado); la respuesta solo lleva un
            # codigo estable: texto de excepcion al cliente = py/stack-trace-exposure.
            logger.warning(
                "13F sync %s: no se pudieron listar filings (%s: %s)",
                cik, type(exc).__name__, redact_secrets(str(exc))[:300],
            )
            manager.coverage = Coverage.UNAVAILABLE.value
            manager.synced_at = datetime.now(UTC)
            db.add(manager)
            db.commit()
            return {
                "cik": cik,
                "manager": manager.name,
                "status": "unavailable",
                "reason": "fuente_no_disponible",
                "provenance": provenance(SOURCE, SourceKind.OFFICIAL, coverage=Coverage.UNAVAILABLE),
            }

        if not filings:
            manager.coverage = Coverage.UNAVAILABLE.value
            manager.synced_at = datetime.now(UTC)
            db.add(manager)
            db.commit()
            return {
                "cik": cik,
                "manager": manager.name,
                "status": "unavailable",
                "reason": "no 13F-HR filings found",
                "provenance": provenance(SOURCE, SourceKind.OFFICIAL, coverage=Coverage.UNAVAILABLE),
            }

        # Latest two report periods (base filings + their amendments), so a
        # quarter-over-quarter comparison is computable from stored rows.
        report_dates = list(dict.fromkeys(f["report_date"] for f in filings))[:2]
        latest_report = report_dates[0]
        group = [f for f in filings if f["report_date"] in report_dates]
        ingested = 0
        errors: list[dict] = []
        verification: list[dict] = []
        skipped_amendments: list[dict] = []
        fetched_at = datetime.now(UTC)
        period_totals: dict[str, Decimal] = {}

        for filing in group:
            accession = filing["accession_number"]
            try:
                url = form13f.information_table_url(
                    cik, accession, filing["primary_document"], client=self.client
                )
                if url is None:
                    errors.append({"accession": accession, "error": "information_table_not_found"})
                    continue
                rows = form13f.fetch_information_table(url, client=self.client)
            except Exception as exc:  # noqa: BLE001 - partial coverage, keep going
                logger.warning(
                    "13F infotable %s/%s: %s: %s",
                    cik, accession, type(exc).__name__, redact_secrets(str(exc))[:300],
                )
                errors.append({"accession": accession, "error": "filing_no_legible"})
                continue
            summary = form13f.fetch_primary_summary(cik, accession, client=self.client)
            if filing["is_amendment"] and summary is None:
                # Sin el resumen no sabemos si la enmienda es completa (RESTATEMENT) o
                # parcial (NEW HOLDINGS): no se ingiere como cartera del periodo.
                skipped_amendments.append({"accession": accession, "reason": "summary_unreadable"})
                continue
            if filing["is_amendment"] and summary is not None and (
                (summary["amendment_type"] or "").upper() != "RESTATEMENT"
            ):
                # Una enmienda "NEW HOLDINGS" solo trae parte de la cartera: usarla
                # como cartera del periodo inventaria compras y cierres.
                skipped_amendments.append(
                    {
                        "accession": accession,
                        "amendment_type": summary["amendment_type"],
                        "reason": "not_restatement",
                    }
                )
                continue
            existing = {
                (row.cusip, row.title_of_class, row.put_call)
                for row in db.scalars(
                    select(ManagerHolding).where(
                        ManagerHolding.manager_id == manager.id,
                        ManagerHolding.accession_number == accession,
                    )
                )
            }
            merged = form13f.aggregate_rows(rows)
            scale_info = form13f.infer_value_scale(merged, filing["report_date"])
            merged = form13f.apply_value_scale(merged, scale_info["scale"])
            factor = 1000 if scale_info["scale"] == form13f.SCALE_THOUSANDS else 1
            check = _verify_totals(summary, rows, merged, factor)
            if not filing["is_amendment"]:
                period_totals[str(filing["report_date"])] = sum(
                    (_decimal(r.get("value_usd_thousands")) or Decimal(0) for r in merged), Decimal(0)
                )
            verification.append({"accession": accession, **check, "value_scale": scale_info})
            if check["status"] == "mismatch":
                errors.append({"accession": accession, "error": "totals_mismatch"})
            for row in merged:
                cusip = (row.get("cusip") or "").strip()
                title = (row.get("title_of_class") or "").strip()
                put_call = (row.get("put_call") or "").strip()
                if (cusip, title, put_call) in existing:
                    continue
                db.add(
                    ManagerHolding(
                        manager_id=manager.id,
                        accession_number=accession,
                        report_date=_date(filing["report_date"]),
                        filing_date=_date(filing["filing_date"]),
                        is_amendment=filing["is_amendment"],
                        name_of_issuer=(row.get("name_of_issuer") or "").strip(),
                        title_of_class=title,
                        cusip=cusip,
                        value_usd_thousands=_decimal(row.get("value_usd_thousands")),
                        value_scale=scale_info["scale"],
                        shares=_decimal(row.get("ssh_prnamt")),
                        share_type=(row.get("ssh_prnamt_type") or "SH").strip(),
                        put_call=put_call,
                        investment_discretion=(row.get("investment_discretion") or "").strip(),
                        voting_sole=_decimal(row.get("voting_sole")),
                        voting_shared=_decimal(row.get("voting_shared")),
                        voting_none=_decimal(row.get("voting_none")),
                        filing_url=url,
                        source=SOURCE,
                        fetched_at=fetched_at,
                    )
                )
                ingested += 1

        scale_jump = detect_scale_jump(period_totals)
        if scale_jump is not None:
            errors.append({"error": "scale_jump_between_quarters", **scale_jump})

        # last_report_date apunta al periodo MAS RECIENTE con filas guardadas.
        # Si el 13F nuevo no se pudo descargar (503, timeout), apuntar a el
        # dejaba la ficha en «ok» con 0 posiciones; se sigue sirviendo el
        # ultimo periodo almacenado y la cobertura queda «partial».
        db.flush()
        stored_latest = db.scalar(
            select(func.max(ManagerHolding.report_date)).where(
                ManagerHolding.manager_id == manager.id
            )
        )
        if stored_latest is not None:
            manager.last_report_date = stored_latest
        stored_coverage = self._stored_coverage(
            db, manager, stored_latest, verification, errors
        )
        manager.coverage = stored_coverage
        manager.synced_at = fetched_at
        db.add(manager)
        db.commit()

        coverage = Coverage(public_coverage(stored_coverage))
        return {
            "cik": cik,
            "manager": manager.name,
            "status": "ok",
            "report_date": latest_report,
            "report_window": report_dates,
            "filings": [
                {
                    "accession_number": f["accession_number"],
                    "form": f["form"],
                    "is_amendment": f["is_amendment"],
                }
                for f in group
            ],
            "ingested_rows": ingested,
            "verification": verification,
            "verification_status": verification_status(stored_coverage),
            "skipped_amendments": skipped_amendments,
            "errors": errors,
            "limitations": LIMITATIONS,
            "provenance": provenance(
                SOURCE, SourceKind.OFFICIAL, fetched_at=fetched_at, coverage=coverage
            ),
        }

    def sync_all(self, db: Session) -> dict[str, Any]:
        return {
            "results": [self.sync_manager(db, cik=cik) for cik in REVIEWED_MANAGERS],
            "limitations": LIMITATIONS,
        }

    def change_labels_for_cusip(self, db: Session, *, cik: str, cusip: str) -> list[str]:
        """Cambios trimestrales de UN cusip para un gestor, sin cargar su cartera entera.

        Misma regla que ``changes()``: dos ultimos periodos guardados, ultimo
        accession por periodo (las enmiendas sustituyen al filing base),
        comparacion por acciones. ``changes()`` lee TODAS las posiciones de
        ambos trimestres (cientos o miles de filas por gestor); la ficha lo
        llamaba una vez por gestor revisado (~32) solo para quedarse con un
        cusip, y para valores muy cubiertos (AAPL) la suma superaba el
        presupuesto de lectura de la ficha y el panel 13F fallaba al cargar.
        Aqui solo se cargan las filas de ese cusip dentro del accession
        vigente de cada periodo (elegido sobre todos los filings del
        gestor, como en ``changes()``). Devuelve las etiquetas por
        fila (puede haber varias clases del mismo cusip); [] si no aplica
        (sin gestor, sin dos periodos o sin ese cusip).
        """
        cik = str(cik).strip().zfill(10)
        manager = db.scalar(select(FundManager).where(FundManager.cik == cik))
        if manager is None:
            return []
        report_dates = [
            row[0]
            for row in db.execute(
                select(ManagerHolding.report_date)
                .where(
                    ManagerHolding.manager_id == manager.id,
                    *tenant_filters(db, ManagerHolding),
                )
                .group_by(ManagerHolding.report_date)
                .order_by(ManagerHolding.report_date.desc())
                .limit(2)
            )
            if row[0] is not None
        ]
        if len(report_dates) < 2:
            return []
        latest_date, previous_date = report_dates[0], report_dates[1]

        def period_view(period: date) -> dict:
            # Misma regla que changes(): el accession vigente del periodo se
            # elige sobre TODOS los filings del gestor (la enmienda mas
            # reciente sustituye al filing base). Elegirlo solo entre los
            # filings que contienen el cusip serviria uno viejo y resucitaria
            # una posicion que la enmienda vigente ya retiro. El agregado
            # (accession, filing_date) es ligero: un gestor tiene pocos
            # filings por periodo, no hace falta cargar sus filas.
            filings = db.execute(
                select(
                    ManagerHolding.accession_number,
                    func.max(ManagerHolding.filing_date),
                )
                .where(
                    ManagerHolding.manager_id == manager.id,
                    ManagerHolding.report_date == period,
                    *tenant_filters(db, ManagerHolding),
                )
                .group_by(ManagerHolding.accession_number)
            ).all()
            if not filings:
                return {}
            accession = max(filings, key=lambda pair: (pair[1] or date.min, pair[0]))[0]
            rows = db.scalars(
                select(ManagerHolding).where(
                    ManagerHolding.manager_id == manager.id,
                    ManagerHolding.report_date == period,
                    ManagerHolding.accession_number == accession,
                    ManagerHolding.cusip == cusip,
                    *tenant_filters(db, ManagerHolding),
                )
            ).all()
            return {
                (row.cusip, row.title_of_class, row.put_call): row
                for row in rows
            }

        latest = period_view(latest_date)
        previous = period_view(previous_date)
        labels: list[str] = []
        for key in sorted(set(latest) | set(previous)):
            if key[2]:
                # Puts/calls no cuentan: el resumen 13F es de posiciones largas
                # (mismo filtro que aplicaba el llamador sobre changes()).
                continue
            now, before = latest.get(key), previous.get(key)
            if now is not None and before is None:
                labels.append("new")
            elif now is None and before is not None:
                labels.append("closed")
            else:
                assert now is not None and before is not None
                labels.append(share_change_label(now, before))
        return labels

    def changes(self, db: Session, *, cik: str) -> dict[str, Any]:
        """Quarter-over-quarter position changes for a reviewed manager.

        Compares the latest accession per report period (amendments supersede
        base filings in this view; every filing stays stored immutably).
        Keys are (cusip, title_of_class, put_call) - tickers never inferred.
        """
        cik = str(cik).strip().zfill(10)
        manager = db.scalar(select(FundManager).where(FundManager.cik == cik))
        if manager is None:
            return {
                "cik": cik,
                "status": "unavailable",
                "changes": [],
                "provenance": provenance(SOURCE, SourceKind.OFFICIAL, coverage=Coverage.UNAVAILABLE),
            }
        report_dates = [
            row[0]
            for row in db.execute(
                select(ManagerHolding.report_date)
                .where(
                    ManagerHolding.manager_id == manager.id,
                    *tenant_filters(db, ManagerHolding),
                )
                .group_by(ManagerHolding.report_date)
                .order_by(ManagerHolding.report_date.desc())
            )
            if row[0] is not None
        ]
        if len(report_dates) < 2:
            return {
                "cik": cik,
                "manager": manager.name,
                "status": "insufficient_history",
                "detail": "need two stored 13F report periods to compare; re-sync after the next quarter",
                "changes": [],
                "provenance": provenance(SOURCE, SourceKind.INTERNAL, coverage=Coverage.UNAVAILABLE),
            }
        latest_date, previous_date = report_dates[0], report_dates[1]

        def period_rows(period: date) -> tuple[str, dict]:
            rows = db.scalars(
                select(ManagerHolding).where(
                    ManagerHolding.manager_id == manager.id,
                    ManagerHolding.report_date == period,
                )
            ).all()
            # Latest accession wins (amendments supersede base filings).
            accession = _latest_accession(rows)
            view = {
                (row.cusip, row.title_of_class, row.put_call): row
                for row in rows
                if row.accession_number == accession
            }
            return accession, view

        latest_accession, latest = period_rows(latest_date)
        previous_accession, previous = period_rows(previous_date)

        changes: list[dict] = []
        for key in sorted(set(latest) | set(previous)):
            now, before = latest.get(key), previous.get(key)
            if now is not None and before is None:
                change = "new"
            elif now is None and before is not None:
                change = "closed"
            else:
                assert now is not None and before is not None
                change = share_change_label(now, before)
            subject = now or before
            assert subject is not None
            changes.append(
                {
                    "change": change,
                    "name_of_issuer": subject.name_of_issuer,
                    "title_of_class": subject.title_of_class,
                    "cusip": subject.cusip,
                    "put_call": subject.put_call or None,
                    "shares_latest": float(now.shares) if now and now.shares is not None else None,
                    "shares_previous": (
                        float(before.shares) if before and before.shares is not None else None
                    ),
                    "value_usd_thousands_latest": (
                        float(now.value_usd_thousands)
                        if now and now.value_usd_thousands is not None
                        else None
                    ),
                    "value_usd_thousands_previous": (
                        float(before.value_usd_thousands)
                        if before and before.value_usd_thousands is not None
                        else None
                    ),
                }
            )

        return {
            "cik": cik,
            "manager": manager.name,
            "status": "ok",
            "latest_report": latest_date.isoformat(),
            "previous_report": previous_date.isoformat(),
            "compared_accessions": {
                "latest": latest_accession,
                "previous": previous_accession,
                "rule": "último filing por periodo; las enmiendas sustituyen a los filings base en esta vista y cada filing se conserva almacenado de forma inmutable",
            },
            "changes": changes,
            "limitations": LIMITATIONS,
            "provenance": provenance(SOURCE, SourceKind.INTERNAL, coverage=Coverage.OK),
        }

    @staticmethod
    def _stored_coverage(
        db: Session,
        manager: FundManager,
        stored_latest: date | None,
        verification: list[dict],
        errors: list[dict],
    ) -> str:
        """Cobertura a guardar segun la verificacion del filing que se servira.

        El filing servido es la accession vigente del ultimo periodo guardado
        (la misma regla que ``latest_holdings``). Si sus totales no cuadran o
        no se pudieron contrastar, se guarda ese motivo exacto; cualquier otro
        fallo (descarga, otro trimestre, salto de escala) es "partial".
        """
        by_accession = {item["accession"]: item["status"] for item in verification}
        served_status: str | None = None
        if stored_latest is not None:
            served_rows = list(
                db.scalars(
                    select(ManagerHolding).where(
                        ManagerHolding.manager_id == manager.id,
                        ManagerHolding.report_date == stored_latest,
                    )
                )
            )
            if served_rows:
                served_status = by_accession.get(_latest_accession(served_rows))
        if served_status in VERIFICATION_COVERAGES:
            return str(served_status)
        if errors:
            return Coverage.PARTIAL.value
        if any(item["status"] != "ok" for item in verification):
            return Coverage.PARTIAL.value
        return Coverage.OK.value

    def latest_holdings(self, db: Session, *, cik: str) -> dict[str, Any]:
        cik = str(cik).strip().zfill(10)
        manager = db.scalar(select(FundManager).where(FundManager.cik == cik))
        if manager is None or manager.last_report_date is None:
            # Sin sync en vivo todavia (o la via principal fallo): servir el
            # snapshot edgartools si existe, marcado como tal y sin persistir.
            # Import perezoso: edgartools_ingestion_service importa LIMITATIONS
            # de este modulo.
            from app.services.edgartools_ingestion_service import (
                refresh_13f_from_edgartools,
            )

            fallback = refresh_13f_from_edgartools(cik)
            if fallback.get("status") == "ok":
                return _snapshot_holdings_payload(fallback)
            return {
                "cik": cik,
                "status": "unavailable",
                "holdings": [],
                "provenance": provenance(SOURCE, SourceKind.OFFICIAL, coverage=Coverage.UNAVAILABLE),
            }
        rows = list(
            db.scalars(
                select(ManagerHolding)
                .where(
                    ManagerHolding.manager_id == manager.id,
                    ManagerHolding.report_date == manager.last_report_date,
                )
                .order_by(ManagerHolding.value_usd_thousands.desc().nulls_last())
            ).all()
        )
        # Una enmienda 13F-HR/A no suma posiciones: sustituye al filing base.
        # Servir todas las filas del periodo duplicaba cada posicion (y su valor)
        # siempre que existiera enmienda; solo se sirve el accession vigente.
        if rows:
            accession = _latest_accession(rows)
            rows = [row for row in rows if row.accession_number == accession]
        from app.services.instrument_reference import names_by_cusip

        display_names = names_by_cusip(db, [row.cusip for row in rows])
        verification = verification_status(manager.coverage)
        return {
            "cik": cik,
            "manager": manager.name,
            # Auditoria A: "ok" solo con totales contrastados contra el propio
            # 13F; si no, el motivo exacto (mismatch, unverified, partial).
            "status": "ok" if verification == "verified" else verification,
            "verification": verification,
            "report_date": manager.last_report_date.isoformat(),
            "coverage": public_coverage(manager.coverage),
            "holdings": [
                {
                    "accession_number": row.accession_number,
                    "is_amendment": row.is_amendment,
                    "name_of_issuer": display_names.get(row.cusip) or row.name_of_issuer,
                    "name_of_issuer_filed": row.name_of_issuer,
                    "title_of_class": row.title_of_class,
                    "cusip": row.cusip,
                    "value_usd_thousands": (
                        float(row.value_usd_thousands)
                        if row.value_usd_thousands is not None
                        else None
                    ),
                    "shares": float(row.shares) if row.shares is not None else None,
                    "share_type": row.share_type,
                    "put_call": row.put_call or None,
                    "investment_discretion": row.investment_discretion,
                    "filing_url": row.filing_url,
                }
                for row in rows
            ],
            "limitations": LIMITATIONS,
            "provenance": provenance(
                SOURCE,
                SourceKind.OFFICIAL,
                fetched_at=manager.synced_at,
                coverage=Coverage(public_coverage(manager.coverage)),
            ),
        }
