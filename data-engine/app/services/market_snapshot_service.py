"""Dated macro context, no vendor requests in GET handlers."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import MarketObservation, MarketRegimeSnapshot
from app.services.market_observation_service import FRED_SERIES
from app.services.market_regime_quant import observed_hmm, sp500_top_ten_concentration

MODEL_VERSION = "macro-context-hmm-v2"


def build_snapshot(db: Session, as_of: date, generated_at: datetime | None = None) -> MarketRegimeSnapshot:
    generated_at = generated_at or datetime.now(UTC)
    if generated_at.tzinfo is None or as_of > generated_at.astimezone(UTC).date():
        raise ValueError("Fecha inválida")
    metrics: dict = {}
    evidence_ids: list[int] = []
    for key, (_, _, max_age) in FRED_SERIES.items():
        point = db.scalar(
            select(MarketObservation)
            .where(
                MarketObservation.metric_key == key,
                MarketObservation.observation_date <= as_of,
                MarketObservation.status == "observed",
                MarketObservation.fetched_at <= generated_at,
            )
            .order_by(desc(MarketObservation.observation_date), desc(MarketObservation.fetched_at), desc(MarketObservation.id))
            .limit(1)
        )
        if not point or point.observation_date < as_of - timedelta(days=max_age):
            continue
        metrics[key] = {
            "value": float(point.value),
            "date": point.observation_date.isoformat(),
            "unit": point.unit,
            "source": point.source,
            "source_url": point.source_url,
            "fetched_at": point.fetched_at.isoformat(),
            "evidence_id": point.id,
        }
        evidence_ids.append(point.id)
    ten, two = metrics.get("treasury_10y_us"), metrics.get("treasury_2y_us")
    if ten and two and ten["date"] == two["date"]:
        metrics["yield_curve_10y_2y_us"] = {
            "value": round(ten["value"] - two["value"], 4),
            "date": ten["date"],
            "unit": "puntos porcentuales",
            "input_evidence_ids": [ten["evidence_id"], two["evidence_id"]],
            "method": "DGS10 menos DGS2 en la misma fecha",
        }
    coverage = (
        "unavailable" if not evidence_ids else "ok" if len(evidence_ids) == len(FRED_SERIES) else "partial"
    )
    hmm = observed_hmm(db, as_of, generated_at)
    metrics["hmm"] = {key: value for key, value in hmm.items() if key != "probabilities"}
    probabilities = hmm.get("probabilities", {})
    # Concentracion top-10 del S&P 500: lee el snapshot en disco del factsheet
    # (S&P DJI) con su propio vintage. Si no hay snapshot, o si su `as_of` es
    # posterior a la fecha del snapshot, responde "sin datos" con motivo: no hay
    # ningun camino que rellene el hueco con el presente ni con un cero. Sin
    # trafico a proveedor: el GET de /market/regime solo lee lo persistido aqui.
    metrics["top_ten_sp500"] = sp500_top_ten_concentration(as_of)
    # La beta de cartera NO va en el snapshot global: el builder corre con
    # sesión sin tenant y portfolio_beta mezclaría posiciones de todos los
    # tenants (fuga). Marcador honesto hasta la beta tenant-scoped.
    metrics["portfolio_beta"] = {
        "status": "no_disponible",
        "reason": "La beta de tu cartera aún no está disponible; el snapshot macro es global y no mezcla carteras.",
    }
    checksum = hashlib.sha256(json.dumps({"metrics": metrics, "probabilities": probabilities}, sort_keys=True).encode()).hexdigest()
    previous = db.scalar(
        select(MarketRegimeSnapshot).where(
            MarketRegimeSnapshot.snapshot_date == as_of,
            MarketRegimeSnapshot.model_version == MODEL_VERSION,
            MarketRegimeSnapshot.input_hash == checksum,
        )
    )
    if previous:
        return previous
    snapshot = MarketRegimeSnapshot(
        snapshot_date=as_of,
        model_version=MODEL_VERSION,
        input_hash=checksum,
        metrics=metrics,
        probabilities=probabilities,
        evidence_ids=evidence_ids,
        coverage=coverage,
        generated_at=generated_at,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def latest_snapshot(db: Session) -> dict:
    snapshot = db.scalar(
        select(MarketRegimeSnapshot)
        .order_by(
            desc(MarketRegimeSnapshot.snapshot_date),
            desc(MarketRegimeSnapshot.id),
        )
        .limit(1)
    )
    if not snapshot:
        return {"status": "sin datos", "coverage": "unavailable", "metrics": {}, "probabilities": {}}
    age = (datetime.now(UTC).date() - snapshot.snapshot_date).days
    return {
        "status": "sin datos"
        if snapshot.coverage == "unavailable"
        else "obsoleto"
        if age > 4
        else "disponible",
        # «stale» solo sustituye a una cobertura real: un snapshot que nunca
        # tuvo datos (coverage="unavailable") sigue declarando "unavailable"
        # por viejo que sea; "stale" afirmaria que hubo datos que envejecieron.
        "coverage": "stale" if age > 4 and snapshot.coverage != "unavailable" else snapshot.coverage,
        "date": snapshot.snapshot_date.isoformat(),
        "generated_at": snapshot.generated_at.isoformat(),
        "model_version": snapshot.model_version,
        "metrics": snapshot.metrics,
        "probabilities": snapshot.probabilities,
        # Bloqueo multi-tenant (#561): la beta no se expone hasta el aislamiento
        # por tenant. El snapshot macro es global y no mezcla carteras; la
        # maquinaria de betas por posición queda en regime_quant sin exponer.
        "portfolio_beta": snapshot.metrics.get(
            "portfolio_beta",
            {"status": "no_disponible", "reason": "La beta de tu cartera aún no está disponible."},
        ),
        "note": "Probabilidades filtradas sin etiqueta económica; métricas faltantes indican sin datos.",
    }
