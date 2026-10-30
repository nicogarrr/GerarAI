"""Tabla fija de inversores para el modulo "Inversores" (13F oficial, EUR 0).

- Solo los inversores de esta tabla se muestran; el CIK, si existe, debe estar
  en REVIEWED_MANAGERS (CIK exacto <-> nombre oficial EDGAR, revisado uno a uno).
- Quien no presenta 13F tiene ``cik=None``: la cartera se muestra como
  "Sin datos: no presenta 13F", nunca se inventa ni se infiere.
- Daily Journal se rotula "Daily Journal": no es la cartera personal de Munger.
- Pershing Square: las posiciones de 2026 van bajo el CIK nuevo 0002026053; el
  antiguo 0001336528 presento un 13F-NT (aviso, sin posiciones) y no se da de alta.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models import FundManager, ManagerHolding
from app.services.investor_profiles import public_profile
from app.services.manager_holding_ingestion_service import (
    LIMITATIONS,
    REVIEWED_MANAGERS,
    SOURCE,
    ManagerHoldingIngestionService,
    _latest_accession,
    public_coverage,
    verification_status,
)
from app.services.provenance import Coverage, SourceKind, provenance

NO_13F_NOTE = "Sin datos: no presenta 13F"


@dataclass(frozen=True)
class Investor:
    slug: str
    name: str
    firm: str
    cik: str | None
    kind: str = "person"  # person | firm | company


INVESTORS: tuple[Investor, ...] = (
    Investor("buffett", "Warren Buffett", "Berkshire Hathaway", "0001067983"),
    Investor("ackman", "Bill Ackman", "Pershing Square", "0002026053"),
    Investor("terry-smith", "Terry Smith", "Fundsmith", "0001569205"),
    Investor("li-lu", "Li Lu", "Himalaya Capital", "0001709323"),
    Investor("daily-journal", "Daily Journal", "Daily Journal Corp", "0000783412", "company"),
    Investor("pabrai", "Mohnish Pabrai", "Dalal Street", "0001549575"),
    Investor("akre", "Chuck Akre", "Akre Capital Management", "0001112520"),
    Investor("klarman", "Seth Klarman", "Baupost Group", "0001061768"),
    Investor("druckenmiller", "Stanley Druckenmiller", "Duquesne Family Office", "0001536411"),
    Investor("tepper", "David Tepper", "Appaloosa", "0001656456"),
    Investor("loeb", "Daniel Loeb", "Third Point", "0001040273"),
    Investor("berkowitz", "Bruce Berkowitz", "Fairholme Capital", "0001056831"),
    Investor("tweedy-browne", "Tweedy, Browne", "Tweedy, Browne", "0000732905", "firm"),
    Investor("oakmark", "Harris Associates (Oakmark)", "Harris Associates", "0000813917", "firm"),
    Investor("peltz", "Nelson Peltz", "Trian Fund Management", "0001345471"),
    Investor("lone-pine", "Lone Pine Capital", "Lone Pine Capital", "0001061165", "firm"),
    Investor("southeastern", "Southeastern Asset Management", "Southeastern", "0000807985", "firm"),
    Investor("tiger-global", "Tiger Global", "Tiger Global Management", "0001167483", "firm"),
    Investor("polen", "Polen Capital", "Polen Capital", "0001034524", "firm"),
    Investor("markel", "Markel", "Markel Group", "0001096343", "company"),
    Investor("gates-foundation", "Gates Foundation Trust", "Gates Foundation Trust", "0001166559", "firm"),
    Investor("abrams-bison", "Abrams Bison", "Abrams Bison Investments", "0001317588", "firm"),
    Investor("ako", "AKO Capital", "AKO Capital", "0001376879", "firm"),
    Investor("roepers", "Alex Roepers", "Atlantic Investment Management", "0001063296"),
    # Sin 13F: cartas, videos y conceptos; cartera "Sin datos".
    Investor("mark-leonard", "Mark Leonard", "Constellation Software", None),
    Investor("bezos", "Jeff Bezos", "Amazon", None),
    Investor("quintana", "Emerito Quintana", "Numantia", None),
    Investor("munger", "Charlie Munger", "Berkshire Hathaway", None),
    Investor("nick-sleep", "Nick Sleep", "Nomad Investment Partnership", None),
    Investor("lynch", "Peter Lynch", "Fidelity Magellan", None),
    Investor("trump", "Donald Trump", "Participaciones personales documentadas", None),
    Investor("barron-trump", "Barron Trump", "World Liberty Financial", None),
)

_BY_SLUG = {i.slug: i for i in INVESTORS}


def get_investor(slug: str) -> Investor | None:
    return _BY_SLUG.get(slug)


def _latest_view(db: Session, manager: FundManager) -> list[ManagerHolding]:
    """Filas del ultimo periodo y de su ultima accession (las enmiendas sustituyen
    al filing base en esta vista; todos los filings siguen almacenados)."""
    if manager.last_report_date is None:
        return []
    rows = list(
        db.scalars(
            select(ManagerHolding).where(
                ManagerHolding.manager_id == manager.id,
                ManagerHolding.report_date == manager.last_report_date,
            )
        )
    )
    if not rows:
        return []
    accession = max(
        {r.accession_number for r in rows},
        key=lambda acc: (
            max((r.filing_date or date.min) for r in rows if r.accession_number == acc),
            acc,
        ),
    )
    return [r for r in rows if r.accession_number == accession]


def _total(rows: list[ManagerHolding]) -> float | None:
    values = [r.value_usd_thousands for r in rows if r.value_usd_thousands is not None]
    if not values:
        return None
    return float(sum(values, Decimal(0)))


def _entry(inv: Investor) -> dict[str, Any]:
    return {
        "slug": inv.slug,
        "name": inv.name,
        "firm": inv.firm,
        "kind": inv.kind,
        "cik": inv.cik,
        "has_13f": inv.cik is not None,
        "has_public_profile": inv.cik is None and public_profile(inv.slug) is not None,
    }


def _manager(db: Session, inv: Investor) -> FundManager | None:
    if inv.cik is None or inv.cik not in REVIEWED_MANAGERS:
        return None
    return db.scalar(select(FundManager).where(FundManager.cik == inv.cik))


def _reviewed_managers(db: Session) -> dict[str, FundManager]:
    """Todos los gestores revisados del tenant en UNA consulta (antes, una por
    inversor de la tabla)."""
    ciks = [inv.cik for inv in INVESTORS if inv.cik is not None and inv.cik in REVIEWED_MANAGERS]
    if not ciks:
        return {}
    return {m.cik: m for m in db.scalars(select(FundManager).where(FundManager.cik.in_(ciks)))}


def _latest_summaries(
    db: Session, managers: list[FundManager]
) -> dict[int, tuple[int, float | None]]:
    """(posiciones, valor en miles USD) de la vista vigente de cada gestor, en
    UNA consulta de columnas. Misma regla que _latest_view + _total: ultimo
    periodo, accession vigente (_latest_accession), suma de los valores que hay."""
    by_id = {m.id: m for m in managers if m.last_report_date is not None}
    if not by_id:
        return {}
    grouped: dict[int, list[Any]] = defaultdict(list)
    for row in db.execute(
        select(
            ManagerHolding.manager_id,
            ManagerHolding.report_date,
            ManagerHolding.accession_number,
            ManagerHolding.filing_date,
            ManagerHolding.value_usd_thousands,
        ).where(
            ManagerHolding.manager_id.in_(list(by_id)),
            *tenant_filters(db, ManagerHolding),
        )
        .join(FundManager, FundManager.id == ManagerHolding.manager_id)
        .where(ManagerHolding.report_date == FundManager.last_report_date)
    ):
        grouped[row.manager_id].append(row)
    summaries: dict[int, tuple[int, float | None]] = {}
    for manager_id, rows in grouped.items():
        accession = _latest_accession(rows)
        view = [r for r in rows if r.accession_number == accession]
        values = [r.value_usd_thousands for r in view if r.value_usd_thousands is not None]
        summaries[manager_id] = (len(view), float(sum(values, Decimal(0))) if values else None)
    return summaries


def list_investors(db: Session) -> dict[str, Any]:
    from app.services.investor_autosync import maybe_autosync_holdings

    maybe_autosync_holdings(db)
    managers = _reviewed_managers(db)
    summaries = _latest_summaries(db, list(managers.values()))
    out: list[dict[str, Any]] = []
    for inv in INVESTORS:
        item = _entry(inv)
        manager = managers.get(inv.cik) if inv.cik in REVIEWED_MANAGERS else None
        positions, value = summaries.get(manager.id, (0, None)) if manager else (0, None)
        item.update(
            {
                "coverage": public_coverage(manager.coverage) if manager and positions else None,
                "verification": verification_status(manager.coverage)
                if manager and positions
                else None,
                "official_name": REVIEWED_MANAGERS.get(inv.cik or ""),
                "report_date": manager.last_report_date.isoformat()
                if manager and manager.last_report_date
                else None,
                "positions": positions or None,
                "value_usd_thousands": value,
                "note": None if inv.cik else NO_13F_NOTE,
            }
        )
        out.append(item)
    return {
        "investors": out,
        "limitations": LIMITATIONS,
        "provenance": provenance(SOURCE, SourceKind.INTERNAL, coverage=Coverage.OK),
    }


def investor_detail(db: Session, slug: str) -> dict[str, Any] | None:
    inv = get_investor(slug)
    if inv is None:
        return None
    detail = _entry(inv)
    detail["note"] = None if inv.cik else NO_13F_NOTE
    detail["public_profile"] = None if inv.cik else public_profile(slug)
    manager = _manager(db, inv)
    rows = _latest_view(db, manager) if manager else []
    rows.sort(key=lambda r: r.value_usd_thousands or Decimal(0), reverse=True)
    total = _total(rows)
    from app.services.instrument_reference import names_by_cusip

    display_names = names_by_cusip(db, [r.cusip for r in rows])
    detail.update(
        {
            "coverage": public_coverage(manager.coverage) if manager and rows else None,
                "verification": verification_status(manager.coverage) if manager and rows else None,
            "official_name": REVIEWED_MANAGERS.get(inv.cik or ""),
            "report_date": manager.last_report_date.isoformat()
            if manager and manager.last_report_date
            else None,
            "positions": len(rows) if rows else None,
            "value_usd_thousands": total,
            "holdings": [
                {
                    "name_of_issuer": display_names.get(r.cusip) or r.name_of_issuer,
                    "name_of_issuer_filed": r.name_of_issuer,
                    "title_of_class": r.title_of_class,
                    "cusip": r.cusip,
                    "shares": float(r.shares) if r.shares is not None else None,
                    "value_usd_thousands": float(r.value_usd_thousands)
                    if r.value_usd_thousands is not None
                    else None,
                    "weight_pct": round(float(r.value_usd_thousands) / total * 100, 2)
                    if total and r.value_usd_thousands is not None
                    else None,
                    "put_call": r.put_call or None,
                    "filing_url": r.filing_url,
                }
                for r in rows
            ],
            "limitations": LIMITATIONS,
            "provenance": provenance(
                SOURCE,
                SourceKind.OFFICIAL if rows else SourceKind.INTERNAL,
                coverage=Coverage.OK if rows else Coverage.UNAVAILABLE,
            ),
        }
    )
    return detail


# El <value> del 13F va en dolares desde los informes de 2022-12-31 y en miles antes.
_DOLLARS_FROM = date(2022, 12, 31)
MOST_BOUGHT_TOP = 30


def _value_usd(raw: Decimal | float | None, report_date: str | None) -> float | None:
    if raw is None or not report_date:
        return None
    return float(raw) if date.fromisoformat(report_date) >= _DOLLARS_FROM else float(raw) * 1000


def most_bought(db: Session) -> dict[str, Any]:
    """Acciones que mas gestores revisados compraron (nueva posicion o mas acciones).

    Solo posiciones largas en acciones (las filas put/call se ignoran: son
    nocionales de opciones). Se agrupa por CUSIP; nunca se infiere ticker.
    Cada gestor se compara contra su trimestre anterior.
    """
    service = ManagerHoldingIngestionService()
    issuers: dict[str, dict[str, Any]] = {}
    compared = 0
    pending = 0
    partial = 0
    periods: set[str] = set()
    managers = _reviewed_managers(db)
    for inv in INVESTORS:
        if inv.cik is None or inv.cik not in REVIEWED_MANAGERS:
            continue
        manager = managers.get(inv.cik)
        if manager is None:
            continue
        result = service.changes(db, cik=inv.cik)
        if result.get("status") != "ok":
            pending += 1
            continue
        compared += 1
        if public_coverage(manager.coverage) == "partial":
            partial += 1
        periods.add(result["latest_report"])
        for row in result["changes"]:
            if row["put_call"]:
                continue
            entry = issuers.setdefault(
                row["cusip"],
                {
                    "name_of_issuer": row["name_of_issuer"],
                    "cusip": row["cusip"],
                    "buyers": [],
                    "sellers": 0,
                    "value_usd": 0.0,
                },
            )
            if row["change"] in ("new", "increased"):
                # Un gestor puede tener varias clases del mismo CUSIP: cuenta una vez.
                same = next((b for b in entry["buyers"] if b["slug"] == inv.slug), None)
                if same is None:
                    entry["buyers"].append({"slug": inv.slug, "name": inv.name, "change": row["change"], "report_date": result["latest_report"]})
                elif row["change"] == "new":
                    same["change"] = "new"
                value = _value_usd(row["value_usd_thousands_latest"], result["latest_report"])
                # nosemgrep: gerarai-money-none-to-zero -- agregado informativo de filings/flujos (ranking/listado): una fila sin cifra no suma; no es un importe del usuario
                entry["value_usd"] += value or 0.0
            elif row["change"] in ("closed", "decreased"):
                entry["sellers"] += 1
    ranked = [e for e in issuers.values() if e["buyers"]]
    ranked.sort(key=lambda e: (-len(e["buyers"]), -e["value_usd"], e["name_of_issuer"]))
    from app.services.instrument_reference import names_by_cusip

    display_names = names_by_cusip(db, [e["cusip"] for e in ranked[:MOST_BOUGHT_TOP]])
    items = [
        {
            "name_of_issuer": display_names.get(e["cusip"]) or e["name_of_issuer"],
            "name_of_issuer_filed": e["name_of_issuer"],
            "cusip": e["cusip"],
            "buyers_count": len(e["buyers"]),
            "new_count": sum(1 for b in e["buyers"] if b["change"] == "new"),
            "sellers_count": e["sellers"],
            "value_usd": e["value_usd"] or None,
            "buyers": e["buyers"],
        }
        for e in ranked[:MOST_BOUGHT_TOP]
    ]
    return {
        "status": "ok" if compared else "sin_datos",
        "managers_compared": compared,
        "managers_without_history": pending,
        "managers_partial": partial,
        "report_dates": sorted(periods),
        "items": items,
        "limitations": LIMITATIONS,
        "provenance": provenance(
            SOURCE,
            SourceKind.OFFICIAL if compared else SourceKind.INTERNAL,
            coverage=Coverage.OK if compared else Coverage.UNAVAILABLE,
        ),
    }
