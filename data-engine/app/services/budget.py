from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import BudgetUsage

# Planning rates in EUR per million tokens, keyed by the EXACT model id.
# These are internal planning estimates, not provider tariffs: OpenCode Go bills
# by subscription and several aliases carry cost_basis="unknown".
PLANNING_RATES_EUR_PER_MTOK: dict[str, tuple[float, float]] = {
    "deepseek-v4-flash": (0.10, 0.40),
    "qwen3.7-plus": (0.60, 1.80),
    "glm-5.2": (0.80, 2.40),
}
# One rate for any model not in the table, so an unrecognised or newly added
# model cannot be priced 10x too high and exhaust the daily cap.
DEFAULT_PLANNING_RATES = (0.10, 0.40)


def _rates_for(model: str) -> tuple[float, float]:
    """Resolve (input, output) EUR-per-Mtok for a model id.

    Registry first, so a list price recorded in the database wins; then the
    exact-match table; then the single planning default.
    """
    from app.llm.model_aliases import MODEL_ALIASES

    alias = MODEL_ALIASES.get(model)
    if alias is not None and alias.has_known_costs:
        return float(alias.input_cost), float(alias.output_cost)
    return PLANNING_RATES_EUR_PER_MTOK.get(model, DEFAULT_PLANNING_RATES)


class BudgetExceededError(RuntimeError):
    pass


class BudgetController:
    def __init__(self) -> None:
        self.settings = get_settings()

    def current_usage(self, db: Session, *, admin: bool = False) -> dict:
        today = date.today()
        # BudgetUsage es TenantOwnedMixin, asi que el agregado filtra por
        # tenant. Medido en SQLAlchemy 2.1.6: `db.scalar(select(sum(...)))`
        # de una sola columna SI dispara el with_loader_criteria de
        # app/core/database.py; el predicado explicito queda como segunda
        # capa y fail-closed. Sin ninguna de las dos capas el total era
        # GLOBAL: un solo tenant podia agotar el tope diario de todos los
        # demas, y ningun tenant podia ver su propio consumo.
        tenant_id = db.info.get("tenant_id")
        if tenant_id is None and not admin:
            # Falla cerrado: sin tenant el agregado seria GLOBAL y can_spend
            # dejaria que un tenant sin contexto consumiera el tope de todos.
            # Solo una vista de operacion consciente pide admin=True.
            raise RuntimeError(
                "BudgetController.current_usage requiere contexto de tenant "
                "(db.info['tenant_id']); pasa admin=True solo desde vistas de "
                "operacion conscientes de que el agregado es global"
            )
        tenant_filter = (
            [] if tenant_id is None else [BudgetUsage.tenant_id == tenant_id]
        )
        daily = db.scalar(
            select(func.coalesce(func.sum(BudgetUsage.cost_eur), 0)).where(
                BudgetUsage.usage_date == today,
                *tenant_filter,
            )
        )
        month_start = today.replace(day=1)
        if today.month == 12:
            next_month = today.replace(year=today.year + 1, month=1, day=1)
        else:
            next_month = today.replace(month=today.month + 1, day=1)
        monthly = db.scalar(
            select(func.coalesce(func.sum(BudgetUsage.cost_eur), 0)).where(
                BudgetUsage.usage_date >= month_start,
                BudgetUsage.usage_date < next_month,
                *tenant_filter,
            )
        )
        return {
            "daily_cost_eur": float(daily or 0),
            "monthly_cost_eur": float(monthly or 0),
            "daily_cap_eur": self.settings.llm_daily_cap_eur,
            "monthly_cap_eur": self.settings.llm_monthly_cap_eur,
            "tenant_scoped": tenant_id is not None,
        }

    def can_spend(self, db: Session, estimated_cost_eur: float) -> bool:
        # Con clave propia el coste no es de GerarAI: los topes EUR no aplican
        # (el usuario paga su factura). El proveedor sigue fail-closed si la
        # fila esta corrupta o le falta la clave.
        from app.llm.tenant_config import current_tenant_llm_config

        tenant_llm = current_tenant_llm_config()
        if (
            tenant_llm is not None
            and tenant_llm.billing_scope == "tenant"
            and tenant_llm.error is None
            and tenant_llm.enabled
            and tenant_llm.has_api_key
        ):
            return True
        # Decision consciente de contexto: con tenant, el tope es por tenant
        # (un tenant no puede agotar el de los demas). Sin contexto de tenant
        # (sesiones anonimas, scripts admin, tests de servicio), el tope actua
        # como cortacircuitos GLOBAL del despliegue: es el contexto admin y se
        # pide explicitamente.
        usage = self.current_usage(db, admin=db.info.get("tenant_id") is None)
        return (
            usage["daily_cost_eur"] + estimated_cost_eur <= self.settings.llm_daily_cap_eur
            and usage["monthly_cost_eur"] + estimated_cost_eur <= self.settings.llm_monthly_cap_eur
        )

    def record(
        self,
        db: Session,
        model: str,
        workflow: str,
        cost_eur: float,
        tokens: int,
        *,
        commit: bool = True,
    ) -> None:
        from app.llm.tenant_config import current_tenant_llm_config

        tenant_llm = current_tenant_llm_config()
        billed_cost = (
            0.0
            if tenant_llm is not None and tenant_llm.billing_scope == "tenant"
            else cost_eur
        )
        db.add(
            BudgetUsage(
                usage_date=date.today(),
                model=model,
                workflow=workflow,
                cost_eur=Decimal(str(billed_cost)),
                token_count=tokens,
            )
        )
        if commit:
            db.commit()

    @staticmethod
    def estimate_cost_eur(model: str, input_tokens: int, output_tokens: int) -> float:
        """Conservative internal estimates; provider invoices remain authoritative.

        Rates come from the model alias registry when the registry knows them,
        and otherwise from an exact-match table plus ONE documented planning
        rate.

        The previous substring matching ("flash" in model) missed the actual
        default model entirely, so every call was priced at 1.00/3.00 instead of
        the cheap-model tier: a 9.7x overcharge that exhausted the daily cap
        roughly ten times early and turned BudgetExceededError into a silent
        deterministic fallback the operator could not explain.

        A single planning rate for unknown models is deliberate: a wide spread
        between "cheapest known" and "most expensive known" is not conservatism,
        it is a pricing error that blocks the feature it is supposed to protect.
        """
        input_rate, output_rate = _rates_for(model)
        return round(
            input_tokens / 1_000_000 * input_rate
            + output_tokens / 1_000_000 * output_rate,
            8,
        )
