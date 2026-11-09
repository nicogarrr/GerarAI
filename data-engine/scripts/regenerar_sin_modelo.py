"""Regeneraciones SIN MODELO de lo que guardan las fichas cuando cambian las reglas o los datos del código.

Nada de esto llama a un modelo de pago: solo código y fuentes gratis. Pensado para correrlo en
prod tras un despliegue (o en local contra una copia de la base).

Uso:
  python scripts/regenerar_sin_modelo.py sotp [--dry-run] [--tenant N] [TICKER ...]
      Rehace la «propuesta de los agentes» del desglose por partes con su clasificación guardada y
      las anclas y reglas de hoy (acciones vigentes, caja + inversiones a corto, deuda, precio,
      divisa de cada ancla). Guarda una versión nueva solo si el cálculo cambia; 0 llamadas al modelo.
  python scripts/regenerar_sin_modelo.py consenso [--dry-run] [--tenant N] [TICKER ...]
      Congela de nuevo el consenso propio (claves de ejercicio de 52/53 semanas por mes nominal) y
      lista las fotos viejas cuya clave ya no corresponde a su cierre (no se borran: quedan como
      historia; la medición de aciertos usa la clave nueva).
  python scripts/regenerar_sin_modelo.py filiales-uk [--dry-run] [--tenant N] TICKER ...
      Vuelve a recoger las cuentas de las filiales británicas (Companies House, con la regla de PSC
      de #4962) y encola su lectura. Necesita COMPANIES_HOUSE_API_KEY y el worker (cola de documentos).
      Con --dry-run solo lista las empresas que se procesarían: no recoge nada ni encola nada.

Sin TICKER: sotp = todas las empresas con propuesta de los agentes; consenso = la watchlist del tenant.
Sale un JSON con el antes/después por empresa.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models.entities import Company  # noqa: E402


def _args(argv: list[str]) -> tuple[str, list[str], bool, int | None]:
    if not argv or argv[0] not in ("sotp", "consenso", "filiales-uk"):
        raise SystemExit(__doc__)
    cmd, rest = argv[0], argv[1:]
    tenant = None
    if "--tenant" in rest:
        i = rest.index("--tenant")
        tenant = int(rest[i + 1])
        rest = rest[:i] + rest[i + 2:]
    dry = "--dry-run" in rest
    tickers = [a.upper() for a in rest if not a.startswith("--")]
    return cmd, tickers, dry, tenant


def _sotp_targets(db: Any, tickers: list[str], tenant: int | None) -> list[tuple[int, Company]]:
    from app.models.declared_input_value import DeclaredInputValue
    from app.services.user_sotp_service import AGENTS_SEGMENT, SOTP_INPUT_KEY

    q = (select(DeclaredInputValue.tenant_id, DeclaredInputValue.company_id)
         .where(DeclaredInputValue.input_key == SOTP_INPUT_KEY, DeclaredInputValue.segment_key == AGENTS_SEGMENT)
         .distinct().execution_options(include_all_tenants=True))
    pairs = sorted({(t, c) for t, c in db.execute(q).all() if t is not None and (tenant is None or t == tenant)})
    out = []
    for t, cid in pairs:
        company = db.get(Company, cid)
        if company is not None and (not tickers or company.ticker.upper() in tickers):
            out.append((int(t), company))
    return out


def _watchlist(db: Any, tenant: int) -> list[Company]:
    from app.models import WatchItem

    symbols = [w.symbol for w in db.scalars(select(WatchItem).where(WatchItem.tenant_id == tenant)
                                            .execution_options(include_all_tenants=True)).all()]
    return list(db.scalars(select(Company).where(Company.ticker.in_(symbols or ["-"]))).all())


def _companies(db: Any, tickers: list[str]) -> list[Company]:
    return list(db.scalars(select(Company).where(Company.ticker.in_(tickers or ["-"]))).all())


def run_sotp(db: Any, tickers: list[str], dry: bool, tenant: int | None) -> dict[str, Any]:
    from app.services.expert_team.sotp_valuer import recompute_saved_proposal

    out: dict[str, Any] = {}
    for t, company in _sotp_targets(db, tickers, tenant):
        db.info["tenant_id"] = t
        try:
            res = recompute_saved_proposal(db, company, dry_run=dry)
        except Exception as exc:  # noqa: BLE001 - una empresa no para a las demás
            db.rollback()
            res = {"ticker": company.ticker, "status": "error", "problems": [type(exc).__name__]}
        out[f"{t}:{company.ticker}"] = res
    return out


def stale_consensus_keys(frozen: list[Any], cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fotos congeladas cuya clave ya no es la del cierre que guardan (p. ej. fy2026 → fy2025 en un
    ejercicio de 52/53 semanas que cierra a primeros de mes)."""
    by_end = {(c.get("metric"), c.get("period_end")): c.get("key") for c in cells if c.get("period_end")}
    out = []
    for row in frozen:
        key = str(row.input_key or "")
        parts = key.split(".")
        if len(parts) != 3 or parts[0] != "estimate":
            continue
        end = (row.metadata_ or {}).get("period_end")
        now_key = by_end.get((parts[1], end))
        if now_key and now_key != key:
            out.append({"row_id": row.id, "key": key, "period_end": end, "current_key": now_key,
                        "as_of": row.as_of.isoformat() if row.as_of else None})
    return out


def run_consenso(db: Any, tickers: list[str], dry: bool, tenant: int | None) -> dict[str, Any]:
    from app.models.declared_input_value import DeclaredInputValue
    from app.services.estimate_accuracy import freeze_consensus
    from app.services.own_consensus import build_company_consensus

    t = tenant or 1
    db.info["tenant_id"] = t
    companies = _companies(db, tickers) if tickers else _watchlist(db, t)
    out: dict[str, Any] = {}
    for company in companies:
        try:
            result = build_company_consensus(db, company, t)
            frozen = list(db.scalars(select(DeclaredInputValue).where(
                DeclaredInputValue.company_id == company.id, DeclaredInputValue.tenant_id == t,
                DeclaredInputValue.input_key.like("estimate.%"))).all())
            stale = stale_consensus_keys(frozen, list(result.get("cells") or []))
            stats = None
            if not dry:
                with db.begin_nested():
                    stats = freeze_consensus(db, company, t, result)
                db.commit()
            out[company.ticker] = {"frozen": stats, "stale_keys": stale}
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            out[company.ticker] = {"status": "error", "problems": [type(exc).__name__]}
    return out


def run_filiales_uk(db: Any, tickers: list[str], tenant: int | None, dry: bool = False) -> dict[str, Any]:
    from app.core.config import get_settings
    from app.services.thesis_evidence_service import ThesisEvidenceService

    if not getattr(get_settings(), "companies_house_api_key", None):
        return {"status": "skipped", "reason": "sin COMPANIES_HOUSE_API_KEY (apagado)"}
    if not tickers:
        raise SystemExit("filiales-uk necesita los tickers (p. ej. FFH.TO CGEO.L)")
    db.info["tenant_id"] = tenant or 1
    companies = _companies(db, tickers)
    if dry:
        return {
            c.ticker: {
                "status": "dry_run",
                "accion": "se recogerian las cuentas de las filiales UK y se encolaria su lectura"
                " (con --dry-run no se recoge ni se encola nada)",
            }
            for c in companies
        }
    service = ThesisEvidenceService()
    return {c.ticker: service._uk_subsidiary_reports(db, c) for c in companies}  # noqa: SLF001


def main(argv: list[str]) -> None:
    cmd, tickers, dry, tenant = _args(argv)
    db = SessionLocal()
    try:
        if cmd == "sotp":
            out = run_sotp(db, tickers, dry, tenant)
        elif cmd == "consenso":
            out = run_consenso(db, tickers, dry, tenant)
        else:
            out = run_filiales_uk(db, tickers, tenant, dry)
        print(json.dumps({"command": cmd, "dry_run": dry, "result": out}, ensure_ascii=False, indent=1, default=str))
    finally:
        db.close()


if __name__ == "__main__":
    main(sys.argv[1:])
