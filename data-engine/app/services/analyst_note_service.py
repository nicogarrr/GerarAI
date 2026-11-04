"""Notas de analista estructuradas: validacion, upsert idempotente y lectura.

Feature aprobada por Nico (4-nov-2026). Es la entrada del experto en analistas
del equipo del Cerebro: cada nota guarda firma, analista, fecha, accion,
rating y objetivo antes -> despues, precio ese dia, argumentos clave,
sentimiento, cita literal y fuente (URL + tipo), y todo lo demas que la fuente
diga (estimaciones, metodo de valoracion, supuestos por segmento, casos
alcista/bajista, catalizadores, riesgos, cambios, enlaces, ``extras``).

Reglas generales (sin codigo por empresa):

- privado por tenant: toda lectura y escritura exige un tenant valido y el de
  la sesion, si la sesion lo fija;
- idempotente: la clave es (tenant, ticker, firma normalizada, fecha, accion);
  repetir el mismo upsert no crea filas ni cambia nada;
- fusion sin perdida: un valor nuevo no nulo completa o actualiza el campo, los
  ``None`` no borran nada, las listas se unen sin duplicados y ``extras`` se
  fusiona por clave;
- verificacion: ``social`` es siempre ``rumor_no_verificado``; ``verificado``
  exige cita y URL https; la verificacion de una fila nunca baja (una fuente
  verificada sustituye a la fuente esqueleto, cuya URL pasa a ``links``).
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenancy import session_tenant_id
from app.models.analyst_note import (
    ANALYST_NOTE_ACTIONS,
    ANALYST_NOTE_SENTIMENTS,
    ANALYST_NOTE_SOURCE_TYPES,
    ANALYST_NOTE_VERIFICATIONS,
    AnalystNote,
)
from app.services.analyst_history_service import normalize_firm
from app.services.inferred_input_service import is_valid_https_url

MAX_KEY_ARGUMENTS = 12
MAX_LIST_ITEMS = 25
MAX_TEXT_CHARS = 4000
MAX_SHORT_TEXT = 200
VERIFICATION_RANK = {"rumor_no_verificado": 0, "fragmento": 1, "verificado": 2}

# Acciones tal como las publica Yahoo (upgrades_downgrades) y en texto libre.
_ACTION_ALIASES: dict[str, str] = {
    "up": "upgrade",
    "upgrade": "upgrade",
    "upgrades": "upgrade",
    "raised": "upgrade",
    "down": "downgrade",
    "downgrade": "downgrade",
    "downgrades": "downgrade",
    "lowered": "downgrade",
    "init": "initiate",
    "initiate": "initiate",
    "initiated": "initiate",
    "initiates": "initiate",
    "resume": "initiate",
    "reinstated": "initiate",
    "reit": "reiterate",
    "reiterate": "reiterate",
    "reiterated": "reiterate",
    "reiterates": "reiterate",
    "main": "maintain",
    "maintain": "maintain",
    "maintained": "maintain",
    "maintains": "maintain",
}


class AnalystNoteError(ValueError):
    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


def normalize_action(raw: Any) -> str:
    """Accion normalizada; lo desconocido es ``other`` (nunca se inventa)."""
    text = str(raw or "").strip().lower()
    return _ACTION_ALIASES.get(text, "other") if text else "other"


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite() or number <= 0:
        return None
    return number.quantize(Decimal("0.00000001"))


def _short(value: Any, limit: int = MAX_SHORT_TEXT) -> str | None:
    text = " ".join(str(value).split()) if value is not None else ""
    return text[:limit] if text else None


def _text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text[:MAX_TEXT_CHARS] if text else None


def _str_list(values: Any, limit: int = MAX_LIST_ITEMS) -> list[str]:
    out: list[str] = []
    for item in values or []:
        text = _short(item, 600)
        if text and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def _union(old: list[str] | None, new: list[str], limit: int) -> list[str]:
    merged = list(old or [])
    for item in new:
        if item not in merged:
            merged.append(item)
    return merged[:limit]


@dataclass
class AnalystNoteInput:
    """Una nota tal como llega de un colector (Yahoo, noticia, prensa, red social)."""

    ticker: str
    firm: str
    note_date: date
    action: str
    source_type: str
    analyst: str | None = None
    rating_old: str | None = None
    rating_new: str | None = None
    pt_old: Any = None
    pt_new: Any = None
    currency: str | None = None
    price_at_note: Any = None
    key_arguments: list[str] = field(default_factory=list)
    sentiment: str | None = None
    quote: str | None = None
    source_url: str | None = None
    verification: str | None = None
    company_id: int | None = None
    document_id: int | None = None
    estimates: dict[str, Any] = field(default_factory=dict)
    valuation: dict[str, Any] = field(default_factory=dict)
    segment_assumptions: dict[str, Any] = field(default_factory=dict)
    bull_target: Any = None
    bear_target: Any = None
    bull_case: str | None = None
    bear_case: str | None = None
    catalysts: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    changes_since_previous: str | None = None
    links: list[str] = field(default_factory=list)
    extras: dict[str, Any] = field(default_factory=dict)
    driver_refs: list[str] | None = None


def _require_tenant(tenant_id: Any, db: Session) -> int:
    if type(tenant_id) is not int or tenant_id <= 0:
        raise AnalystNoteError(["hace falta un tenant válido: las notas de analista son privadas"])
    session_tenant = session_tenant_id(db)
    if session_tenant is not None and session_tenant != tenant_id:
        raise AnalystNoteError(["el tenant pedido no es el de la sesión"])
    return tenant_id


def dedupe_key(tenant_id: int, ticker: str, firm: str, note_date: date, action: str) -> str:
    firm_key = (normalize_firm(firm) or "").lower()
    raw = (
        f"{tenant_id}|{ticker.strip().upper()}|{firm_key}|{note_date.isoformat()}|{normalize_action(action)}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def clean_note(item: AnalystNoteInput) -> dict[str, Any]:
    """Valida y normaliza una nota; lanza ``AnalystNoteError`` con los motivos."""
    problems: list[str] = []
    ticker = (item.ticker or "").strip().upper()
    if not ticker or len(ticker) > 32:
        problems.append("ticker vacío o demasiado largo")
    firm = normalize_firm(item.firm)
    if not firm:
        problems.append("falta la firma")
    if not isinstance(item.note_date, date):
        problems.append("fecha de la nota no válida")
    action = normalize_action(item.action)
    if action not in ANALYST_NOTE_ACTIONS:
        problems.append("acción no válida")
    source_type = (item.source_type or "").strip().lower()
    if source_type not in ANALYST_NOTE_SOURCE_TYPES:
        problems.append(f"tipo de fuente no válido: {item.source_type!r}")
    sentiment = (item.sentiment or "").strip().lower() or None
    if sentiment is not None and sentiment not in ANALYST_NOTE_SENTIMENTS:
        problems.append(f"sentimiento no válido: {item.sentiment!r}")
    source_url = (item.source_url or "").strip() or None
    if source_url is not None and not is_valid_https_url(source_url):
        problems.append("la URL de la fuente no es una URL https pública")
    quote = _text(item.quote)
    if source_type == "social":
        verification = "rumor_no_verificado"
    else:
        verification = (item.verification or "").strip() or (
            "verificado" if quote and source_url else "fragmento"
        )
    if verification not in ANALYST_NOTE_VERIFICATIONS:
        problems.append(f"verificación no válida: {item.verification!r}")
    if verification == "verificado" and not (quote and source_url):
        problems.append("una nota verificada necesita cita literal y URL de la fuente")
    if problems:
        raise AnalystNoteError(problems)
    assert firm is not None
    return {
        "ticker": ticker,
        "firm": firm,
        "firm_key": firm.lower(),
        "note_date": item.note_date,
        "action": action,
        "source_type": source_type,
        "verification": verification,
        "analyst": _short(item.analyst),
        "rating_old": _short(item.rating_old, 80),
        "rating_new": _short(item.rating_new, 80),
        "pt_old": _decimal(item.pt_old),
        "pt_new": _decimal(item.pt_new),
        "currency": _short(item.currency, 10),
        "price_at_note": _decimal(item.price_at_note),
        "key_arguments": _str_list(item.key_arguments, MAX_KEY_ARGUMENTS),
        "sentiment": sentiment,
        "quote": quote,
        "source_url": source_url,
        "company_id": item.company_id,
        "document_id": item.document_id,
        "estimates": dict(item.estimates or {}),
        "valuation": dict(item.valuation or {}),
        "segment_assumptions": dict(item.segment_assumptions or {}),
        "bull_target": _decimal(item.bull_target),
        "bear_target": _decimal(item.bear_target),
        "bull_case": _text(item.bull_case),
        "bear_case": _text(item.bear_case),
        "catalysts": _str_list(item.catalysts),
        "risks": _str_list(item.risks),
        "changes_since_previous": _text(item.changes_since_previous),
        "links": [u for u in _str_list(item.links) if is_valid_https_url(u)],
        "extras": dict(item.extras or {}),
        "driver_refs": _str_list(item.driver_refs) if item.driver_refs is not None else None,
    }


_SOURCE_FIELDS = ("source_url", "source_type", "verification", "quote", "document_id")
_LIST_FIELDS = {
    "key_arguments": MAX_KEY_ARGUMENTS,
    "catalysts": MAX_LIST_ITEMS,
    "risks": MAX_LIST_ITEMS,
    "links": MAX_LIST_ITEMS,
}
_DICT_FIELDS = ("estimates", "valuation", "segment_assumptions", "extras")
_IDENTITY = ("ticker", "firm_key", "note_date", "action")


class AnalystNoteService:
    def upsert(self, db: Session, tenant_id: int, item: AnalystNoteInput) -> tuple[AnalystNote, bool]:
        """Inserta o completa la nota; devuelve (fila, cambió). No hace commit."""
        tenant = _require_tenant(tenant_id, db)
        data = clean_note(item)
        key = dedupe_key(tenant, data["ticker"], data["firm"], data["note_date"], data["action"])
        row = db.execute(select(AnalystNote).where(AnalystNote.dedupe_key == key)).scalar_one_or_none()
        if row is None:
            row = AnalystNote(tenant_id=tenant, dedupe_key=key, **data)
            db.add(row)
            db.flush()
            return row, True
        if row.tenant_id != tenant:  # pragma: no cover - la clave incluye el tenant
            raise AnalystNoteError(["la nota pertenece a otro tenant"])
        changed = False
        new_rank = VERIFICATION_RANK[data["verification"]]
        old_rank = VERIFICATION_RANK.get(row.verification, 0)
        links = list(row.links or [])
        if new_rank > old_rank:
            if row.source_url and row.source_url != data["source_url"] and row.source_url not in links:
                links.append(row.source_url)
            for name in _SOURCE_FIELDS:
                if getattr(row, name) != data[name]:
                    setattr(row, name, data[name])
                    changed = True
        elif new_rank == old_rank and row.quote is None and data["quote"]:
            row.quote = data["quote"]
            changed = True
        elif data["source_url"] and data["source_url"] != row.source_url and data["source_url"] not in links:
            links.append(data["source_url"])
        merged_links = _union(links, data["links"], MAX_LIST_ITEMS)
        if merged_links != list(row.links or []):
            row.links = merged_links
            changed = True
        for name, value in data.items():
            if name in _SOURCE_FIELDS or name in _IDENTITY or name == "links" or name == "firm":
                continue
            current = getattr(row, name)
            if name in _LIST_FIELDS:
                merged = _union(current, value, _LIST_FIELDS[name])
                if merged != list(current or []):
                    setattr(row, name, merged)
                    changed = True
            elif name in _DICT_FIELDS:
                merged_dict = {**(current or {}), **value}
                if merged_dict != (current or {}):
                    setattr(row, name, merged_dict)
                    changed = True
            elif name == "driver_refs":
                if value is not None:
                    merged = _union(current, value, MAX_LIST_ITEMS)
                    if merged != list(current or []):
                        row.driver_refs = merged
                        changed = True
            elif value is not None and current != value:
                setattr(row, name, value)
                changed = True
        if changed:
            db.flush()
        return row, changed

    def list_notes(
        self,
        db: Session,
        tenant_id: int,
        ticker: str,
        *,
        firms: Sequence[str] | None = None,
        limit: int = 50,
    ) -> list[AnalystNote]:
        """Notas del ticker de este tenant, más recientes primero."""
        tenant = _require_tenant(tenant_id, db)
        stmt = select(AnalystNote).where(
            AnalystNote.tenant_id == tenant, AnalystNote.ticker == ticker.strip().upper()
        )
        if firms:
            keys = [k.lower() for k in (normalize_firm(f) for f in firms) if k]
            stmt = stmt.where(AnalystNote.firm_key.in_(keys))
        stmt = stmt.order_by(AnalystNote.note_date.desc(), AnalystNote.id.desc()).limit(
            max(1, min(limit, 500))
        )
        return list(db.execute(stmt).scalars())

    def latest_by_firm(
        self, db: Session, tenant_id: int, ticker: str, firms: Sequence[str], *, per_firm: int = 1
    ) -> list[AnalystNote]:
        """Las ``per_firm`` notas más recientes de cada firma, en el orden de ``firms``
        (el ranking de #4543); una firma sin notas no aparece."""
        notes = self.list_notes(db, tenant_id, ticker, firms=firms, limit=500)
        out: list[AnalystNote] = []
        for firm in firms:
            key = (normalize_firm(firm) or "").lower()
            out.extend([n for n in notes if n.firm_key == key][: max(1, per_firm)])
        return out


analyst_note_service = AnalystNoteService()
