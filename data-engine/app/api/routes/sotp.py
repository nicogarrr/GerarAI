"""Desglose por partes (SOTP) editable: GET/PUT/DELETE /valuation/{ticker}/sotp."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.ui_errors import ui_error
from app.schemas.sotp import SotpModelIn
from app.services.company_resolver import resolve_company
from app.services.user_sotp_service import UserSotpService

router = APIRouter()


def _context(db: Session, ticker: str):
    tenant = db.info.get("tenant_id")
    if tenant is None:
        raise HTTPException(status_code=403, detail=ui_error(401, "user_context_required").detail)
    company = resolve_company(db, ticker)
    if company is None:
        raise HTTPException(status_code=404, detail=ui_error(404, "company_not_found_dot").detail)
    return company, int(tenant)


@router.get("/{ticker}/sotp")
def get_user_sotp(
    ticker: str,
    db: Session = Depends(get_db),
    variant: str | None = Query(default=None, pattern="^(agents|user|example)$"),
) -> dict:
    """Desglose por partes con su aritmética, escenarios, sensibilidad y la tasa base
    medida. Versiones: la propuesta de los agentes (por defecto en cuanto existe), la
    editada por el usuario (si es posterior) y el ejemplo de código del ticker.
    Supuestos no validados: no es el valor justo de GerarAI."""
    company, tenant = _context(db, ticker)
    out = UserSotpService().read(db, company, tenant, variant=variant)
    # Cifras con pagina de las cuentas britanicas escaneadas ya leidas por el worker (solo cache).
    out["companies_house"] = companies_house_scanned(company.ticker)
    return out


def companies_house_scanned(ticker: str) -> list[dict]:
    """Por sociedad: cifras validadas (pagina, linea literal, unidades, periodo) y motivo de lo descartado."""
    from app.services import scanned_accounts

    rows = []
    for item in scanned_accounts.for_ticker(ticker):
        doc = item.get("document_url")
        rows.append({
            "company_name": item.get("company_name"), "company_number": item.get("company_number"),
            "made_up_to": item.get("made_up_to"), "document_url": doc, "status": item.get("status"),
            "reason": item.get("reason"), "page_count": item.get("page_count"),
            "checks": item.get("checks") or {},
            "figures": [{**{k: f.get(k) for k in ("metric", "label", "value", "unit", "currency", "period_end",
                                                   "page", "line", "basis", "check")},
                         "page_url": scanned_accounts.page_url(doc, f.get("page"))}
                        for f in item.get("figures") or []],
            "rejected": [{k: f.get(k) for k in ("metric", "page", "reason")} for f in item.get("rejected") or []],
        })
    return rows


@router.post("/{ticker}/sotp/generate", status_code=202)
def generate_agents_sotp(ticker: str, db: Session = Depends(get_db)) -> dict:
    """«Generar con expertos»: encola el valorador SOTP del equipo (job en segundo plano)."""
    from app.services import sotp_agents_job

    company, _tenant = _context(db, ticker)
    run, created = sotp_agents_job.enqueue(db, company.ticker)
    return {"job": sotp_agents_job.job_payload(run), "created": created}


@router.get("/{ticker}/sotp/jobs/latest")
def latest_agents_sotp_job(ticker: str, db: Session = Depends(get_db)) -> dict:
    """Estado honesto del último «Generar con expertos» (sin ETA)."""
    from app.services import sotp_agents_job

    company, _tenant = _context(db, ticker)
    return {"job": sotp_agents_job.job_payload(sotp_agents_job.latest_run(db, company.ticker))}


@router.put("/{ticker}/sotp")
def put_user_sotp(ticker: str, model: SotpModelIn, db: Session = Depends(get_db)) -> dict:
    """Guarda una versión nueva del desglose (la anterior queda en el histórico)."""
    company, tenant = _context(db, ticker)
    try:
        return UserSotpService().save(db, company, tenant, model.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/{ticker}/sotp", status_code=204)
def delete_user_sotp(ticker: str, db: Session = Depends(get_db)) -> None:
    company, tenant = _context(db, ticker)
    UserSotpService().delete(db, company, tenant)
