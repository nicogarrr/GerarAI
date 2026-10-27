"""Variacion diaria unica sobre market_prices (cierres datados).

Una sola funcion alimenta Movers, Mercado y watchlist: dos pantallas con el
mismo precio no pueden mostrar porcentajes distintos por usar fuentes
distintas (cotizacion en vivo vs cierres de BD)."""

from __future__ import annotations

from collections.abc import Collection
from types import SimpleNamespace

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models.entities import Company, MarketPrice
from app.services.price_units import listing_price
from app.valuation.currency import listing_currency

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


def compute_session_changes(
    db: Session, tickers: Collection[str] | None = None
) -> tuple[list[dict], int, object]:
    """(filas por compania con change_pct, excluidas sin sesion comun, ultima sesion comun).

    change_pct es None salvo que el ultimo cierre sea el de la ultima sesion
    comun y el previo el de la sesion inmediatamente anterior.

    `tickers` (opcional) limita el calculo a esas compañías (sin distinguir
    mayúsculas). Las sesiones comunes se siguen calculando sobre TODO el
    universo, así que cada fila es idéntica a la del cálculo completo; solo se
    evita leer y normalizar los cierres de las compañías que nadie pidió
    (/api/market/changes pide 3-30 tickers y recalculaba ~1200)."""
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
    if tickers is not None:
        wanted = sorted({t.strip().upper() for t in tickers if t and t.strip()})
        if not wanted:
            return [], 0, None
        official = and_(
            official,
            MarketPrice.company_id.in_(
                select(Company.id).where(func.upper(Company.ticker).in_(wanted))
            ),
        )
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
                    MarketPrice.quote_currency,
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

    def _entry(day, close, volume, registered, ticker, name, sector, currency, quote_currency) -> dict:
        company = SimpleNamespace(ticker=ticker, currency=currency)
        currency = listing_currency(ticker, currency)
        normalized = None
        if close is not None:
            # Divisa de la cotizacion que declara Yahoo (SHEL.L en GBp aunque
            # las cuentas sean USD): el precio se muestra en ESA divisa.
            listed = listing_price(close, quote_currency=quote_currency, company=company)
            if listed is not None:
                normalized, currency = listed
        return {
            "ticker": ticker,
            "name": name,
            "sector": sector,
            "currency": currency,
            "price": float(normalized) if normalized is not None else None,
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
    for (
        company_id,
        day,
        close,
        volume,
        registered,
        ticker,
        name,
        sector,
        currency,
        quote_currency,
    ) in _rows_at(latest_pairs, latest_pairs.c.last_date):
        latest[company_id] = _entry(
            day, close, volume, registered, ticker, name, sector, currency, quote_currency
        )
    previous: dict[int, dict] = {}
    for (
        company_id,
        day,
        close,
        volume,
        registered,
        ticker,
        name,
        sector,
        currency,
        quote_currency,
    ) in _rows_at(previous_pairs, previous_pairs.c.prev_date):
        previous[company_id] = _entry(
            day, close, volume, registered, ticker, name, sector, currency, quote_currency
        )
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
        if (
            prev is not None
            and prev["price"] is not None
            and last["price"] is not None
            and prev["currency"] != last["currency"]
        ):
            # La divisa de la cotizacion cambia entre las dos sesiones (GBX y
            # luego USD en la misma linea): dato ambiguo del proveedor, ni
            # precio ni ranking. Una divisa estable distinta de la de las
            # cuentas (SHEL.L en GBp, cuentas USD) si se muestra.
            last = {**last, "price": None}
        base = float(prev["price"]) if prev and prev["price"] is not None else 0.0
        current = session_day is not None and last["date"] == session_day.isoformat()
        comparable = (
            current
            and prev is not None
            and last["price"] is not None
            and prev["date"] == (prev_session_day.isoformat() if prev_session_day else None)
            # Misma divisa de cotizacion en las dos sesiones (sin mezclar).
            and prev["currency"] == last["currency"]
        )
        # Sin cierre anterior no hay cambio medible: None (la UI muestra "—"),
        # nunca un 0.0% que aparenta un dato que no existe.
        change_pct = round((last["price"] - base) / base * 100, 2) if base and comparable else None
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
        select(MarketPrice.date, MarketPrice.close, MarketPrice.quote_currency)
        .where(MarketPrice.company_id == company_id, MarketPrice.source.in_(OFFICIAL_CLOSE_SOURCES))
        .order_by(MarketPrice.date.desc())
        .limit(2)
    ).all()
    if len(rows) < 2:
        return None
    (last_day, last_close, last_unit), (prev_day, prev_close, prev_unit) = rows
    if last_day != session_day or prev_day != prev_session_day:
        return None
    company = db.get(Company, company_id)
    if company is None:
        return None
    last_listed = listing_price(last_close, quote_currency=last_unit, company=company)
    prev_listed = listing_price(prev_close, quote_currency=prev_unit, company=company)
    if last_listed is None or prev_listed is None:
        return None
    # Ambos cierres en la divisa de su cotizacion; distinta divisa entre las
    # dos sesiones no da una variacion honesta.
    if last_listed[1] != prev_listed[1]:
        return None
    currency = last_listed[1]
    last, prev = float(last_listed[0]), float(prev_listed[0])
    if last <= 0 or prev <= 0:
        return None
    return {
        "currency": currency,
        "close": last,
        "previous_close": prev,
        "date": last_day.isoformat(),
        "previous_date": prev_day.isoformat(),
        "change": last - prev,
        "change_percent": (last - prev) / prev * 100,
    }
