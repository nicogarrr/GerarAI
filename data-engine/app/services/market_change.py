"""Variacion diaria unica sobre market_prices (cierres datados).

Una sola funcion alimenta Movers, Mercado y watchlist: dos pantallas con el
mismo precio no pueden mostrar porcentajes distintos por usar fuentes
distintas (cotizacion en vivo vs cierres de BD)."""

from __future__ import annotations

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models.entities import Company, MarketPrice

# Unica fuente que cuenta como cierre oficial: barras diarias reales (job
# market_close_sync). Finnhub/FMP/yahoo intradia son fotos spot de un momento
# cualquiera: comparar dos fotos daba variaciones distintas de las oficiales.
OFFICIAL_CLOSE_SOURCES = ("yfinance",)


def common_sessions(db: Session) -> tuple:
    """(ultima sesion comun, sesion anterior) de market_prices.

    Una fecha cuenta como sesion si es laborable y tiene cierres de al menos la
    mitad de la MEDIANA de empresas por fecha en las ultimas 10 fechas
    laborables. Con el maximo como referencia, una carga masiva puntual (1142
    empresas un dia, ~60-120 los siguientes) dejaba como unica sesion valida
    la de la carga y congelaba el ranking en una fecha vieja. Un cierre suelto
    de fin de semana o de un solo ticker tampoco define la sesion."""
    rows = db.execute(
        select(MarketPrice.date, func.count(func.distinct(MarketPrice.company_id)))
        .where(MarketPrice.source.in_(OFFICIAL_CLOSE_SOURCES))
        .group_by(MarketPrice.date)
        .order_by(MarketPrice.date.desc())
        .limit(30)
    ).all()
    weekdays = [(day, count) for day, count in rows if day.weekday() < 5][:10]
    if not weekdays:
        return None, None
    counts = sorted(count for _, count in weekdays)
    mid = len(counts) // 2
    median = counts[mid] if len(counts) % 2 else (counts[mid - 1] + counts[mid]) / 2
    threshold = median / 2
    sessions = [day for day, count in weekdays if count >= threshold]
    return (sessions[0] if sessions else None), (sessions[1] if len(sessions) > 1 else None)


def compute_session_changes(db: Session) -> tuple[list[dict], int, object]:
    """(filas por compania con change_pct, excluidas sin sesion comun, ultima sesion comun).

    change_pct es None salvo que el ultimo cierre sea el de la ultima sesion
    comun y el previo el de la sesion inmediatamente anterior."""
    # Ventana POR COMPAÑÍA: los dos últimos cierres de cada una, sin suelo
    # temporal global. Un corte global de N días expulsaba del universo a
    # cualquier compañía con el último cierre más viejo que la ventana, y a
    # otra con el último cierre dentro pero el anterior fuera le publicaba
    # precio con variación null: dos resultados distintos del mismo hueco de
    # datos. El contrato es "los dos últimos cierres de cada compañía".
    # Coste acotado por índice (uq company_id+date): un max() por compañía en
    # cada CTE y una lectura por clave; nunca un row_number sobre toda la
    # historia.
    official = MarketPrice.source.in_(OFFICIAL_CLOSE_SOURCES)
    latest_day = db.scalar(select(func.max(MarketPrice.date)).where(official))
    if latest_day is None:
        return [], 0, None
    latest_pairs = (
        select(
            MarketPrice.company_id.label("company_id"),
            func.max(MarketPrice.date).label("last_date"),
        )
        .where(official)
        .group_by(MarketPrice.company_id)
        .cte("movers_latest")
    )
    previous_pairs = (
        select(
            MarketPrice.company_id.label("company_id"),
            func.max(MarketPrice.date).label("prev_date"),
        )
        .join(
            latest_pairs,
            and_(
                MarketPrice.company_id == latest_pairs.c.company_id,
                MarketPrice.date < latest_pairs.c.last_date,
            ),
        )
        .where(official)
        .group_by(MarketPrice.company_id)
        .cte("movers_previous")
    )

    def _rows_at(pair_cte, date_column) -> list:
        return list(
            db.execute(
                select(
                    MarketPrice.company_id,
                    MarketPrice.date,
                    MarketPrice.close,
                    MarketPrice.volume,
                    MarketPrice.updated_at,
                    Company.ticker,
                    Company.name,
                    Company.sector,
                    Company.currency,
                )
                .join(
                    pair_cte,
                    and_(
                        MarketPrice.company_id == pair_cte.c.company_id,
                        MarketPrice.date == date_column,
                    ),
                )
                .join(Company, Company.id == MarketPrice.company_id)
            ).all()
        )

    def _entry(day, close, volume, registered, ticker, name, sector, currency) -> dict:
        return {
            "ticker": ticker,
            "name": name,
            "sector": sector,
            "currency": currency,
            "price": float(close or 0),
            # Volumen desconocido o 0 = None (la UI muestra N/D): una sesion
            # negociada no tiene volumen 0, es un dato ausente de la fuente.
            "volume": int(volume) if volume else None,
            "date": day.isoformat() if day else None,
            # Hora de observacion/registro (updated_at, tz-aware): dentro de
            # la misma sesion conviven filas refrescadas a distinta hora y la
            # fecha diaria sola no las distingue en el ranking.
            "registered_at": registered.isoformat() if registered else None,
        }

    latest: dict[int, dict] = {}
    for company_id, day, close, volume, registered, ticker, name, sector, currency in _rows_at(
        latest_pairs, latest_pairs.c.last_date
    ):
        latest[company_id] = _entry(day, close, volume, registered, ticker, name, sector, currency)
    previous: dict[int, dict] = {}
    for company_id, day, close, volume, registered, ticker, name, sector, currency in _rows_at(
        previous_pairs, previous_pairs.c.prev_date
    ):
        previous[company_id] = _entry(day, close, volume, registered, ticker, name, sector, currency)
    # Sesion comun: los rankings comparan manzanas con manzanas. Una fila solo
    # entra si su ultimo cierre es el de la ultima sesion comun Y su cierre
    # previo es el de la sesion inmediatamente anterior; con otro hueco, el
    # cambio seria de varios dias (o de una sesion vieja) presentado como el de
    # hoy (F9/F10). Las demas siguen en el universo, fuera de los rankings.
    session_day, prev_session_day = common_sessions(db)
    movers = []
    stale_excluded = 0
    for company_id, last in latest.items():
        prev = previous.get(company_id)
        base = float(prev["price"]) if prev else 0.0
        current = session_day is not None and last["date"] == session_day.isoformat()
        comparable = (
            current
            and prev is not None
            and prev["date"] == (prev_session_day.isoformat() if prev_session_day else None)
        )
        # Sin cierre anterior no hay cambio medible: None (la UI muestra "—"),
        # nunca un 0.0% que aparenta un dato que no existe.
        change_pct = (
            round((last["price"] - base) / base * 100, 2) if base and comparable else None
        )
        if not current:
            stale_excluded += 1
        movers.append(
            {
                **last,
                "change_pct": change_pct,
                "previous_close": base if base and comparable else None,
                "previous_date": prev["date"] if prev and comparable else None,
                "current": current,
            }
        )
    return movers, stale_excluded, session_day


def ticker_close_change(db: Session, company_id: int) -> dict | None:
    """Variacion "ultimo cierre vs anterior" de UNA compania, con la misma regla
    que compute_session_changes: solo cierres oficiales (OFFICIAL_CLOSE_SOURCES),
    el ultimo debe ser el de la ultima sesion comun y el previo el de la sesion
    comun inmediatamente anterior. Con cualquier hueco devuelve None: nunca un
    cambio de varios dias presentado como el de la ultima sesion."""
    session_day, prev_session_day = common_sessions(db)
    if session_day is None or prev_session_day is None:
        return None
    rows = db.execute(
        select(MarketPrice.date, MarketPrice.close)
        .where(MarketPrice.company_id == company_id, MarketPrice.source.in_(OFFICIAL_CLOSE_SOURCES))
        .order_by(MarketPrice.date.desc())
        .limit(2)
    ).all()
    if len(rows) < 2:
        return None
    (last_day, last_close), (prev_day, prev_close) = rows
    if last_day != session_day or prev_day != prev_session_day:
        return None
    last, prev = float(last_close or 0), float(prev_close or 0)
    if last <= 0 or prev <= 0:
        return None
    return {
        "close": last,
        "previous_close": prev,
        "date": last_day.isoformat(),
        "previous_date": prev_day.isoformat(),
        "change": last - prev,
        "change_percent": (last - prev) / prev * 100,
    }
