"""Lectura y escritura de los datos del declarante (metadata del tenant, clave tax_declarant).

Solo se escriben las claves que el Modelo 720 lee y que este formulario cubre.
Las demás claves de tax_declarant (entidades depositarias, fechas de primera
adquisición...) se conservan intactas.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CashBalance, Company, Position, Tenant

KEY = "tax_declarant"
IDENTITY_FIELDS = ("nif", "apellidos_nombre", "numero_declaracion", "telefono")
_NIF = re.compile(r"^[A-Z0-9]{5,15}$")
_NUMERO = re.compile(r"^720\d{10}$")
_TELEFONO = re.compile(r"^\d{9,15}$")
_COUNTRY = re.compile(r"^[A-Z]{2}$")
_PARTIDA = re.compile(r"^(?:cash:[A-Z]{3}|[A-Z0-9][A-Z0-9.\-_]{0,29})$")


def _tenant(db: Session) -> Tenant:
    tenant_id = db.info.get("tenant_id")
    tenant = db.get(Tenant, tenant_id) if tenant_id is not None else None
    if tenant is None:
        raise PermissionError("Se necesita el contexto del usuario.")
    return tenant


def partidas(db: Session) -> list[str]:
    """Claves de custodia de las posiciones y cuentas actuales (ISIN o ticker, cash:DIVISA)."""
    keys: set[str] = set()
    for isin, ticker in db.execute(
        select(Company.isin, Company.ticker).join(Position, Position.company_id == Company.id)
    ):
        key = (isin or ticker or "").strip().upper()
        if key:
            keys.add(key)
    for currency in db.scalars(select(CashBalance.currency)):
        if currency and currency.strip():
            keys.add(f"cash:{currency.strip().upper()}")
    return sorted(keys)


def read(db: Session) -> dict:
    declarant = (_tenant(db).metadata_ or {}).get(KEY)
    declarant = declarant if isinstance(declarant, dict) else {}
    custody = declarant.get("custody")
    custody = custody if isinstance(custody, dict) else {}
    filed = declarant.get("filed_720_before")
    return {
        **{field: str(declarant.get(field) or "") for field in IDENTITY_FIELDS},
        "filed_720_before": filed if isinstance(filed, bool) else None,
        "custody": {
            str(k): str(v).strip().upper()
            for k, v in custody.items()
            if isinstance(v, str) and _COUNTRY.match(str(v).strip().upper())
        },
        "partidas": partidas(db),
    }


def write(db: Session, payload: dict) -> dict:
    """Valida y fusiona. Cadena vacía o null borra el campo; el resto de claves se conserva."""
    tenant = _tenant(db)
    current = (tenant.metadata_ or {}).get(KEY)
    declarant = dict(current) if isinstance(current, dict) else {}
    errors: list[str] = []

    rules = {
        "nif": (_NIF, "NIF no válido", True),
        "apellidos_nombre": (re.compile(r"^.{2,100}$"), "Apellidos y nombre no válidos", False),
        "numero_declaracion": (_NUMERO, "El número de declaración son 13 dígitos y empieza por 720", False),
        "telefono": (_TELEFONO, "Teléfono no válido", False),
    }
    for field, (pattern, message, upper) in rules.items():
        if field not in payload:
            continue
        value = str(payload[field] or "").strip()
        value = value.upper() if upper else value
        if not value:
            declarant.pop(field, None)
        elif pattern.match(value):
            declarant[field] = value
        else:
            errors.append(message)

    if "filed_720_before" in payload:
        value = payload["filed_720_before"]
        if value is None:
            declarant.pop("filed_720_before", None)
        elif isinstance(value, bool):
            declarant["filed_720_before"] = value
        else:
            errors.append("filed_720_before debe ser verdadero o falso")

    if "custody" in payload:
        raw = payload["custody"]
        known = set(partidas(db))
        merged = dict(declarant.get("custody") or {})
        if not isinstance(raw, dict):
            errors.append("custody debe ser un mapa partida a país")
        else:
            for key, country in raw.items():
                partida = str(key).strip()
                partida = "cash:" + partida[5:].upper() if partida.lower().startswith("cash:") else partida.upper()
                if not _PARTIDA.match(partida) or partida not in known:
                    errors.append(f"Partida desconocida: {key}")
                    continue
                value = str(country or "").strip().upper()
                if not value:
                    merged.pop(partida, None)
                elif _COUNTRY.match(value):
                    merged[partida] = value
                else:
                    errors.append(f"País no válido para {partida}")
        if merged:
            declarant["custody"] = merged
        else:
            declarant.pop("custody", None)

    if errors:
        raise ValueError("; ".join(errors))
    metadata = dict(tenant.metadata_ or {})
    metadata[KEY] = declarant
    tenant.metadata_ = metadata  # reasignar: el JSON no detecta mutaciones in situ
    db.commit()
    return read(db)
