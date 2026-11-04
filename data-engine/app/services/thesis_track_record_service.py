"""«Nuestro acierto»: puntúa los valores razonables de GerarAI contra el precio real.

Cada ``ThesisVersion`` congela un valor razonable (``base_value``; si falta,
``expected_value``) en la fecha en que se creó. Este servicio mira qué hizo
después el precio a 6 y 12 meses y lo guarda en ``thesis_realized_returns``
(una fila por tenant y versión):

- precio al emitir: primer cierre en o después del día de la versión (como
  mucho ``ENTRY_WINDOW_DAYS`` días después);
- precio al horizonte: primer cierre en o después de la fecha de vencimiento
  (como mucho ``HORIZON_WINDOW_DAYS`` días después);
- error con signo ``(valor razonable - precio real) / precio real`` (positivo
  = fuimos optimistas) y su valor absoluto;
- acierto de dirección: el valor razonable decía «sube» (o «baja») respecto
  al precio al emitir y el precio hizo eso;
- «tocó»: el precio alcanzó el valor razonable en algún cierre (o máximo /
  mínimo del día) dentro de la ventana.

SIN LOOKAHEAD: un horizonte solo se evalúa cuando su fecha ya pasó y con
precios hasta el cierre del horizonte; nada posterior entra en el cálculo
(``score_version`` recorta la serie y los tests lo comprueban). El valor
razonable es el congelado en la versión: recalcularlo hoy metería datos
posteriores en la foto del pasado.

Idempotente: si el resultado no cambia no se escribe; si cambia (llegó un
precio que faltaba) se guarda la revisión anterior en ``revisions``.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenancy import session_tenant_id, tenant_filters
from app.models import Company, MarketPrice, ThesisVersion
from app.models.thesis_realized_return import ThesisRealizedReturn

HORIZONS: tuple[tuple[str, int], ...] = (("6M", 6), ("12M", 12))
ENTRY_WINDOW_DAYS = 5
HORIZON_WINDOW_DAYS = 7
# Si el precio guardado en la versión y el cierre del mismo día difieren más
# que esto, las unidades no casan (GBp frente a GBP, ADR, split): no se puntúa.
UNIT_MISMATCH_TOLERANCE = 0.25
# Mínimo de muestras vencidas por horizonte para elegir el «mejor horizonte».
MIN_SAMPLES_BEST_HORIZON = 3
OUTCOME_DEFINITION_VERSION = "fv_v1"
EXCLUDED_STATUSES = frozenset({"insufficient_data", "draft_failed_audit"})
MAX_REVISIONS = 10


@dataclass(frozen=True)
class PriceRow:
    day: date
    close: float
    high: float | None = None
    low: float | None = None
    adj_close: float | None = None


def add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last))


def _f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out > 0 else None


def _round(value: float | None, digits: int = 6) -> float | None:
    return None if value is None else round(value, digits)


def fair_value_of(version: Any) -> tuple[float | None, str]:
    base = _f(getattr(version, "base_value", None))
    if base is not None:
        return base, "base_value"
    expected = _f(getattr(version, "expected_value", None))
    if expected is not None:
        return expected, "expected_value"
    return None, "absent"


def issue_day(version: Any) -> date:
    created = version.created_at
    if isinstance(created, datetime):
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        return created.astimezone(UTC).date()
    return created


def first_maturity(issue: date) -> date:
    return add_months(issue, HORIZONS[0][1])


def _first_on_or_after(prices: list[PriceRow], day: date, window_days: int) -> PriceRow | None:
    limit = day + timedelta(days=window_days)
    for row in prices:
        if row.day < day:
            continue
        return row if row.day <= limit else None
    return None


def score_version(
    *,
    issue: date,
    fair_value: float | None,
    stored_price: float | None,
    prices: list[PriceRow],
    today: date,
) -> dict[str, Any]:
    """Puntúa una versión. Función pura: no lee nada fuera de sus argumentos.

    ``prices`` puede traer cierres posteriores a cualquier horizonte; cada
    horizonte solo mira los cierres hasta su propio cierre de vencimiento.
    """
    prices = sorted((p for p in prices if p.close and p.close > 0 and p.day <= today), key=lambda p: p.day)
    result: dict[str, Any] = {
        "entry_date": None,
        "entry_price": None,
        "entry_status": "missing",
        "price_basis": "close",
        "horizons": [],
    }
    entry = _first_on_or_after(prices, issue, ENTRY_WINDOW_DAYS)
    horizons_out: list[dict[str, Any]] = []
    for label, months in HORIZONS:
        target = add_months(issue, months)
        horizons_out.append({"horizon": label, "months": months, "target_date": target.isoformat(),
                             "status": "pending"})
    result["horizons"] = horizons_out
    if fair_value is None:
        result["entry_status"] = "no_fair_value"
        for h in horizons_out:
            h["status"] = "no_fair_value"
        return result
    if entry is None:
        # Sin cierre al emitir no hay foto de partida (nunca se usa uno posterior
        # a la ventana: eso sería mirar el futuro).
        status = "pending" if today <= issue + timedelta(days=ENTRY_WINDOW_DAYS) else "no_entry_price"
        result["entry_status"] = status
        for h in horizons_out:
            h["status"] = status
        return result
    if stored_price is not None and abs(stored_price / entry.close - 1) > UNIT_MISMATCH_TOLERANCE:
        result.update(entry_date=entry.day.isoformat(), entry_price=_round(entry.close),
                      entry_status="unit_mismatch")
        for h in horizons_out:
            h["status"] = "unit_mismatch"
        return result

    result.update(entry_date=entry.day.isoformat(), entry_price=_round(entry.close), entry_status="ok")
    for h, (label, months) in zip(horizons_out, HORIZONS, strict=True):
        target = add_months(issue, months)
        if today < target:
            h["status"] = "pending"
            continue
        end = _first_on_or_after(prices, target, HORIZON_WINDOW_DAYS)
        if end is None:
            h["status"] = "pending" if today <= target + timedelta(days=HORIZON_WINDOW_DAYS) else "no_price"
            continue
        window = [p for p in prices if entry.day <= p.day <= end.day]
        # Base ajustada (splits/dividendos) solo si los dos extremos la tienen;
        # el valor razonable se escala con el mismo factor del día de emisión.
        adjusted = entry.adj_close is not None and end.adj_close is not None
        if adjusted:
            factor = entry.adj_close / entry.close  # type: ignore[operator]
            p0, p1, fv = entry.adj_close, end.adj_close, fair_value * factor
        else:
            p0, p1, fv = entry.close, end.close, fair_value
        assert p0 is not None and p1 is not None
        touched = False
        predicted_up = fv > p0
        for p in window:
            if p.day == entry.day:
                continue
            scale = (p.adj_close / p.close) if adjusted and p.adj_close else 1.0
            hi = (p.high if p.high else p.close) * scale
            lo = (p.low if p.low else p.close) * scale
            if (predicted_up and hi >= fv) or (not predicted_up and lo <= fv):
                touched = True
                break
        direction_hit: bool | None
        if fv == p0:
            direction_hit = None
        else:
            direction_hit = (p1 > p0) == predicted_up
        signed = (fv - p1) / p1
        h.update(
            status="matured",
            price_basis="adj_close" if adjusted else "close",
            price_date=end.day.isoformat(),
            price=_round(p1),
            fair_value=_round(fv),
            entry_price=_round(p0),
            expected_return=_round(fv / p0 - 1),
            realized_return=_round(p1 / p0 - 1),
            signed_error=_round(signed),
            abs_error=_round(abs(signed)),
            direction_hit=direction_hit,
            touched=touched,
        )
    return result


def _fingerprint(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def _judgement(horizons: list[dict[str, Any]]) -> tuple[str, str, str, bool, str]:
    """(judgement_status, judgement_horizon, outcome, counts, reason)."""
    matured = [h for h in horizons if h.get("status") == "matured"]
    pending = any(h.get("status") == "pending" for h in horizons)
    if not matured:
        if pending:
            return "pending", HORIZONS[0][0], "too_early", False, "horizonte sin vencer"
        blocked = sorted({str(h.get("status")) for h in horizons})
        return "excluded", HORIZONS[0][0], "inconclusive", False, ",".join(blocked)
    last = matured[-1]
    status = "partial" if pending else "complete"
    hit = last.get("direction_hit")
    if hit is None:
        return status, last["horizon"], "inconclusive", False, "valor razonable igual al precio"
    return status, last["horizon"], "hit" if hit else "miss", True, "dirección" + (" acertada" if hit else " fallada")


def _load_prices(db: Session, company_id: int, start: date, end: date) -> list[PriceRow]:
    rows = db.execute(
        select(MarketPrice.date, MarketPrice.close, MarketPrice.high, MarketPrice.low, MarketPrice.adj_close)
        .where(MarketPrice.company_id == company_id, MarketPrice.date >= start, MarketPrice.date <= end)
        .order_by(MarketPrice.date)
    ).all()
    out: list[PriceRow] = []
    for day, close, high, low, adj in rows:
        c = _f(close)
        if c is None:
            continue
        out.append(PriceRow(day=day, close=c, high=_f(high), low=_f(low), adj_close=_f(adj)))
    return out


def _eligible_versions(db: Session) -> list[ThesisVersion]:
    stmt = (
        select(ThesisVersion)
        .where(ThesisVersion.status.not_in(EXCLUDED_STATUSES), *tenant_filters(db, ThesisVersion))
        .order_by(ThesisVersion.company_id, ThesisVersion.created_at, ThesisVersion.id)
    )
    return [v for v in db.scalars(stmt).all() if fair_value_of(v)[0] is not None]


def refresh_track_record(db: Session, *, today: date | None = None) -> dict[str, Any]:
    """Rellena/actualiza las filas del tenant de la sesión. Idempotente."""
    today = today or datetime.now(UTC).date()
    versions = _eligible_versions(db)
    existing = {
        row.thesis_version_id: row
        for row in db.scalars(
            select(ThesisRealizedReturn).where(*tenant_filters(db, ThesisRealizedReturn))
        ).all()
    }
    by_company: dict[int, list[ThesisVersion]] = defaultdict(list)
    for v in versions:
        row = existing.get(v.id)
        if row is not None and row.judgement_status in {"complete", "excluded"}:
            # Cerrada: ningún horizonte puede cambiar ya.
            continue
        by_company[v.company_id].append(v)
    tickers = dict(db.execute(select(Company.id, Company.ticker).where(Company.id.in_(list(by_company)))).all()) if by_company else {}
    created = updated = unchanged = 0
    now = datetime.now(UTC)
    tenant_id = session_tenant_id(db)
    for company_id, items in by_company.items():
        start = min(issue_day(v) for v in items)
        end = max(add_months(issue_day(v), HORIZONS[-1][1]) for v in items) + timedelta(days=HORIZON_WINDOW_DAYS)
        prices = _load_prices(db, company_id, start, min(end, today))
        for v in items:
            fv, fv_source = fair_value_of(v)
            issue = issue_day(v)
            scored = score_version(issue=issue, fair_value=fv, stored_price=_f(v.current_price),
                                   prices=prices, today=today)
            horizons = scored["horizons"]
            judgement, j_horizon, outcome, counts, reason = _judgement(horizons)
            payload = {"entry": [scored["entry_date"], scored["entry_price"], scored["entry_status"]],
                       "horizons": horizons, "outcome": outcome}
            fp = _fingerprint(payload)
            row = existing.get(v.id)
            if row is not None and row.price_fingerprint == fp:
                unchanged += 1
                continue
            entry_price = scored["entry_price"]
            values = dict(
                company_id=company_id,
                ticker=(tickers.get(company_id) or "")[:20],
                thesis_version=v.version,
                thesis_published_at=v.created_at,
                thesis_status=v.status,
                entry_date=date.fromisoformat(scored["entry_date"]) if scored["entry_date"] else None,
                entry_price=Decimal(str(entry_price)) if entry_price is not None else None,
                entry_price_status=scored["entry_status"],
                entry_price_rule=f"primer cierre en o tras el día de la tesis (≤{ENTRY_WINDOW_DAYS} d)",
                fair_value_at_entry=Decimal(str(round(fv, 6))) if fv is not None else None,
                fair_value_source=fv_source,
                upside_at_entry=(Decimal(str(round(fv / entry_price - 1, 6)))
                                 if fv is not None and entry_price else None),
                holding_horizon_days=(add_months(issue, HORIZONS[-1][1]) - issue).days,
                holding_horizon_source="fv_6m_12m",
                judgement_horizon=j_horizon,
                judgement_status=judgement,
                horizons=horizons,
                outcome=outcome,
                outcome_definition_version=OUTCOME_DEFINITION_VERSION,
                verdict_reason=reason,
                counts_toward_hit_rate=counts,
                price_fingerprint=fp,
                computed_at=now,
            )
            if row is None:
                row = ThesisRealizedReturn(thesis_version_id=v.id, tenant_id=tenant_id, revisions=[],
                                           metadata_={}, revision=1, **values)
                db.add(row)
                existing[v.id] = row
                created += 1
            else:
                previous = {"revision": row.revision, "horizons": row.horizons, "outcome": row.outcome,
                            "computed_at": row.computed_at.isoformat() if row.computed_at else None}
                row.revisions = ([*(row.revisions or []), previous])[-MAX_REVISIONS:]
                row.revision = (row.revision or 1) + 1
                for key, value in values.items():
                    setattr(row, key, value)
                updated += 1
    db.commit()
    return {"status": "ok", "versions": len(versions), "created": created, "updated": updated,
            "unchanged": unchanged, "today": today.isoformat()}


# --------------------------------------------------------------------------- lectura


def _summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    hits = [s for s in samples if s.get("direction_hit") is not None]
    n_hits = sum(1 for s in hits if s["direction_hit"])
    abs_errors = [s["abs_error"] for s in samples if s.get("abs_error") is not None]
    signed = [s["signed_error"] for s in samples if s.get("signed_error") is not None]
    return {
        "samples": len(samples),
        "hits": n_hits,
        "hit_rate": round(n_hits / len(hits), 4) if hits else None,
        "median_abs_error": round(statistics.median(abs_errors), 4) if abs_errors else None,
        "median_signed_error": round(statistics.median(signed), 4) if signed else None,
        "touched_rate": (round(sum(1 for s in samples if s.get("touched")) / len(samples), 4)
                         if samples else None),
    }


def best_horizon(summaries: dict[str, dict[str, Any]]) -> tuple[str | None, str]:
    ranked = [
        (label, s) for label, s in summaries.items()
        if s["samples"] >= MIN_SAMPLES_BEST_HORIZON and s["hit_rate"] is not None
    ]
    if not ranked:
        return None, "insufficient_samples"
    ranked.sort(key=lambda item: (-item[1]["hit_rate"],
                                  item[1]["median_abs_error"] if item[1]["median_abs_error"] is not None else 9e9))
    return ranked[0][0], "hit_rate"


def _daily_samples(rows: list[ThesisRealizedReturn]) -> dict[str, list[dict[str, Any]]]:
    """Una muestra por empresa y día (la última versión del día): regenerar la
    tesis cinco veces el mismo día no cuenta como cinco aciertos."""
    latest: dict[tuple[int, date], ThesisRealizedReturn] = {}
    for row in rows:
        published = row.thesis_published_at
        if published.tzinfo is None:
            published = published.replace(tzinfo=UTC)
        key = (row.company_id, published.astimezone(UTC).date())
        current = latest.get(key)
        if current is None or (row.thesis_published_at, row.thesis_version_id) > (
            current.thesis_published_at, current.thesis_version_id
        ):
            latest[key] = row
    out: dict[str, list[dict[str, Any]]] = {label: [] for label, _ in HORIZONS}
    for row in latest.values():
        for h in row.horizons or []:
            if isinstance(h, dict) and h.get("status") == "matured" and h.get("horizon") in out:
                out[h["horizon"]].append(h)
    return out


def _first_maturity_date(db: Session, company_id: int | None = None) -> date | None:
    stmt = select(ThesisVersion).where(
        ThesisVersion.status.not_in(EXCLUDED_STATUSES), *tenant_filters(db, ThesisVersion)
    )
    if company_id is not None:
        stmt = stmt.where(ThesisVersion.company_id == company_id)
    first: date | None = None
    for v in db.scalars(stmt.order_by(ThesisVersion.created_at)).all():
        if fair_value_of(v)[0] is not None:
            first = first_maturity(issue_day(v))
            break
    return first


def _payload(summaries: dict[str, dict[str, Any]], first: date | None, has_versions: bool) -> dict[str, Any]:
    matured = sum(s["samples"] for s in summaries.values())
    best, reason = best_horizon(summaries)
    if matured:
        status = "ready"
    elif has_versions:
        status = "pending"
    else:
        status = "no_data"
    return {
        "status": status,
        "first_maturity_date": first.isoformat() if first else None,
        "horizons": summaries,
        "best_horizon": best,
        "best_horizon_reason": reason,
        "min_samples_best_horizon": MIN_SAMPLES_BEST_HORIZON,
    }


def company_track_record(db: Session, company: Company) -> dict[str, Any]:
    rows = list(db.scalars(
        select(ThesisRealizedReturn).where(
            ThesisRealizedReturn.company_id == company.id, *tenant_filters(db, ThesisRealizedReturn)
        )
    ).all())
    samples = _daily_samples(rows)
    summaries = {label: _summary(samples[label]) for label, _ in HORIZONS}
    first = _first_maturity_date(db, company.id)
    payload = _payload(summaries, first, has_versions=first is not None)
    payload["ticker"] = company.ticker
    payload["versions_tracked"] = len(rows)
    payload["last_computed_at"] = max((r.computed_at for r in rows), default=None)
    return payload


def tenant_track_record(db: Session) -> dict[str, Any]:
    rows = list(db.scalars(select(ThesisRealizedReturn).where(*tenant_filters(db, ThesisRealizedReturn))).all())
    samples = _daily_samples(rows)
    summaries = {label: _summary(samples[label]) for label, _ in HORIZONS}
    first = _first_maturity_date(db)
    payload = _payload(summaries, first, has_versions=first is not None)
    per_company: dict[int, list[ThesisRealizedReturn]] = defaultdict(list)
    for row in rows:
        per_company[row.company_id].append(row)
    tickers = []
    for company_rows in per_company.values():
        s = _daily_samples(company_rows)
        sums = {label: _summary(s[label]) for label, _ in HORIZONS}
        if not any(v["samples"] for v in sums.values()):
            continue
        best, reason = best_horizon(sums)
        tickers.append({"ticker": company_rows[0].ticker, "horizons": sums, "best_horizon": best,
                        "best_horizon_reason": reason})
    tickers.sort(key=lambda t: t["ticker"])
    payload["tickers"] = tickers
    payload["versions_tracked"] = len(rows)
    payload["last_computed_at"] = max((r.computed_at for r in rows), default=None)
    return payload
