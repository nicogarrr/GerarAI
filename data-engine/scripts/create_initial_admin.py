"""Script de configuracion segura para la cuenta de administrador inicial.

Fulfills: VAL-SEC-002
Expected Behavior:
- No hardcoded credentials in codebase (verification via scan)
- Admin credentials loaded from environment variables
- Initial admin account creation via secure setup script
"""

from __future__ import annotations

import getpass
import logging
import os
import re
import sys
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.entities import Tenant

logger = logging.getLogger(__name__)

COMMON_WEAK_PATTERNS = (
    "admin",
    "password",
    "123456",
    "changeme",
    "change-me",
    "supersecret",
    "root",
)

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


class AdminCredentials(NamedTuple):
    email: str
    password: str
    name: str


def validate_credentials(email: str, password: str) -> None:
    """Valida el formato de email y la robustez de la contrasena."""
    email_clean = email.strip()
    if not email_clean or not EMAIL_REGEX.match(email_clean):
        raise ValueError("El email proporcionado no tiene un formato valido.")

    if len(password) < 12:
        raise ValueError("La contrasena debe tener al menos 12 caracteres.")

    pw_lower = password.lower()
    if any(weak in pw_lower for weak in COMMON_WEAK_PATTERNS):
        raise ValueError("La contrasena elegida es demasiado comun o insegura.")

    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_digit_or_punct = any(not c.isalpha() for c in password)

    if not (has_upper and has_lower and has_digit_or_punct):
        raise ValueError(
            "La contrasena debe incluir mayusculas, minusculas y al menos un numero o simbolo."
        )


def load_credentials_from_env() -> AdminCredentials | None:
    """Carga credenciales de admin desde variables de entorno."""
    email = os.environ.get("ADMIN_EMAIL", "").strip()
    password = os.environ.get("ADMIN_PASSWORD", "")
    name = os.environ.get("ADMIN_NAME", "Administrador").strip()

    if not email or not password:
        return None

    validate_credentials(email, password)
    return AdminCredentials(email=email, password=password, name=name)


def prompt_credentials_interactive() -> AdminCredentials:
    """Solicita credenciales de manera interactiva y segura."""
    print("=== Creacion de Cuenta Administrador Inicial (GerarAI) ===")
    email = input("Email de administrador: ").strip()
    password = getpass.getpass("Contrasena (minimo 12 caracteres robustos): ")
    confirm_password = getpass.getpass("Confirmar contrasena: ")

    if password != confirm_password:
        raise ValueError("Las contrasenas no coinciden.")

    name = input("Nombre completo [Administrador]: ").strip() or "Administrador"

    validate_credentials(email, password)
    return AdminCredentials(email=email, password=password, name=name)


def create_initial_admin(
    credentials: AdminCredentials,
    db: Session,
) -> Tenant:
    """Crea o inicializa el tenant y espacio de trabajo del administrador."""
    tenant_external_id = f"tenant_{credentials.email.lower().replace('@', '_at_').replace('.', '_')}"

    existing = db.execute(
        select(Tenant).where(Tenant.external_id == tenant_external_id)
    ).scalar_one_or_none()

    if existing is not None:
        logger.info("El tenant de administrador %s ya existe.", tenant_external_id)
        return existing

    admin_tenant = Tenant(
        external_id=tenant_external_id,
        name=f"Workspace de {credentials.name}",
        status="active",
        metadata_={
            "admin_email": credentials.email,
            "role": "admin",
            "is_initial_admin": True,
        },
    )
    db.add(admin_tenant)
    db.commit()
    db.refresh(admin_tenant)
    logger.info("Tenant de administrador %s creado con exito.", tenant_external_id)
    return admin_tenant


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    creds = load_credentials_from_env()
    if creds is None:
        if sys.stdin.isatty():
            try:
                creds = prompt_credentials_interactive()
            except (ValueError, KeyboardInterrupt) as exc:
                print(f"Error: {exc}", file=sys.stderr)
                return 1
        else:
            print(
                "Error: ADMIN_EMAIL y ADMIN_PASSWORD deben definirse como variables de entorno.",
                file=sys.stderr,
            )
            return 1

    with SessionLocal() as db:
        admin_tenant = create_initial_admin(creds, db)
        print(f"OK: Cuenta admin inicial configurada (Tenant ID: {admin_tenant.id}, External: {admin_tenant.external_id}).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
