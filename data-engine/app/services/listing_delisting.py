"""Estado de negociacion de un listado: dato derivado vs baja probada.

Decision del piloto (11-nov-2026, via main): 5 sesiones consecutivas sin
barra prueban AUSENCIA de datos/negociacion (suspension temporal, proveedor
caido, festivo largo mal calendariado), NO la baja del listado. Por eso:

- ``listing_data_state`` es DERIVADO y reversible: se calcula del ultimo
  ``MarketPrice`` y del calendario de sesiones de la bolsa
  (``trading_sessions.missing_sessions``, que distingue festivos mirando a
  los demas valores de la bolsa). Nunca se persiste y se reversa solo en
  cuanto vuelve una barra.
- ``Company.delisted_at`` SOLO se fija con evidencia primaria de la baja
  (``mark_delisted`` la exige): un comunicado del emisor, del comprador o de
  la bolsa. Caso real: SES.TO (Secure Energy Services) — comunicado de GFL
  del 1-sep-2026 cerrando la adquisicion; Yahoo seguia respondiendo 200 con
  el ultimo precio congelado y 0 barras (observado el 11-nov-2026).
- El refresco de precios no pide cotizaciones de empresas dadas de baja;
  las ``no_trading_data`` SIGUEN pidiendose: si la suspension se levanta, la
  primera barra nueva las devuelve a ``active`` sin intervencion.

Nada aqui borra datos: los historicos de precios, tesis y documentos de una
empresa dada de baja se conservan intactos.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entities import Company, MarketPrice
from app.services.trading_sessions import missing_sessions

# Sesiones consecutivas sin barra a partir de las cuales el listado pasa a
# "no_trading_data". Ni el festivo mas largo de TSX/NYSE (4 dias naturales)
# ni un proveedor caido un fin de semana lo alcanzan; una suspension o una
# baja si.
SESSIONS_WITHOUT_BAR_THRESHOLD = 5


def sessions_without_bar(db: Session, company: Company, *, today: date) -> int:
    """Sesiones de la bolsa desde la ultima barra hasta ``today`` inclusive.

    0 si la empresa no tiene ninguna barra: sin historico no hay senal (un
    alta reciente aun sin datos no es una suspension).
    """
    last_bar = db.scalar(
        select(func.max(MarketPrice.date)).where(MarketPrice.company_id == company.id)
    )
    if last_bar is None or last_bar >= today:
        return 0
    # missing_sessions(previous, latest) cuenta estrictamente entre ambas:
    # latest = manana incluye ``today`` en el gap.
    return len(missing_sessions(db, company, last_bar, today + timedelta(days=1)))


def listing_data_state(db: Session, company: Company, *, today: date | None = None) -> str:
    """"delisted" | "no_trading_data" | "active" (en ese orden de dominio)."""
    if company.delisted_at is not None:
        return "delisted"
    today = today or date.today()
    if sessions_without_bar(db, company, today=today) >= SESSIONS_WITHOUT_BAR_THRESHOLD:
        return "no_trading_data"
    return "active"


def mark_delisted(
    db: Session,
    company: Company,
    *,
    evidence: str,
    at: datetime | None = None,
) -> None:
    """Fija la baja del listado. ``evidence`` es la referencia de la fuente
    primaria (comunicado, circular de bolsa) y queda en ``listing_note``.
    Sin evidencia no hay baja: ValueError. No borra ningun dato."""
    evidence = (evidence or "").strip()
    if not evidence:
        raise ValueError("la baja de un listado exige evidencia primaria")
    company.delisted_at = at or datetime.now(UTC)
    company.listing_note = evidence[:200]
    db.flush()


def clear_delisted(db: Session, company: Company, *, evidence: str) -> None:
    """Revierte la baja (relistado, error de fuente). Tambien exige
    evidencia: la auditoria del estado vive en quien lo fija, no en el dato
    borrado — las columnas vuelven a NULL y todo lo demas sigue intacto."""
    evidence = (evidence or "").strip()
    if not evidence:
        raise ValueError("revertir una baja exige evidencia primaria")
    company.delisted_at = None
    company.listing_note = None
    db.flush()
