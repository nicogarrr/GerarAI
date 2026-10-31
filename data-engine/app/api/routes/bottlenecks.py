"""Persisted, tenant-scoped supply constraints. GET never ingests or calls AI."""
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import (
    BottleneckDiscovery,
    BottleneckSignal,
    Company,
    InsiderTransaction,
    Position,
    WatchItem,
)
from app.services.bottleneck_discovery_service import NO_DATA, distinct_sources, resolve_evidence
from app.services.bottleneck_service import MIN_SOURCES as DETECTION_MIN_SOURCES
from app.services.bottleneck_service import THEMES
from app.services.insider_service import _parse_date as _parse_insider_date

router = APIRouter()


class DiscoveryEvidenceOut(BaseModel):
    id: str
    title: str | None
    url: str | None
    status: Literal["verificada", "N/D"]


class BottleneckSignalOut(BaseModel):
    theme: str
    evidence_ids: list[str]
    evidence: list[DiscoveryEvidenceOut] = []
    first_seen: datetime | None
    last_seen: datetime | None
    n_sources: int
    status: Literal["N/D", "detectado"]


class BottlenecksOut(BaseModel):
    signals: list[BottleneckSignalOut]
    # Umbral vigente de "detectado": la UI etiqueta «n de min_sources fuentes
    # independientes» con el numero real, nunca hardcodeado.
    min_sources: int = DETECTION_MIN_SOURCES
    method: str = "Extracción determinista de documentos y titulares almacenados"
    limitation: str = "Se requieren al menos dos autores o editores independientes; no implica una recomendación de inversión"


@router.get("", response_model=BottlenecksOut, summary="Listar señales de cuellos de botella")
def list_bottlenecks(db: Session = Depends(get_db)) -> BottlenecksOut:
    tenant = db.info.get("tenant_id")
    rows = {} if not isinstance(tenant, int) else {
        row.theme: row for row in db.scalars(select(BottleneckSignal).where(
            BottleneckSignal.tenant_id == tenant
        ))
    }
    resolved = resolve_evidence(db, [ident for row in rows.values() for ident in row.evidence_ids or []])
    signals = []
    for theme in THEMES:
        row = rows.get(theme)
        signals.append(BottleneckSignalOut(
            theme=theme,
            evidence_ids=row.evidence_ids if row else [],
            evidence=[DiscoveryEvidenceOut(
                id=item.id,
                title=item.title,
                url=item.url,
                status="verificada" if item.url else NO_DATA,
            # Fuentes realmente distintas: varios chunks de un mismo filing cuentan una vez.
            ) for item in distinct_sources(
                resolved[ident] for ident in (row.evidence_ids or []) if ident in resolved
            )] if row else [],
            first_seen=row.first_seen if row else None,
            last_seen=row.last_seen if row else None,
            n_sources=row.n_sources if row else 0,
            status="detectado" if row and row.n_sources >= DETECTION_MIN_SOURCES else "N/D",
        ))
    return BottlenecksOut(signals=signals)


class DiscoveryOut(BaseModel):
    id: int
    theme: str
    ticker: str
    label: Literal["INFERIDO"]
    reasoning: str
    evidence: list[DiscoveryEvidenceOut]
    model: str
    created_at: datetime
    # Contexto vivo del tema: un candidato guardado persiste aunque el tema
    # caiga despues bajo el umbral de deteccion; la UI lo etiqueta.
    theme_detected: bool
    theme_last_seen: datetime | None
    # Conexion con lo que el tenant ya tiene: posicion abierta o en seguimiento.
    in_portfolio: bool
    in_watchlist: bool
    # True solo si hay transaccion insider (Form 4) del ticker en los ultimos
    # 90 dias; sin datos no se muestra nada (ausencia != ausencia de actividad).
    recent_insider_activity: bool


class DiscoveriesOut(BaseModel):
    items: list[DiscoveryOut]
    total: int
    limit: int
    offset: int
    has_more: bool
    note: str = (
        "Candidatos INFERIDOS por un modelo a partir de evidencias almacenadas; son hipótesis, "
        "no hechos ni recomendaciones. Las URLs proceden de la fuente guardada, nunca del modelo"
    )


@router.get("/discoveries", response_model=DiscoveriesOut, summary="Listar candidatos inferidos por tema")
def list_discoveries(
    db: Session = Depends(get_db),
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DiscoveriesOut:
    """Solo lectura sobre lo persistido: no ingiere ni llama a ningun modelo."""
    tenant = db.info.get("tenant_id")
    if not isinstance(tenant, int):
        return DiscoveriesOut(items=[], total=0, limit=limit, offset=offset, has_more=False)
    scope = BottleneckDiscovery.tenant_id == tenant
    total = int(db.scalar(select(func.count(BottleneckDiscovery.id)).where(scope)) or 0)
    rows = db.scalars(select(BottleneckDiscovery).where(scope).order_by(
        BottleneckDiscovery.created_at.desc(), BottleneckDiscovery.id.desc()
    ).limit(limit).offset(offset)).all()
    resolved = resolve_evidence(db, [i for row in rows for i in row.evidence_ids or []])
    signals = {
        signal.theme: signal
        for signal in db.scalars(select(BottleneckSignal).where(BottleneckSignal.tenant_id == tenant))
    }
    portfolio_tickers = set(db.scalars(
        select(Company.ticker).join(Position, Position.company_id == Company.id).where(
            Position.tenant_id == tenant, Position.quantity != 0
        )
    ))
    watchlist_tickers = {symbol.upper() for symbol in db.scalars(
        select(WatchItem.symbol).where(WatchItem.tenant_id == tenant)
    )}
    # tx_date es texto; se interpreta con el mismo parser que las alertas insider.
    insider_cutoff = datetime.now(UTC).date() - timedelta(days=90)
    insider_tickers: set[str] = set()
    # Prefiltro SQL SUPERSET (el DISTINCT leia la tabla entera; 372 ms
    # medidos en el barrido 2026-10-31). El parseo exacto sigue en Python:
    # - ISO ("YYYY-MM-DD", con o sin ceros): una fecha parseada >= cutoff
    #   SIEMPRE ordena lexicamente >= cutoff ISO acolchado (demostrado por
    #   componentes: el primer componente mayor empieza por digito > '0').
    # - US ("MM/DD/YYYY"): no ordena contra ISO; se acota por su año
    #   (ultimos 4 caracteres >= año del cutoff), exacto para años de 4 cifras.
    # Basura ("fecha rara") puede pasar el prefiltro: el parser la descarta.
    tx = InsiderTransaction
    for ticker, tx_date in db.execute(
        select(tx.issuer_ticker, tx.tx_date)
        .where(
            tx.tenant_id == tenant,
            tx.issuer_ticker.is_not(None),
            or_(
                tx.tx_date >= insider_cutoff.isoformat(),
                and_(
                    tx.tx_date.like("%/%"),
                    func.substr(tx.tx_date, func.length(tx.tx_date) - 3, 4)
                    >= str(insider_cutoff.year),
                ),
            ),
        )
        .distinct()
    ):
        parsed = _parse_insider_date(tx_date)
        if ticker and parsed is not None and parsed >= insider_cutoff:
            insider_tickers.add(ticker.upper())
    items = []
    for row in rows:
        # Fuentes realmente distintas: varios chunks de un mismo filing cuentan una vez.
        evidence = [
            DiscoveryEvidenceOut(
                id=item.id, title=item.title, url=item.url,
                status="verificada" if item.url else NO_DATA)
            for item in distinct_sources(
                resolved[ident] for ident in (row.evidence_ids or []) if ident in resolved
            )
        ]
        signal = signals.get(row.theme)
        items.append(DiscoveryOut(
            id=row.id, theme=row.theme, ticker=row.ticker, label="INFERIDO", reasoning=row.reasoning,
            evidence=evidence, model=row.model, created_at=row.created_at,
            theme_detected=bool(signal and signal.n_sources >= DETECTION_MIN_SOURCES),
            theme_last_seen=signal.last_seen if signal else None,

            in_portfolio=row.ticker in portfolio_tickers,
            in_watchlist=row.ticker.upper() in watchlist_tickers,
            recent_insider_activity=row.ticker.upper() in insider_tickers))
    return DiscoveriesOut(items=items, total=total, limit=limit, offset=offset,
                          has_more=offset + len(items) < total)


@router.post("/discoveries/run", status_code=202)
def run_discovery(db: Session = Depends(get_db)) -> dict:
    """Encola un barrido manual de candidatos INFERIDOS para el tenant actual.

    Sin scheduler automatico: el barrido solo arranca cuando alguien lo pide.
    La cuota diaria y las guardas de modelo gratuito las aplica
    ``bottleneck_discovery_service.discover`` dentro del worker; aqui solo se
    encola, nunca se llama al modelo desde la peticion.
    """
    from app.workers.dramatiq_app import discover_bottlenecks

    message = discover_bottlenecks.send(db.info.get("tenant_id"), db.info.get("user_id"))
    return {"status": "queued", "message_id": str(message.message_id)}
