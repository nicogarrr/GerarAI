"""Resumen diario "que paso con lo mio" como ResearchAlert enrutable.

El digest lo construye build_digest; este emisor lo resume en texto de
plantilla (sin LLM): cada variacion va con fuente (cierres ajustados de
yfinance) y fecha explicitas, y lo no cubierto se nombra como "sin datos",
nunca como 0.
"""
from __future__ import annotations

import hashlib
import math
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.i18n import generation_language
from app.core.local_date import USER_TIMEZONE
from app.models import PortfolioMoveDigest, ResearchAlert

VERSION = "daily-digest-alert-v1"

_MAX_LINEAS = 16


def last_session_date(today: date) -> date:
    """Ultimo dia laborable anterior a `today` (lun -> vie, sab/dom -> vie).

    El resumen diario pedia siempre "ayer": domingo y lunes caian en un dia sin
    mercado y la alerta decia "sin datos de cierre" para todas las posiciones.
    No conoce festivos de bolsa: ahi sigue diciendo "sin datos", sin inventar.
    """
    d = today - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _fingerprint(tenant_id: int, as_of: date) -> str:
    raw = f"{VERSION}:{tenant_id}:{as_of.isoformat()}".encode()
    return hashlib.sha256(raw).hexdigest()


def _fmt_pct(value: object) -> str | None:
    try:
        pct = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(pct):
        return None
    return f"{pct:+.2f}%"


_COVERAGE_EN = {"parcial": "partial", "completa": "complete", "complete": "complete", "partial": "partial"}


def _summary_en(items, disponibles, lineas, total_var, omitidas, sin_datos_shown, omitidas_sd, huecos, as_of) -> str:
    """Mismo resumen que el espanol, en ingles (usuario con ingles guardado en Ajustes)."""
    if not items:
        text = "There were no open positions to summarise."
    elif not disponibles:
        text = (f"{len(items)} positions tracked, no closing data for "
                f"{as_of.isoformat()} (no data, not 0).")
    else:
        text = f"{total_var} of {len(items)} positions moved: " + ", ".join(lineas) + "."
        if omitidas:
            text += f" Showing {len(lineas)} of {total_var} positions that moved; {omitidas} left out."
    if items and sin_datos_shown:
        text += f" No data: {', '.join(sin_datos_shown)}"
        text += f" and {omitidas_sd} more." if omitidas_sd else "."
    if huecos:
        parts = []
        for ticker in sorted(huecos)[:_MAX_LINEAS]:
            days = huecos[ticker]
            if days:
                missing = ", ".join(days)
                parts.append(f"{ticker} (missing the close of {missing})" if len(days) == 1
                             else f"{ticker} (missing the closes of {missing})")
            else:
                parts.append(f"{ticker} (a session in between is missing)")
        rest = len(huecos) - len(parts)
        text += (" No daily change because of a session gap, not 0: " + ", ".join(parts)
                 + (f" and {rest} more." if rest else "."))
    return text


def emit_digest_alert(db: Session, digest: PortfolioMoveDigest, as_of: date) -> ResearchAlert | None:
    """Persist the daily-digest alert once per tenant/day; None if already emitted.

    Privacy boundary: the digest must belong to the session tenant and match
    the requested as_of date; a foreign or stale digest is never announced.
    """
    tenant_id = db.info.get("tenant_id")
    if tenant_id is None:
        raise ValueError("Tenant context required")
    if digest.tenant_id != tenant_id:
        raise ValueError("Digest tenant does not match the session tenant")
    if digest.digest_date != as_of:
        raise ValueError("Digest date does not match the requested as_of")
    fp = _fingerprint(tenant_id, as_of)
    existing = db.scalar(select(ResearchAlert).where(
        ResearchAlert.tenant_id == tenant_id, ResearchAlert.fingerprint == fp,
    ))
    if existing is not None:
        return None
    items = digest.items or []
    # "disponible" sin variacion finita NO cuenta como dato: pasa a Sin datos.
    disponibles = []
    sin_datos = set()
    # Hueco de sesion: hay cierre del dia, pero falta una sesion entre el y el
    # anterior; no hay variacion de UN dia que mostrar. Se nombra aparte, con
    # la sesion que falta, en vez de mezclarlo con "Sin datos" sin motivo.
    huecos: dict[str, list[str]] = {}
    for item in items:
        pct = _fmt_pct(item.get("price_change_pct"))
        if item.get("status") == "disponible" and pct is not None:
            disponibles.append((abs(float(item["price_change_pct"])),
                                f"{item['ticker']} {pct}"))
        elif item.get("status") == "hueco de sesión" and item.get("ticker"):
            huecos[item["ticker"]] = [str(day) for day in item.get("missing_sessions") or []]
        elif item.get("ticker"):
            sin_datos.add(item["ticker"])
    disponibles.sort(reverse=True)
    total_var = len(disponibles)
    lineas = [txt for _, txt in disponibles[:_MAX_LINEAS]]
    omitidas = total_var - len(lineas)
    sin_datos_all = sorted(sin_datos)
    sin_datos_shown = sin_datos_all[:_MAX_LINEAS]
    omitidas_sd = len(sin_datos_all) - len(sin_datos_shown)
    # Idioma guardado del usuario (Ajustes); sin preferencia, espanol como siempre.
    en = generation_language(db) == "en"
    if en:
        resumen = _summary_en(items, disponibles, lineas, total_var, omitidas,
                              sin_datos_shown, omitidas_sd, huecos, as_of)
    elif not items:
        resumen = "No habia posiciones abiertas que resumir."
    elif not disponibles:
        resumen = (f"{len(items)} posiciones seguidas, sin datos de cierre para el "
                   f"{as_of.isoformat()} (sin datos, no 0).")
    else:
        resumen = (f"{total_var} de {len(items)} posiciones con variacion: "
                   + ", ".join(lineas) + ".")
        if omitidas:
            resumen += (f" Mostradas {len(lineas)} de {total_var} posiciones con "
                        f"variacion; {omitidas} omitidas.")
    if not en and items and sin_datos_shown:
        resumen += f" Sin datos: {', '.join(sin_datos_shown)}"
        resumen += f" y {omitidas_sd} mas." if omitidas_sd else "."
    if not en and huecos:
        partes = []
        for ticker in sorted(huecos)[:_MAX_LINEAS]:
            dias = huecos[ticker]
            if dias:
                faltan = ", ".join(dias)
                partes.append(f"{ticker} (falta el cierre del {faltan})" if len(dias) == 1
                              else f"{ticker} (faltan los cierres del {faltan})")
            else:
                partes.append(f"{ticker} (falta una sesión intermedia)")
        resto = len(huecos) - len(partes)
        resumen += (" Sin variación diaria por hueco de sesión, no 0: " + ", ".join(partes)
                    + (f" y {resto} más." if resto else "."))
    # La etiqueta del digest habla de su propia cobertura; si el resumen filtro
    # variaciones no finitas u omitio filas, el resumen es parcial aunque el
    # digest dijera "complete".
    cobertura_resumen = digest.coverage
    if items and (sin_datos or huecos or omitidas or total_var < len(items)):
        cobertura_resumen = "parcial"
    sampled = digest.generated_at
    if sampled.tzinfo is None:
        sampled = sampled.replace(tzinfo=UTC)
    sampled = sampled.astimezone(UTC)  # metadatos máquina: siempre UTC
    # La hora que lee el usuario va en Europe/Madrid, no en la del servidor (UTC).
    sampled_txt = sampled.astimezone(USER_TIMEZONE).strftime("%Y-%m-%d %H:%M") + " (hora de Madrid)"
    sampled_txt_en = sampled.astimezone(USER_TIMEZONE).strftime("%Y-%m-%d %H:%M") + " (Madrid time)"
    alert = ResearchAlert(
        tenant_id=tenant_id, company_id=None, severity="low", status="open",
        alert_type="daily_digest",
        title=(f"Daily summary of your portfolio as of {as_of.isoformat()}" if en
               else f"Resumen diario de tu cartera al {as_of.isoformat()}"),
        message=(
            (resumen + " Price changes from yfinance adjusted closes as of "
             f"{as_of.isoformat()}, not your position's P&L. "
             f"Portfolio measured when the summary was generated ({sampled_txt_en}); "
             "later moves are not included. "
             f"Summary coverage: {_COVERAGE_EN.get(str(cobertura_resumen), cobertura_resumen)}.")
            if en
            else (resumen + " Variaciones del valor con cierres ajustados de yfinance al "
                  f"{as_of.isoformat()}, no el P&L de tu posición. "
                  f"Cartera medida al generar el resumen ({sampled_txt}); "
                  "movimientos posteriores no están incluidos. "
                  f"Cobertura del resumen: {cobertura_resumen}.")
        ),
        fingerprint=fp, channels=["in_app"], last_triggered_at=datetime.now(UTC),
        metadata_={"digest_id": digest.id, "digest_date": as_of.isoformat(),
                   "coverage": cobertura_resumen, "digest_coverage": digest.coverage,
                   "rule_version": VERSION,
                   "price_source": "yfinance", "as_of": as_of.isoformat(),
                   "positions_sampled_at": sampled.isoformat()},
    )
    try:
        with db.begin_nested():
            db.add(alert)
            db.flush()
    except IntegrityError:
        return None
    db.commit()
    return alert
