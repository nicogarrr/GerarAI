from sqlalchemy import select

from app.core.database import SessionLocal, init_db
from app.data.company_master import COMPANY_MASTER
from app.models import Company


def upsert_company(db, payload: dict) -> Company:
    company = db.scalar(select(Company).where(Company.ticker == payload["ticker"]))
    if company is None:
        company = Company(**payload)
        db.add(company)
        db.flush()
    else:
        for key, value in payload.items():
            setattr(company, key, value)
    return company


def ensure_company_master() -> None:
    db = SessionLocal()
    try:
        for payload in COMPANY_MASTER:
            upsert_company(db, payload)
        db.commit()
    finally:
        db.close()


STUB_TYPE = "research_candidate"
STUB_MODEL = "unassigned"
TAXONOMY_FIELDS = (
    "company_type",
    "valuation_model",
    "special_sources",
    "special_risks",
    "factor_tags",
)

# Filas placeholder con identidad sin verificar: las crea el buscador/ensure
# (research_candidate) o la importacion IBKR (imported_holding). Ambas son
# placeholders del mismo tipo: el maestro verificado manda sobre ellas.
STUB_COMPANY_PAIRS = frozenset(
    {(STUB_TYPE, STUB_MODEL), ("imported_holding", STUB_MODEL)}
)
# Identidad que el maestro tiene verificada y el stub deja en placeholder
# (p.ej. KRKNF en prod: sector "Unknown" -> framework/equivalencias mal
# resueltos). La divisa NUNCA se toca aqui: el USD por defecto del stub no es
# marcador de placeholder y cambiarla alteraria la valoracion de posiciones.
_PLACEHOLDER = {"", "unknown", "sin dato"}
IDENTITY_FIELDS = ("name", "exchange", "sector", "industry", "ir_url", "cik")


def _is_placeholder(value) -> bool:
    return value is None or str(value).strip().lower() in _PLACEHOLDER


def apply_master_taxonomy_to_stubs(db) -> list[str]:
    """Completa taxonomia e identidad de fichas stub desde el maestro.

    En produccion el seed completo no corre, asi que un ticker del maestro que
    se creo como stub (research_candidate/unassigned o importado de IBKR como
    imported_holding/unassigned) nunca recibia su motor de valoracion ni su
    sector/industry verificados. Solo se tocan stubs sin asignar: una ficha
    con modelo o tipo ya decididos no se sobrescribe, y de la identidad solo
    se rellenan campos en placeholder ("Unknown", vacio, nombre=ticker); un
    dato real de otra fuente no se pisa. No crea empresas ni toca carteras.
    """
    updated: list[str] = []
    for payload in COMPANY_MASTER:
        company = db.scalar(select(Company).where(Company.ticker == payload["ticker"]))
        if company is None:
            continue
        pair = ((company.company_type or ""), (company.valuation_model or ""))
        if pair not in STUB_COMPANY_PAIRS:
            continue
        for key in TAXONOMY_FIELDS:
            if key in payload:
                setattr(company, key, payload[key])
        for key in IDENTITY_FIELDS:
            if key not in payload:
                continue
            current = getattr(company, key, None)
            # El nombre por defecto del stub es el propio ticker.
            if key == "name" and str(current or "").strip().upper() == company.ticker.upper():
                current = None
            if _is_placeholder(current):
                setattr(company, key, payload[key])
        updated.append(company.ticker)
    return updated


def seed() -> None:
    """Install only the global company taxonomy; user data is never seeded."""
    init_db()
    ensure_company_master()


if __name__ == "__main__":
    seed()
    print("Seed complete: company taxonomy loaded; no user portfolio or evidence was created.")
