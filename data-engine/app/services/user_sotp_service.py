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
#: Segmentos de la misma clave: el modelo del usuario ("") y la propuesta de los agentes.
USER_SEGMENT = ""
AGENTS_SEGMENT = "agents"

USER_ASSUMPTIONS_LABEL = "Supuestos del usuario, no validados contra histórico"
AGENTS_ASSUMPTIONS_LABEL = "Propuesta de los agentes expertos: supuestos no validados contra histórico"
EXAMPLE_LABEL = "Ejemplo pegado por Nico"

#: Versiones que puede pedir la ficha (?variant=…).
SOTP_VARIANTS = ("agents", "user", "example")

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


def _envelope(db: Session, company: Company, model: dict, *, origin: str, saved: dict | None,
              label: str = USER_ASSUMPTIONS_LABEL) -> dict:
    price, price_currency, price_as_of = _price(db, company)
    # El % frente al precio solo vale en la misma divisa.
    comparable = price if (price_currency and price_currency == model.get("currency")) else None
    result = run_user_sotp(model, price=comparable)
    return {
        "ticker": company.ticker,
        "available": True,
        "origin": origin,  # "saved" | "agents" | "example"
        "label": label,
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

    def _rows(self, db: Session, company: Company, tenant_id: int) -> dict[str, DeclaredInputValue]:
        current = self.inputs.current(db, company_id=company.id, tenant_id=tenant_id, keys=[SOTP_INPUT_KEY])
        return {segment: row for (key, segment), row in current.items() if key == SOTP_INPUT_KEY}

    def _row(self, db: Session, company: Company, tenant_id: int) -> DeclaredInputValue | None:
        return self._rows(db, company, tenant_id).get(USER_SEGMENT)

    @staticmethod
    def _model_of(row: DeclaredInputValue | None) -> dict | None:
        if row is None:
            return None
        model, problems = normalize_user_sotp((row.metadata_ or {}).get("model"))
        return None if problems else model

    def variants(self, db: Session, company: Company, tenant_id: int) -> tuple[dict, str | None]:
        """Versiones disponibles y cuál se enseña por defecto.

        Por defecto: la propuesta de los agentes en cuanto existe; el modelo del
        usuario solo si es POSTERIOR a ella (lo editó después); si no hay
        ninguna de las dos, el ejemplo de código del ticker.
        """
        rows = self._rows(db, company, tenant_id)
        agents_row, user_row = rows.get(AGENTS_SEGMENT), rows.get(USER_SEGMENT)
        agents_model, user_model = self._model_of(agents_row), self._model_of(user_row)
        example = SOTP_EXAMPLES.get((company.ticker or "").upper())
        example_model = None
        if example is not None:
            model, problems = normalize_user_sotp(example)
            example_model = None if problems else model
        found = {
            "agents": (agents_row, agents_model) if agents_model is not None else None,
            "user": (user_row, user_model) if user_model is not None else None,
            "example": (None, example_model) if example_model is not None else None,
        }
        default = None
        if found["agents"] and found["user"]:
            a, u = agents_row, user_row
            default = "user" if (u.created_at and a.created_at and u.created_at > a.created_at) or (
                u.id > a.id and not (u.created_at and a.created_at)) else "agents"
        elif found["agents"]:
            default = "agents"
        elif found["user"]:
            default = "user"
        elif found["example"]:
            default = "example"
        return found, default

    @staticmethod
    def _variant_summary(key: str, entry) -> dict:
        labels = {"agents": "Propuesta de los agentes", "user": "Editado por ti", "example": EXAMPLE_LABEL}
        out = {"key": key, "label": labels[key], "available": entry is not None}
        if entry is not None and entry[0] is not None:
            row = entry[0]
            meta = row.metadata_ or {}
            out["saved_at"] = row.created_at.isoformat() if row.created_at else None
            out["generated_at"] = meta.get("generated_at")
            out["price"] = meta.get("price")
            out["price_as_of"] = meta.get("price_as_of")
            out["value_per_share"] = float(row.base) if row.base is not None else None
        return out

    def read(self, db: Session, company: Company, tenant_id: int, variant: str | None = None) -> dict:
        found, default = self.variants(db, company, tenant_id)
        chosen = variant if variant in SOTP_VARIANTS and found.get(variant) else default
        listing = [self._variant_summary(k, found.get(k)) for k in SOTP_VARIANTS]
        agents_status = latest_agents_attempt(db, company)
        if chosen is None:
            return {"ticker": company.ticker, "available": False, "label": USER_ASSUMPTIONS_LABEL,
                    "validated": False, "base_rate": _base_rate(db, company), "variant": None,
                    "default_variant": None, "variants": listing, "agents_status": agents_status}
        row, model = found[chosen]
        if chosen == "agents":
            meta = row.metadata_ or {}
            history = self.inputs.history(db, company_id=company.id, tenant_id=tenant_id,
                                          input_key=SOTP_INPUT_KEY, segment_key=AGENTS_SEGMENT)
            out = _envelope(db, company, model, origin="agents", label=AGENTS_ASSUMPTIONS_LABEL, saved={
                "row_id": row.id,
                "saved_at": row.created_at.isoformat() if row.created_at else None,
                "versions": len(history),
            })
            out["agents_stability"] = agents_stability(history)
            out["agents"] = {k: meta.get(k) for k in (
                "generated_at", "price", "price_currency", "price_as_of", "thesis_version_id", "trigger", "prompt_version",
                "rules_version", "cache_hit", "readings", "readings_differ", "changed_by")}
            out["agents"]["fingerprint"] = (meta.get("fingerprint") or {}).get("hash")
            out["agents"]["narrative"] = _rendered_narrative(meta.get("narrative"), model, out.get("result"))
            out["agents"]["mostly_cash"] = _mostly_cash(out.get("result"))
        elif chosen == "user":
            out = _envelope(db, company, model, origin="saved", saved={
                "row_id": row.id,
                "saved_at": row.created_at.isoformat() if row.created_at else None,
                "versions": len(self.inputs.history(db, company_id=company.id, tenant_id=tenant_id,
                                                    input_key=SOTP_INPUT_KEY)),
            })
        else:
            out = _envelope(db, company, model, origin="example", saved=None)
            out["example_label"] = EXAMPLE_LABEL
        out.update({"variant": chosen, "default_variant": default, "variants": listing,
                    "agents_status": agents_status})
        return out

    def save_agents(self, db: Session, company: Company, tenant_id: int, model: dict, *, meta: dict) -> DeclaredInputValue:
        """Guarda la propuesta de los agentes como una versión más (segmento ``agents``)."""
        model, problems = normalize_user_sotp(model)
        if not model.get("currency"):
            if company.currency:
                model["currency"] = str(company.currency).upper()
            else:
                problems.append("falta la divisa del modelo")
        if problems:
            raise ValueError("; ".join(problems))
        result = run_user_sotp(model)
        outcome = self.inputs.upsert(
            db,
            company=company,
            tenant_id=tenant_id,
            item=DeclaredInput(
                input_key=SOTP_INPUT_KEY,
                segment_key=AGENTS_SEGMENT,
                low=None,
                base=Decimal(str(round(result["value_per_share"], 6))),
                high=None,
                unit=f"{model['currency']}/acción",
                method="manual",
                source_quote=(model.get("source") or None),
                as_of=datetime.now(UTC).date(),
                model_family="sotp_agents",
                input_set_version=USER_SOTP_VERSION,
                metadata={"model": model, "origin": "agents", **meta},
            ),
        )
        db.commit()
        return outcome.row

    def save(self, db: Session, company: Company, tenant_id: int, raw: dict) -> dict:
        """Guarda el modelo del usuario (segmento ""); pasa a ser el de por defecto por ser el más nuevo."""
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
        return self.read(db, company, tenant_id, variant="user")

    def delete(self, db: Session, company: Company, tenant_id: int) -> bool:
        done = self.inputs.retire(db, company_id=company.id, tenant_id=tenant_id, input_key=SOTP_INPUT_KEY)
        db.commit()
        return done


#: Dos propuestas seguidas de los agentes que difieren más que esto: «resultado sensible a supuestos».
AGENTS_UNSTABLE_CHANGE = 0.30


#: Si la caja menos deuda pesa más que esto en el total, la ficha lo dice en grande.
MOSTLY_CASH_SHARE = 0.5


def _mostly_cash(result: dict | None) -> dict | None:
    """Cuánto del $/acción es caja menos deuda de hoy (no negocio): aviso si pasa de la mitad."""
    if not result or not result.get("value_per_share") or result["value_per_share"] <= 0:
        return None
    cash = sum(r.get("value_per_share") or 0.0 for r in result.get("rows") or []
               if str(r.get("name") or "").startswith("Caja menos deuda"))
    share = cash / result["value_per_share"]
    if cash <= 0 or share <= MOSTLY_CASH_SHARE:
        return None
    return {"cash_per_share": cash, "value_per_share": result["value_per_share"], "share": share}


def _rendered_narrative(narrative: dict | None, model: dict, result: dict | None) -> dict | None:
    """Secciones con los marcadores sustituidos por las cifras del cálculo de AHORA (nunca del modelo)."""
    from app.services.expert_team.sotp_narrative import SECTIONS, render_narrative, sotp_markers

    if not narrative or not narrative.get("sections") or not result:
        return None
    rendered = render_narrative(narrative["sections"], sotp_markers(model, result))
    return {
        "status": narrative.get("status"),
        "version": narrative.get("version"),
        "sections": [{"key": key, "title": title, "text": rendered.get(key) or ""}
                     for key, title in SECTIONS if rendered.get(key)],
    }


def _rules_of(row: DeclaredInputValue) -> tuple:
    meta = row.metadata_ or {}
    return (meta.get("rules_version"), meta.get("prompt_version"))


def agents_stability(history: list[DeclaredInputValue]) -> dict | None:
    """Compara la propuesta vigente con la anterior de los agentes (mismo tenant y empresa).

    None si solo hay una. ``unstable`` cuando el valor por acción cambia más de un 30 %
    (o cambia de signo): la cifra depende de la corrida, no solo de los datos.
    """
    rows = [r for r in history if r.base is not None]
    if not rows:
        return None
    # Solo se comparan propuestas con las mismas reglas y el mismo prompt (otro diseño no es «otra corrida»).
    same = [r for r in rows if _rules_of(r) == _rules_of(rows[-1])]
    rows = same
    if len(rows) < 2:
        return None
    previous, current = float(rows[-2].base), float(rows[-1].base)
    change = (current / previous - 1.0) if previous else None
    unstable = previous * current <= 0 or change is None or abs(change) > AGENTS_UNSTABLE_CHANGE
    return {
        "previous_value_per_share": previous,
        "previous_generated_at": (rows[-2].metadata_ or {}).get("generated_at"),
        "current_value_per_share": current,
        "change": change,
        "unstable": unstable,
        "threshold": AGENTS_UNSTABLE_CHANGE,
    }


def latest_agents_attempt(db: Session, company: Company) -> dict | None:
    """Último intento del valorador SOTP (botón o tesis) de este tenant, para decir por qué no hay propuesta."""
    from app.models.entities import WorkflowRun
    from app.services.sotp_agents_job import WORKFLOW_NAME as SOTP_WORKFLOW
    from app.services.thesis_job_service import WORKFLOW_NAME as THESIS_WORKFLOW

    try:
        runs = db.scalars(
            select(WorkflowRun)
            .where(WorkflowRun.workflow_name.in_((SOTP_WORKFLOW, THESIS_WORKFLOW)),
                   WorkflowRun.input_payload["ticker"].as_string() == (company.ticker or "").upper())
            .order_by(desc(WorkflowRun.id))
            .limit(10)
        ).all()
    except Exception:  # noqa: BLE001 - solo informativo
        return None
    for run in runs:
        if run.workflow_name == SOTP_WORKFLOW:
            result = dict(run.result_payload or {})
            return {"source": "button", "run_id": run.id, "job_status": run.status,
                    "status": result.get("status"), "problems": result.get("problems") or [],
                    "finished_at": run.finished_at.isoformat() if run.finished_at else None}
        sotp = (run.result_payload or {}).get("sotp_agents")
        if isinstance(sotp, dict):
            return {"source": "thesis", "run_id": run.id, "job_status": run.status,
                    "status": sotp.get("status"), "problems": sotp.get("problems") or [],
                    "finished_at": run.finished_at.isoformat() if run.finished_at else None}
    return None
