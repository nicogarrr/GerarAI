"""Desglose por partes (SOTP) editable por el usuario: lectura, guardado y honestidad.

Almacén sin migración: una fila de ``declared_input_values`` por (tenant,
empresa) con ``input_key='sotp_user_model'``, ``method='manual'``,
``status='manual'``; el modelo entero va en ``metadata`` y ``base`` guarda el
valor por acción calculado. Guardar otra versión deja la anterior como
histórico (``superseded_at``), como cualquier input declarado. Ningún motor ni
el valor justo leen esta clave (solo las claves que cada uno conoce, y solo
``method='analyst'``): es una herramienta del usuario, no una valoración de
GerarAI.

Al lado de la cifra se muestra SIEMPRE lo medido en el histórico para
empresas que queman caja (``app.valuation.cash_burn_base_rate``), con
``applies`` diciendo si esta empresa quema caja, y la etiqueta «supuestos del
usuario, no validados contra histórico».
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.data.sotp_examples import SOTP_EXAMPLES
from app.models import Company, FinancialFact
from app.models.declared_input_value import DeclaredInputValue
from app.services.declared_input_service import DeclaredInput, DeclaredInputService
from app.valuation.sotp import USER_SOTP_VERSION, normalize_user_sotp, run_user_sotp

SOTP_INPUT_KEY = "sotp_user_model"

USER_ASSUMPTIONS_LABEL = "Supuestos del usuario, no validados contra histórico"

def _base_rate(db: Session, company: Company) -> dict:
    """Tasa base medida de las empresas que queman caja (dca-valor-4), siempre visible.

    ``applies`` dice si ESTA empresa quema caja en su último ejercicio (beneficio
    neto y flujo operativo negativos, la misma regla del backtest); None = sin datos.
    """
    from types import SimpleNamespace

    from app.valuation import cash_burn_base_rate as cbr

    facts = db.scalars(
        select(FinancialFact).where(
            FinancialFact.company_id == company.id,
            FinancialFact.metric.in_(("net_income", "operating_cash_flow")),
            FinancialFact.fiscal_year.is_not(None),
        ).order_by(desc(FinancialFact.created_at))
    ).all()
    seen: set[tuple[str, int]] = set()
    rows = []
    for fact in facts:  # el más nuevo de cada (métrica, ejercicio)
        key = (fact.metric, int(fact.fiscal_year))
        if key in seen or fact.value is None:
            continue
        seen.add(key)
        rows.append(SimpleNamespace(metric=fact.metric, year=fact.fiscal_year, value=fact.value))
    latest = cbr.latest_fiscal_year_values(rows)
    applies = cbr.burns_cash(latest) if latest else None
    line = cbr.cash_burn_base_rate(latest or {"net_income": -1.0, "operating_cash_flow": -1.0}, {"value": 1.0}) or {}
    return {
        "applies": applies,
        "fiscal_year": latest.get("fiscal_year") if latest else None,
        "cases": cbr.CASES,
        "median_return_24m": cbr.MEDIAN_RETURN_24M,
        "fell_over_half_24m_share": cbr.FELL_OVER_HALF_24M_SHARE,
        "doubled_24m_share": cbr.DOUBLED_24M_SHARE,
        "beat_spy_24m_share": cbr.BEAT_SPY_24M_SHARE,
        "stopped_filing_24m_share": cbr.STOPPED_FILING_24M_SHARE,
        "message_es": line.get("message_es"),
        "message_en": line.get("message_en"),
    }


def _price(db: Session, company: Company) -> tuple[float | None, str | None, str | None]:
    try:
        from app.services.valuation_service import resolve_model_price

        price = resolve_model_price(db, company.id)
    except Exception:  # noqa: BLE001 - sin precio el desglose sigue, sin % frente al precio
        return None, None, None
    if price is None:
        return None, None, None
    return price.value, price.currency, price.as_of.isoformat() if price.as_of else None


def _envelope(db: Session, company: Company, model: dict, *, origin: str, saved: dict | None) -> dict:
    price, price_currency, price_as_of = _price(db, company)
    # El % frente al precio solo vale en la misma divisa.
    comparable = price if (price_currency and price_currency == model.get("currency")) else None
    result = run_user_sotp(model, price=comparable)
    return {
        "ticker": company.ticker,
        "available": True,
        "origin": origin,  # "saved" | "example"
        "label": USER_ASSUMPTIONS_LABEL,
        "validated": False,
        "model": model,
        "result": result,
        "price": price,
        "price_currency": price_currency,
        "price_as_of": price_as_of,
        "base_rate": _base_rate(db, company),
        "saved": saved,
    }


class UserSotpService:
    def __init__(self) -> None:
        self.inputs = DeclaredInputService()

    def _row(self, db: Session, company: Company, tenant_id: int) -> DeclaredInputValue | None:
        return self.inputs.current(db, company_id=company.id, tenant_id=tenant_id, keys=[SOTP_INPUT_KEY]).get(
            (SOTP_INPUT_KEY, "")
        )

    def read(self, db: Session, company: Company, tenant_id: int) -> dict:
        row = self._row(db, company, tenant_id)
        if row is not None:
            model, problems = normalize_user_sotp((row.metadata_ or {}).get("model"))
            if not problems:
                history = self.inputs.history(db, company_id=company.id, tenant_id=tenant_id, input_key=SOTP_INPUT_KEY)
                return _envelope(db, company, model, origin="saved", saved={
                    "row_id": row.id,
                    "saved_at": row.created_at.isoformat() if row.created_at else None,
                    "versions": len(history),
                })
        example = SOTP_EXAMPLES.get((company.ticker or "").upper())
        if example is not None:
            model, problems = normalize_user_sotp(example)
            if not problems:
                return _envelope(db, company, model, origin="example", saved=None)
        return {"ticker": company.ticker, "available": False, "label": USER_ASSUMPTIONS_LABEL,
                "validated": False, "base_rate": _base_rate(db, company)}

    def save(self, db: Session, company: Company, tenant_id: int, raw: dict) -> dict:
        model, problems = normalize_user_sotp(raw)
        if not model.get("currency"):
            if company.currency:
                model["currency"] = str(company.currency).upper()
            else:
                problems.append("falta la divisa del modelo")
        if problems:
            raise ValueError("; ".join(problems))
        result = run_user_sotp(model)
        self.inputs.upsert(
            db,
            company=company,
            tenant_id=tenant_id,
            item=DeclaredInput(
                input_key=SOTP_INPUT_KEY,
                segment_key="",
                low=None,
                base=Decimal(str(round(result["value_per_share"], 6))),
                high=None,
                unit=f"{model['currency']}/acción",  # divisa ya resuelta arriba
                method="manual",
                source_quote=(model.get("source") or None),
                as_of=datetime.now(UTC).date(),
                model_family="sotp_user",
                input_set_version=USER_SOTP_VERSION,
                metadata={"model": model},
            ),
        )
        db.commit()
        return self.read(db, company, tenant_id)

    def delete(self, db: Session, company: Company, tenant_id: int) -> bool:
        done = self.inputs.retire(db, company_id=company.id, tenant_id=tenant_id, input_key=SOTP_INPUT_KEY)
        db.commit()
        return done
