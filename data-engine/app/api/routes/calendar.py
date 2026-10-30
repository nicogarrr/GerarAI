"""Calendario de mercado (earnings, dividendos y catalizadores de cartera)."""

import asyncio
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.services import catalyst_calendar_service as catalyst_service
from app.services.connectors import earnings_calendar as calendar_connector
from app.services.connectors import ipo_calendar as ipo_connector

router = APIRouter()
# Feed ICS publico: se monta en main.py FUERA de private_dependencies (los
# clientes de calendario no pueden firmar). Solo este GET; el resto de /feed
# sigue en `router`, autenticado.
public_router = APIRouter()


def _madrid_today(now: datetime | None = None) -> date:
    """Dia actual de Madrid. ``date.today()`` usa el reloj del contenedor (UTC):
    entre las 00:00 y las 02:00 de Madrid devolvia el dia anterior y los
    rangos por defecto empezaban ayer. Mismo criterio que /materials y el feed ICS."""
    return (now or datetime.now(ZoneInfo("Europe/Madrid"))).astimezone(ZoneInfo("Europe/Madrid")).date()


async def _empty_connector() -> dict:
    """Conector no consultado: mismo contrato que uno que respondio vacio."""
    return {"status": "ok", "events": [], "errors": []}


def _resolve_range(desde: date | None, hasta: date | None) -> tuple[date, date]:
    start = desde or _madrid_today()
    end = hasta or (start + timedelta(days=7))
    if start > end:
        raise HTTPException(status_code=400, detail="desde no puede ser posterior a hasta")
    if (end - start).days + 1 > calendar_connector.MAX_DAYS_PER_REQUEST:
        raise HTTPException(
            status_code=400,
            detail=f"rango maximo: {calendar_connector.MAX_DAYS_PER_REQUEST} dias",
        )
    return start, end


@router.get("/earnings")
async def earnings_calendar(
    desde: date | None = Query(default=None),
    hasta: date | None = Query(default=None),
) -> dict:
    """Eventos de earnings entre ``desde`` y ``hasta`` (por defecto, 7 dias).

    El conector degrada a ``status="unavailable"`` si NASDAQ no responde;
    este endpoint nunca devuelve 5xx por un fallo del proveedor.
    """
    start, end = _resolve_range(desde, hasta)
    try:
        return await calendar_connector.fetch_earnings_range(start, end)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/dividends")
async def dividends_calendar(
    desde: date | None = Query(default=None),
    hasta: date | None = Query(default=None),
) -> dict:
    """Eventos de dividendos entre ``desde`` y ``hasta`` (por defecto, 7 dias)."""
    start, end = _resolve_range(desde, hasta)
    try:
        return await calendar_connector.fetch_dividends_range(start, end)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/followed")
def followed_earnings_calendar(
    desde: date | None = Query(default=None),
    hasta: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    """Resultados de cartera + watchlist del tenant agrupados por dia (60 dias por defecto).

    Lee la tabla ``earnings_dates`` (refresco programado, fuentes Yahoo/NASDAQ):
    no llama a ningun proveedor en la peticion. ``confirmed`` es true/false/null
    segun lo diga la fuente y ``session`` solo es la franja publicada.
    """
    from app.services.earnings_dates_service import followed_calendar

    start = desde or _madrid_today()
    end = hasta or (start + timedelta(days=60))
    if start > end:
        raise HTTPException(status_code=400, detail="desde no puede ser posterior a hasta")
    if (end - start).days > 366:
        raise HTTPException(status_code=400, detail="rango maximo: 366 dias")
    return followed_calendar(db, start, end)


@router.get("/followed/materials")
async def followed_materials(db: Session = Depends(get_db)) -> dict:
    """Material oficial (SEC) de resultados ya publicados de las empresas seguidas.

    Hoy y ultimos 7 dias, solo eventos con fecha confirmada. Usa SECClient (identidad,
    ritmo y cache ya configurados); un fallo de la SEC devuelve ``no_disponible`` por
    evento y nunca rompe el calendario. Clave: ``TICKER|YYYY-MM-DD``.
    """
    from app.services.connectors.sec import SECClient
    from app.services.earnings_dates_service import followed_calendar
    from app.services.earnings_materials_service import HISTORY_DAYS, materials_for_events

    # Mismo "hoy" que la pagina del calendario (Europe/Madrid), no el dia UTC del servidor.
    today = datetime.now(ZoneInfo("Europe/Madrid")).date()
    calendar = await run_in_threadpool(followed_calendar, db, today - timedelta(days=HISTORY_DAYS), today)
    events = [
        e for day in calendar["days"] for e in day["events"] if e.get("confirmed") is True
    ]
    items = await materials_for_events(events, today, sec=SECClient())
    return {"as_of": today.isoformat(), "items": items}


@router.get("/catalysts")
async def catalysts_calendar(
    desde: date | None = Query(default=None),
    hasta: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    """Calendario unico de catalizadores de la cartera (por defecto, 14 dias).

    Une resultados y fecha ex-dividendo (NASDAQ publico, posiciones y
    watchlist en bolsa US y USD), acciones corporativas registradas sin
    aplicar y, desde el historial de dividendos ya ingerido (posiciones y
    watchlist de cualquier mercado), las fechas de PAGO declaradas y los
    ex-dividendos no-US que NASDAQ no cubre. Cuando la fila de NASDAQ trae
    fecha de pago se muestra en el detalle del evento ex. Nada se estima:
    si la fuente no trae fecha de pago, no hay evento de pago. Si NASDAQ no
    responde, ``status`` lo declara (``partial``/``unavailable``) y las
    acciones corporativas propias y los dividendos ingeridos se siguen
    mostrando; nunca devuelve 5xx por un fallo del proveedor.
    """
    start = desde or _madrid_today()
    end = hasta or (start + timedelta(days=14))
    start, end = _resolve_range(start, end)
    # held_tickers y pending_actions son sqlalchemy sincrono: hilo del pool.
    held, held_us = await run_in_threadpool(catalyst_service.held_tickers, db)
    # Pieza 5: el calendario de resultados tambien cubre la watchlist (lineas
    # US), etiquetadas con origin="watchlist"; la cartera gana el origen.
    watch_us = await run_in_threadpool(catalyst_service.watchlist_us_tickers, db, held_us)
    watch_all = await run_in_threadpool(catalyst_service.watchlist_tickers, db, held)
    if not held and not watch_all:
        return {
            "status": "ok",
            "desde": start.isoformat(),
            "hasta": end.isoformat(),
            "held_count": 0,
            "watchlist_count": 0,
            "count": 0,
            "events": [],
            "errors": [],
        }
    if held_us or watch_us:
        earnings, dividends, filings = await asyncio.gather(
            calendar_connector.fetch_earnings_range(start, end),
            # Dividendos y plazos 10-Q/10-K siguen siendo solo de cartera:
            # para watchlist el brief pide resultados, no ruido.
            calendar_connector.fetch_dividends_range(start, end) if held_us else _empty_connector(),
            # Mismo deadline que NASDAQ: van en paralelo, asi la ruta entera
            # cabe en ~8 s. Con 20 s (presupuesto propio de EDGAR) una SEC
            # caida retenia la respuesta 20 s y el cliente (15 s) la cortaba:
            # la pagina perdia tambien lo que si habia (acciones, dividendos).
            catalyst_service.fetch_filing_deadlines(
                held_us, start, end, budget_seconds=calendar_connector.RANGE_DEADLINE_S
            )
            if held_us
            else _empty_connector(),
        )
    else:  # sin posiciones US no hay nada que cruzar con NASDAQ/EDGAR: no se les pregunta
        earnings = dividends = filings = {"status": "ok", "events": [], "errors": []}
    pending_actions = await run_in_threadpool(
        catalyst_service.pending_actions, db, start, end
    )
    # Historial de dividendos ingerido: cubre pagos (cualquier mercado) y
    # ex-dividendos no-US; es local, sin llamadas extra a proveedores.
    dividend_records = await run_in_threadpool(
        catalyst_service.upcoming_dividend_records, db, held | watch_all, start, end
    )
    events = catalyst_service.build_catalysts(
        held=held,
        held_us=held_us,
        desde=start,
        hasta=end,
        earnings=earnings["events"],
        dividends=dividends["events"],
        actions=pending_actions,
        watchlist_us=watch_us,
        watchlist=watch_all,
        records=dividend_records,
    )
    events = sorted(
        [*events, *filings["events"]],
        key=lambda e: (e["date"], catalyst_service._TYPE_ORDER[e["type"]], e["ticker"]),  # noqa: SLF001
    )
    return {
        "status": catalyst_service.combine_status(
            earnings["status"], dividends["status"], filings["status"]
        ),
        "desde": start.isoformat(),
        "hasta": end.isoformat(),
        "held_count": len(held),
        "watchlist_count": len(watch_all),
        "count": len(events),
        "events": events,
        "errors": earnings["errors"] + dividends["errors"] + filings["errors"],
    }


@router.get("/ipos")
async def ipo_calendar() -> dict:
    """Salidas a bolsa en EE. UU. del mes en curso y el siguiente (NASDAQ publico).

    Incluye las proximas (fecha prevista por la fuente) y las ya fijadas del
    periodo. Cobertura declarada: solo mercados US que publica NASDAQ (datos
    de EDGAR Online); el resto de mercados no aparece. Si NASDAQ no responde,
    ``status`` lo declara; nunca devuelve 5xx por un fallo del proveedor.
    """
    today = _madrid_today()
    months = [
        ipo_connector.add_months(today, offset) for offset in range(ipo_connector.DEFAULT_MONTHS)
    ]
    return await ipo_connector.fetch_ipo_calendar(months)


class FeedCreate(BaseModel):
    scope: str = "watchlist"


def _feed_state(row) -> dict:
    return {
        "active": row is not None,
        "scope": row.scope if row else None,
        "created_at": row.created_at.isoformat() if row else None,
        "last_used_at": row.last_used_at.isoformat() if row and row.last_used_at else None,
    }


@router.get("/feed")
def calendar_feed_status(db: Session = Depends(get_db)) -> dict:
    """Estado de la suscripcion ICS del tenant. Nunca devuelve el token (solo se guarda su hash)."""
    from app.services.calendar_feed_service import active_token

    return _feed_state(active_token(db))


@router.post("/feed")
def calendar_feed_create(payload: FeedCreate, db: Session = Depends(get_db)) -> dict:
    """Crea (o regenera) la suscripcion: revoca la anterior y devuelve el token UNA vez.

    ``path`` es relativo al backend; la URL publica la compone el front con su
    propio dominio (``/api/calendar-feed/<token>.ics`` y su variante webcal://).
    ``scope``: ``watchlist`` (solo la watchlist, valor prudente) o ``followed``
    (watchlist + empresas de posiciones abiertas: revela que se siguen, sin cantidades).
    """
    from app.services.calendar_feed_service import SCOPES, create_token

    if payload.scope not in SCOPES:
        raise HTTPException(status_code=422, detail=f"scope debe ser uno de {list(SCOPES)}")
    token, row = create_token(db, payload.scope)
    return {**_feed_state(row), "token": token, "path": f"/api/calendar/feed/{token}.ics"}


@router.delete("/feed")
def calendar_feed_revoke(db: Session = Depends(get_db)) -> dict:
    """Revoca la suscripcion activa: la URL deja de funcionar al instante."""
    from app.services.calendar_feed_service import revoke_tokens

    return {"revoked": revoke_tokens(db)}


@public_router.get("/feed/{filename}")
def calendar_feed_public(filename: str) -> Response:
    """Feed ICS publico: el unico secreto es el token del nombre de fichero.

    Sin identidad firmada a proposito (Apple/Google/Outlook no pueden firmar):
    abre su propia sesion, resuelve el tenant por el hash del token y responde
    404 identico para token desconocido o revocado.
    """
    from app.core.database import SessionLocal
    from app.services.calendar_feed_service import feed_for_token

    token = filename[:-4] if filename.endswith(".ics") else ""
    not_found = HTTPException(status_code=404, detail="Feed no encontrado")
    if not token.startswith("gfc_") or len(token) > 80 or not token.isascii():
        raise not_found
    db = SessionLocal()
    try:
        body = feed_for_token(db, token)
    finally:
        db.close()
    if body is None:
        raise not_found
    return Response(
        content=body,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Cache-Control": "private, max-age=300",
            "Content-Disposition": 'inline; filename="resultados.ics"',
            "Referrer-Policy": "no-referrer",
            "X-Robots-Tag": "noindex",
        },
    )
