"""Lectura y escritura de los datos del declarante (metadata del tenant, clave tax_declarant).

Solo se escriben las claves que el Modelo 720 lee y que este formulario cubre.
Las demás claves de tax_declarant (entidades depositarias, fechas de primera
adquisición...) se conservan intactas.
"""

from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.local_date import local_today
from app.core.tenancy import tenant_filters
from app.models import CashBalance, Company, Position, Tenant

KEY = "tax_declarant"
IDENTITY_FIELDS = ("nif", "apellidos_nombre", "numero_declaracion", "telefono")
_NIF = re.compile(r"^[A-Z0-9]{5,20}$")
# [0-9] y no \d: \d acepta dígitos Unicode («６００…», «٦٠٠…») que el campo
# numérico del fichero del 720 no admite.
_NUMERO = re.compile(r"^720[0-9]{10}$")
_TELEFONO = re.compile(r"^[0-9]{9,15}$")
_APELLIDOS_NOMBRE = re.compile(r"^[^\x00-\x1f\x7f]{2,100}$")
_COUNTRY = re.compile(r"^[A-Z]{2}$")
_ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}\d$")
ENTITY_REQUIRED = ("name", "nif", "street", "city", "zip", "country")
ENTITY_OPTIONAL = ("complement", "region")
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
        select(Company.isin, Company.ticker)
        .join(Position, Position.company_id == Company.id)
        .where(*tenant_filters(db, Position))
    ):
        key = (isin or ticker or "").strip().upper()
        if key:
            keys.add(key)
    for currency in db.scalars(
        select(CashBalance.currency).where(*tenant_filters(db, CashBalance))
    ):
        if currency and currency.strip():
            keys.add(f"cash:{currency.strip().upper()}")
    return sorted(keys)


def _read_entities(raw) -> dict[str, dict[str, str]]:
    if not isinstance(raw, dict):
        return {}
    return {
        str(key): {f: str(value.get(f) or "") for f in ENTITY_REQUIRED + ENTITY_OPTIONAL}
        for key, value in raw.items()
        if isinstance(value, dict)
    }


def _read_dates(raw) -> dict[str, str]:
    """Fechas guardadas como YYYYMMDD; se devuelven YYYY-MM-DD."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        digits = str(value).replace("-", "")
        if len(digits) == 8 and digits.isdigit():
            out[str(key)] = f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"
    return out


def _partida(key: str) -> str:
    key = str(key).strip()
    return "cash:" + key[5:].upper() if key.lower().startswith("cash:") else key.upper()


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
        "custody_entities": _read_entities(declarant.get("custody_entities")),
        "first_acquisition_dates": _read_dates(declarant.get("first_acquisition_dates")),
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
        "apellidos_nombre": (_APELLIDOS_NOMBRE, "Apellidos y nombre no válidos", False),
        "numero_declaracion": (_NUMERO, "El número de declaración son 13 dígitos y empieza por 720", False),
        "telefono": (_TELEFONO, "Teléfono no válido", False),
    }
    for field, (pattern, message, upper) in rules.items():
        if field not in payload:
            continue
        value = str(payload[field] or "").strip()
        value = value.upper() if upper else value
        if field == "nif" and value:
            if len(value) > 32 or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
                errors.append(message)
                continue
            value = re.sub(r"[^A-Z0-9]", "", value)
            if not value:
                errors.append(message)
                continue
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
                partida = _partida(key)
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

    known = set(partidas(db))
    custody_now = declarant.get("custody") or {}

    if "custody_entities" in payload:
        raw = payload["custody_entities"]
        merged_entities = dict(declarant.get("custody_entities") or {})
        if not isinstance(raw, dict):
            errors.append("custody_entities debe ser un mapa partida a entidad")
        else:
            for key, entity in raw.items():
                partida = _partida(key)
                if partida not in known:
                    errors.append(f"Partida desconocida: {key}")
                elif not entity or not any(str(v or "").strip() for v in entity.values()):
                    merged_entities.pop(partida, None)
                else:
                    clean = {f: str(entity.get(f) or "").strip() for f in ENTITY_REQUIRED + ENTITY_OPTIONAL}
                    clean["country"] = clean["country"].upper()
                    clean["nif"] = clean["nif"].upper()
                    missing = [f for f in ENTITY_REQUIRED if not clean[f]]
                    if missing:
                        errors.append(f"Entidad de {partida}: faltan {', '.join(missing)}")
                    elif not _COUNTRY.match(clean["country"]):
                        errors.append(f"Entidad de {partida}: país no válido")
                    elif custody_now.get(partida) and custody_now[partida] != clean["country"]:
                        errors.append(f"Entidad de {partida}: el país no coincide con la custodia")
                    else:
                        merged_entities[partida] = clean
        if merged_entities:
            declarant["custody_entities"] = merged_entities
        else:
            declarant.pop("custody_entities", None)

    if "first_acquisition_dates" in payload:
        raw = payload["first_acquisition_dates"]
        merged_dates = dict(declarant.get("first_acquisition_dates") or {})
        if not isinstance(raw, dict):
            errors.append("first_acquisition_dates debe ser un mapa ISIN a fecha")
        else:
            for key, value in raw.items():
                isin = _partida(key)
                text = str(value or "").strip()
                if isin not in known or not _ISIN.match(isin):
                    errors.append(f"ISIN desconocido: {key}")
                elif not text:
                    merged_dates.pop(isin, None)
                else:
                    try:
                        day = datetime.strptime(text, "%Y-%m-%d").date()
                    except ValueError:
                        errors.append(f"Fecha no válida para {isin}")
                        continue
                    if day > local_today():
                        errors.append(f"Fecha futura para {isin}")
                    else:
                        merged_dates[isin] = day.strftime("%Y%m%d")
        if merged_dates:
            declarant["first_acquisition_dates"] = merged_dates
        else:
            declarant.pop("first_acquisition_dates", None)

    if errors:
        raise ValueError("; ".join(errors))
    metadata = dict(tenant.metadata_ or {})
    metadata[KEY] = declarant
    tenant.metadata_ = metadata  # reasignar: el JSON no detecta mutaciones in situ
    db.commit()
    return read(db)
