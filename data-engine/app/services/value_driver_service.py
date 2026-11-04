"""Inventario de impulsores de valor por tenant y empresa (etapa «Recopilador»).

Feature aprobada por Nico (4-nov-2026). Primera etapa del pipeline automático de
la tesis (SPEC_ADDENDUM «inventario de impulsores»): antes de buscar inputs y
valorar, el equipo de expertos lista todo lo que mueve el valor de la empresa,
para que ningún contrato, mercado, activo u opción quede fuera sin avisar.

Este módulo no llama a ningún LLM. Da:

- :class:`ValueDriverItem`, el registro de un impulsor, y :func:`normalize_item`
  y :meth:`ValueDriverService.validate` (fail-closed: fuente con URL y cita
  obligatorias, tratamiento obligatorio con su enlace o su motivo);
- almacén por tenant (``current``/``history``/``upsert``/``upsert_many``/
  ``retire``), idempotente y con histórico por ``superseded_at``;
- :func:`publication_check`, función pura con la regla «no se publica valor si
  un impulsor firmado y material no tiene tratamiento» (motivo
  ``impulsor_material_sin_tratar``), que devuelve los impulsores que bloquean.

Reglas generales (ninguna por ticker):

- Una fuente de foro o red social (p. ej. un post en X) es SIEMPRE rumor: el
  estado pasa a ``rumor`` y la evidencia a ``rumor`` aunque el texto diga
  «firmado», hasta que un filing o una nota oficial lo confirme. Un rumor nunca
  cuenta como firmado.
- «Oficial» exige una fuente oficial (filing, nota de la empresa o del socio,
  regulador); con prensa o analista la evidencia baja a ``estimado``.
- Re-ejecutar el Recopilador no borra el tratamiento que ya puso el valorador:
  una fila nueva con ``pendiente`` hereda el tratamiento vigente.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenancy import session_tenant_id
from app.models.entities import Company
from app.models.value_driver import (
    VALUE_DRIVER_CATEGORIES,
    VALUE_DRIVER_EVIDENCE,
    VALUE_DRIVER_SOURCE_TYPES,
    VALUE_DRIVER_STATUSES,
    VALUE_DRIVER_TREATMENTS,
    ValueDriver,
)

# Fuentes que no confirman nada: lo que dicen es rumor hasta que un documento
# oficial lo confirme.
RUMOR_SOURCE_TYPES: tuple[str, ...] = ("foro", "redes")
# Fuentes que pueden sostener una evidencia «oficial».
OFFICIAL_SOURCE_TYPES: tuple[str, ...] = ("filing", "nota_empresa", "nota_socio", "regulador")
# Estados que comprometen a la empresa (SPEC_ADDENDUM §6.1: firmado o anunciado).
COMMITTED_STATUSES: tuple[str, ...] = ("firmado", "anunciado_oficial")
# Material: economía ≥ 1 % de la capitalización, o tema principal de un 8-K/nota.
MATERIALITY_SHARE_OF_MARKET_CAP = Decimal("0.01")
UNTREATED = "pendiente"
BLOCK_REASON = "impulsor_material_sin_tratar"

DRIVER_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,119}$")
URL_RE = re.compile(r"^https?://\S+$")
MAX_NAME = 200
MAX_TIMING = 120
MAX_MODEL_LINK = 120


class ValueDriverError(ValueError):
    """Un impulsor no cumple las reglas del inventario (fail-closed)."""

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


@dataclass(frozen=True)
class ValueDriverItem:
    """Un impulsor de valor a guardar en el inventario de una empresa."""

    driver_key: str
    category: str
    name: str
    status: str
    source_type: str
    evidence: str
    source_url: str | None = None
    source_quote: str | None = None
    document_id: int | None = None
    as_of: date | None = None
    economics: dict[str, Any] = field(default_factory=dict)
    timing: str | None = None
    headline: bool = False
    treatment: str = UNTREATED
    model_link: str | None = None
    reason_if_not_valued: str | None = None
    value_per_share_marginal: float | Decimal | None = None
    confidence: float | Decimal | None = None
    fingerprint: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DriverBlock:
    driver_key: str
    name: str
    status: str
    why: str

    def as_dict(self) -> dict[str, Any]:
        return {"driver_key": self.driver_key, "name": self.name, "status": self.status, "why": self.why}


@dataclass(frozen=True)
class PublicationCheck:
    """Resultado de la puerta «impulsores materiales sin tratar»."""

    publishable: bool
    reason: str | None
    blocking: tuple[DriverBlock, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "publishable": self.publishable,
            "reason": self.reason,
            "blocking": [b.as_dict() for b in self.blocking],
        }


@dataclass(frozen=True)
class UpsertResult:
    row: ValueDriver
    changed: bool
    action: str  # created | replaced | unchanged


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _clean(text: str | None) -> str | None:
    return (text or "").strip() or None


def normalize_item(item: ValueDriverItem) -> ValueDriverItem:
    """Aplica las reglas de evidencia: un rumor nunca cuenta como firmado.

    - Fuente de foro/redes → estado ``rumor`` y evidencia ``rumor``.
    - Estado ``rumor`` → evidencia ``rumor``.
    - Evidencia ``oficial`` sin fuente oficial → ``estimado``.
    Lo declarado y cambiado queda en ``metadata`` (``status_declarado``,
    ``evidence_declarada``).
    """
    status, evidence = item.status, item.evidence
    metadata = dict(item.metadata)
    if item.source_type in RUMOR_SOURCE_TYPES:
        status, evidence = "rumor", "rumor"
    if status == "rumor":
        evidence = "rumor"
    if evidence == "oficial" and item.source_type not in OFFICIAL_SOURCE_TYPES:
        evidence = "estimado"
    if status != item.status:
        metadata["status_declarado"] = item.status
    if evidence != item.evidence:
        metadata["evidence_declarada"] = item.evidence
    if status == item.status and evidence == item.evidence:
        return item
    return replace(item, status=status, evidence=evidence, metadata=metadata)


def _amount_usd(economics: Any) -> Decimal | None:
    if not isinstance(economics, dict):
        return None
    amount = _decimal(economics.get("amount_usd"))
    return abs(amount) if amount is not None else None


def is_material(item: ValueDriverItem, market_cap_usd: float | Decimal | None) -> bool:
    """SPEC_ADDENDUM §6.1: economía > 1 % de la capitalización o tema principal.

    Con importe pero sin capitalización conocida se asume material (prudente).
    Sin importe y sin ser tema principal no es material.
    """
    if item.headline:
        return True
    amount = _amount_usd(item.economics)
    if amount is None:
        return False
    cap = _decimal(market_cap_usd)
    if cap is None or cap <= 0:
        return True
    return amount >= cap * MATERIALITY_SHARE_OF_MARKET_CAP


def _untreated_why(item: ValueDriverItem) -> str | None:
    if item.treatment == UNTREATED or item.treatment not in VALUE_DRIVER_TREATMENTS:
        return "sin tratamiento"
    if item.treatment == "no_valorado" and not _clean(item.reason_if_not_valued):
        return "no valorado sin motivo"
    if item.treatment == "en_modelo" and not _clean(item.model_link):
        return "en el modelo sin decir qué input lo recoge"
    return None


def publication_check(
    drivers: Iterable[ValueDriverItem | ValueDriver],
    *,
    market_cap_usd: float | Decimal | None = None,
) -> PublicationCheck:
    """«No se publica valor si un impulsor firmado y material no tiene tratamiento».

    Función pura. Cada impulsor se normaliza antes (un rumor nunca cuenta como
    firmado). Devuelve los que bloquean, ordenados por clave.
    """
    blocks: list[DriverBlock] = []
    for raw in drivers:
        item = normalize_item(raw if isinstance(raw, ValueDriverItem) else as_item(raw))
        if item.status not in COMMITTED_STATUSES:
            continue
        if not is_material(item, market_cap_usd):
            continue
        why = _untreated_why(item)
        if why:
            blocks.append(DriverBlock(item.driver_key, item.name, item.status, why))
    blocks.sort(key=lambda b: b.driver_key)
    if blocks:
        return PublicationCheck(False, BLOCK_REASON, tuple(blocks))
    return PublicationCheck(True, None, ())


def as_item(row: ValueDriver) -> ValueDriverItem:
    return ValueDriverItem(
        driver_key=row.driver_key,
        category=row.category,
        name=row.name,
        status=row.status,
        source_type=row.source_type,
        evidence=row.evidence,
        source_url=row.source_url,
        source_quote=row.source_quote,
        document_id=row.document_id,
        as_of=row.as_of,
        economics=dict(row.economics or {}),
        timing=row.timing,
        headline=bool(row.headline),
        treatment=row.treatment or UNTREATED,
        model_link=row.model_link,
        reason_if_not_valued=row.reason_if_not_valued,
        value_per_share_marginal=row.value_per_share_marginal,
        confidence=row.confidence,
        fingerprint=row.fingerprint,
        metadata=dict(row.metadata_ or {}),
    )


def _require_tenant(tenant_id: Any, db: Session | None = None) -> int:
    if type(tenant_id) is not int or tenant_id <= 0:
        raise ValueDriverError(["hace falta un tenant válido: el inventario es privado"])
    session_tenant = session_tenant_id(db) if db is not None else None
    if session_tenant is not None and session_tenant != tenant_id:
        raise ValueDriverError(["el tenant pedido no es el de la sesión"])
    return tenant_id


def validate_item(item: ValueDriverItem) -> list[str]:
    """Problemas de un impulsor (vacío = válido). Fail-closed."""
    problems: list[str] = []
    key = item.driver_key or ""
    if not DRIVER_KEY_RE.match(key):
        problems.append(f"driver_key inválida: {key!r} (minúsculas, dígitos y _.:-, máx. 120)")
    if item.category not in VALUE_DRIVER_CATEGORIES:
        problems.append(f"categoría desconocida: {item.category!r}")
    if item.status not in VALUE_DRIVER_STATUSES:
        problems.append(f"estado desconocido: {item.status!r}")
    if item.source_type not in VALUE_DRIVER_SOURCE_TYPES:
        problems.append(f"tipo de fuente desconocido: {item.source_type!r}")
    if item.evidence not in VALUE_DRIVER_EVIDENCE:
        problems.append(f"evidencia desconocida: {item.evidence!r}")
    if item.treatment not in VALUE_DRIVER_TREATMENTS:
        problems.append(f"tratamiento desconocido: {item.treatment!r}")
    name = _clean(item.name)
    if not name:
        problems.append("falta el nombre")
    elif len(name) > MAX_NAME:
        problems.append(f"nombre de más de {MAX_NAME} caracteres")
    url = _clean(item.source_url)
    if not url:
        problems.append("falta la URL de la fuente")
    elif not URL_RE.match(url):
        problems.append(f"URL de fuente inválida: {url!r}")
    if not _clean(item.source_quote):
        problems.append("falta la cita literal de la fuente")
    if item.timing is not None and len(item.timing) > MAX_TIMING:
        problems.append(f"timing de más de {MAX_TIMING} caracteres")
    if item.treatment == "en_modelo" and not _clean(item.model_link):
        problems.append("en_modelo exige model_link (qué input o término lo recoge)")
    if item.model_link is not None and len(item.model_link) > MAX_MODEL_LINK:
        problems.append(f"model_link de más de {MAX_MODEL_LINK} caracteres")
    if item.treatment == "no_valorado" and not _clean(item.reason_if_not_valued):
        problems.append("no_valorado exige el motivo")
    if not isinstance(item.economics, dict):
        problems.append("economics debe ser un objeto")
    else:
        for numeric in ("amount", "amount_usd"):
            if numeric in item.economics and item.economics[numeric] is not None:
                if _decimal(item.economics[numeric]) is None:
                    problems.append(f"economics.{numeric} no es un número")
    if item.confidence is not None:
        conf = _decimal(item.confidence)
        if conf is None or conf < 0 or conf > 1:
            problems.append("confidence debe estar entre 0 y 1")
    if item.value_per_share_marginal is not None and _decimal(item.value_per_share_marginal) is None:
        problems.append("value_per_share_marginal no es un número")
    return problems


class ValueDriverService:
    """Almacén por tenant del inventario de impulsores de valor."""

    def validate(self, item: ValueDriverItem) -> list[str]:
        return validate_item(item)

    # ------------------------------------------------------------------ lectura
    def current(self, db: Session, *, company_id: int, tenant_id: int) -> dict[str, ValueDriver]:
        """Filas vigentes por ``driver_key`` del tenant y la empresa."""
        tenant = _require_tenant(tenant_id, db)
        rows = db.scalars(
            select(ValueDriver)
            .where(
                ValueDriver.tenant_id == tenant,
                ValueDriver.company_id == company_id,
                ValueDriver.superseded_at.is_(None),
            )
            .order_by(ValueDriver.driver_key)
        ).all()
        return {row.driver_key: row for row in rows}

    def history(self, db: Session, *, company_id: int, tenant_id: int, driver_key: str) -> list[ValueDriver]:
        tenant = _require_tenant(tenant_id, db)
        return list(
            db.scalars(
                select(ValueDriver)
                .where(
                    ValueDriver.tenant_id == tenant,
                    ValueDriver.company_id == company_id,
                    ValueDriver.driver_key == driver_key,
                )
                .order_by(ValueDriver.id)
            ).all()
        )

    def check_publication(
        self,
        db: Session,
        *,
        company_id: int,
        tenant_id: int,
        market_cap_usd: float | Decimal | None = None,
    ) -> PublicationCheck:
        rows = self.current(db, company_id=company_id, tenant_id=tenant_id).values()
        return publication_check(rows, market_cap_usd=market_cap_usd)

    # ------------------------------------------------------------------ escritura
    def upsert(
        self,
        db: Session,
        *,
        company: Company,
        tenant_id: int,
        item: ValueDriverItem,
        now: datetime | None = None,
    ) -> UpsertResult:
        tenant = _require_tenant(tenant_id, db)
        item = normalize_item(item)
        problems = self.validate(item)
        if problems:
            raise ValueDriverError(problems)
        existing = self.current(db, company_id=company.id, tenant_id=tenant).get(item.driver_key)
        if existing is not None:
            if item.treatment == UNTREATED and (existing.treatment or UNTREATED) != UNTREATED:
                item = replace(
                    item,
                    treatment=existing.treatment,
                    model_link=existing.model_link,
                    reason_if_not_valued=existing.reason_if_not_valued,
                    value_per_share_marginal=existing.value_per_share_marginal,
                )
            if self._content(as_item(existing)) == self._content(item):
                return UpsertResult(existing, False, "unchanged")
            existing.superseded_at = now or datetime.now(UTC)
            db.flush()
        row = ValueDriver(
            tenant_id=tenant,
            company_id=company.id,
            driver_key=item.driver_key,
            category=item.category,
            name=(item.name or "").strip(),
            status=item.status,
            economics=dict(item.economics),
            timing=_clean(item.timing),
            source_url=_clean(item.source_url),
            source_quote=_clean(item.source_quote),
            source_type=item.source_type,
            document_id=item.document_id,
            evidence=item.evidence,
            as_of=item.as_of,
            headline=bool(item.headline),
            treatment=item.treatment,
            model_link=_clean(item.model_link),
            reason_if_not_valued=_clean(item.reason_if_not_valued),
            value_per_share_marginal=_decimal(item.value_per_share_marginal),
            confidence=_decimal(item.confidence),
            fingerprint=item.fingerprint,
            metadata_=dict(item.metadata),
        )
        db.add(row)
        db.flush()
        return UpsertResult(row, True, "replaced" if existing is not None else "created")

    def upsert_many(
        self,
        db: Session,
        *,
        company: Company,
        tenant_id: int,
        items: Iterable[ValueDriverItem],
        now: datetime | None = None,
    ) -> list[UpsertResult]:
        """Guarda un inventario entero o nada: valida todo antes de escribir."""
        items = [normalize_item(i) for i in items]
        problems: list[str] = []
        seen: set[str] = set()
        for item in items:
            problems.extend(f"{item.driver_key}: {p}" for p in self.validate(item))
            if item.driver_key in seen:
                problems.append(f"{item.driver_key}: clave repetida en el inventario")
            seen.add(item.driver_key)
        if problems:
            raise ValueDriverError(problems)
        return [self.upsert(db, company=company, tenant_id=tenant_id, item=i, now=now) for i in items]

    def retire(
        self,
        db: Session,
        *,
        company_id: int,
        tenant_id: int,
        driver_key: str,
        now: datetime | None = None,
    ) -> bool:
        """Baja: la fila vigente queda como histórico (``superseded_at``)."""
        row = self.current(db, company_id=company_id, tenant_id=tenant_id).get(driver_key)
        if row is None:
            return False
        row.superseded_at = now or datetime.now(UTC)
        db.flush()
        return True

    # ------------------------------------------------------------------ internos
    @staticmethod
    def _content(item: ValueDriverItem) -> tuple[Any, ...]:
        return (
            item.category,
            (item.name or "").strip(),
            item.status,
            dict(item.economics or {}),
            _clean(item.timing),
            _clean(item.source_url),
            _clean(item.source_quote),
            item.source_type,
            item.document_id,
            item.evidence,
            item.as_of,
            bool(item.headline),
            item.treatment,
            _clean(item.model_link),
            _clean(item.reason_if_not_valued),
            _decimal(item.value_per_share_marginal),
            _decimal(item.confidence),
            item.fingerprint,
            dict(item.metadata or {}),
        )


__all__ = [
    "BLOCK_REASON",
    "COMMITTED_STATUSES",
    "MATERIALITY_SHARE_OF_MARKET_CAP",
    "OFFICIAL_SOURCE_TYPES",
    "RUMOR_SOURCE_TYPES",
    "DriverBlock",
    "PublicationCheck",
    "UpsertResult",
    "ValueDriverError",
    "ValueDriverItem",
    "ValueDriverService",
    "as_item",
    "is_material",
    "normalize_item",
    "publication_check",
    "validate_item",
]
