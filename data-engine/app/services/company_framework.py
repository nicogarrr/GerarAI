"""Company-specific research frameworks for the long-term model.

The framework is a routing decision, not an investment conclusion. It tells the
research engine which drivers and modules deserve attention for a company and
which market-opportunity method should be used. Missing inputs remain explicit.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models import Company
from app.services.company_types import is_holding_company_type


@dataclass(frozen=True)
class CompanyFramework:
    key: str
    label: str
    primary_question: str
    market_opportunity_mode: str
    revenue_drivers: tuple[str, ...]
    kpis: tuple[str, ...]
    unit_economics: tuple[str, ...]
    segment_model: tuple[str, ...]
    binding_constraints: tuple[str, ...]
    active_modules: tuple[str, ...]
    required_fact_metrics: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "primary_question": self.primary_question,
            "market_opportunity_mode": self.market_opportunity_mode,
            "revenue_drivers": list(self.revenue_drivers),
            "kpis": list(self.kpis),
            "unit_economics": list(self.unit_economics),
            "segment_model": list(self.segment_model),
            "binding_constraints": list(self.binding_constraints),
            "active_modules": list(self.active_modules),
            "required_fact_metrics": list(self.required_fact_metrics),
        }


COMMON_MODULES = (
    "historical_review",
    "forward_operating_model",
    "quality_of_growth",
    "capital_allocation",
    "reverse_dcf",
    "timeline",
    "what_must_be_true",
)


FRAMEWORKS: dict[str, CompanyFramework] = {
    "space_network": CompanyFramework(
        key="space_network",
        label="Space network / connectivity",
        primary_question="Can physical network capacity, monetization and funding support the revenue ramp?",
        market_opportunity_mode="required",
        revenue_drivers=("addressable_subscribers", "penetration", "monthly_arpu", "revenue_share", "satellites", "capacity_per_satellite", "utilization", "price_per_gb"),
        kpis=("satellites", "launch_cadence", "coverage", "mno_agreements", "cash_burn", "dilution", "runway"),
        unit_economics=("subscribers × ARPU × revenue share", "satellites × capacity × utilization × price"),
        segment_model=("connectivity", "government_or_defense", "other"),
        binding_constraints=("capacity", "launch_cadence", "funding", "regulation", "MNO_monetization"),
        active_modules=COMMON_MODULES + ("market_opportunity", "unit_economics", "segment_model", "macro_sensitivity"),
        required_fact_metrics=("addressable_subscribers", "penetration", "monthly_arpu", "revenue_share", "satellites", "capacity_per_satellite", "utilization", "price_per_gb"),
    ),
    "space_defense": CompanyFramework(
        key="space_defense",
        label="Space and defense platform",
        primary_question="Does backlog convert into a profitable, scalable space systems and launch business?",
        market_opportunity_mode="required",
        revenue_drivers=("launches", "price_per_launch", "backlog", "backlog_conversion", "space_systems_units", "price_per_unit"),
        kpis=("backlog", "launch_cadence", "gross_margin", "defense_contracts", "capex", "R&D"),
        unit_economics=("launches × price per launch", "units × price per unit"),
        segment_model=("launch", "space_systems", "defense"),
        binding_constraints=("launch_execution", "capacity", "capital", "contract_timing", "competition"),
        active_modules=COMMON_MODULES + ("market_opportunity", "unit_economics", "segment_model", "macro_sensitivity"),
        required_fact_metrics=("launches", "price_per_launch", "backlog", "backlog_conversion"),
    ),
    "platform": CompanyFramework(
        key="platform",
        label="Platform / marketplace",
        primary_question="Can engagement, volume and take rate compound without losing quality or share?",
        market_opportunity_mode="required",
        revenue_drivers=("active_accounts", "transactions_per_account", "tpv", "take_rate", "bookings", "trips", "revenue_per_trip"),
        kpis=("active_accounts", "churn", "retention", "tpv", "take_rate", "customer_acquisition_cost", "contribution_margin"),
        unit_economics=("TPV × take rate", "customers × usage × monetization"),
        segment_model=("core_platform", "adjacent_products", "geography"),
        binding_constraints=("competition", "pricing", "churn", "regulation", "distribution"),
        active_modules=COMMON_MODULES + ("market_opportunity", "unit_economics", "segment_model", "macro_sensitivity"),
        required_fact_metrics=("active_accounts", "tpv", "take_rate", "churn", "retention"),
    ),
    "advertising_platform": CompanyFramework(
        key="advertising_platform",
        label="Advertising / attention platform",
        primary_question="Can ad impressions, price per ad and daily engagement compound advertising revenue without eroding the user experience?",
        market_opportunity_mode="required",
        # Drivers que la propia empresa desglosa en resultados (Meta, Q4/FY2025,
        # investor.atmeta.com): «Ad impressions delivered across our Family of
        # Apps» (+18% Q4 / +12% FY2025 interanual), «Average price per ad»
        # (+6% Q4 / +9% FY2025) y «Family daily active people (DAP)» (3,58 mil
        # millones en dic-2025, +7%). Los valores absolutos de impresiones y
        # precio por anuncio NO se desglosan (solo variaciones interanuales),
        # así que ninguno es exigible como fact: exigirlos recrearía la demanda
        # imposible que esta corrección elimina (TPV/take_rate/churn de un
        # negocio de pagos aplicado a publicidad).
        revenue_drivers=("ad_impressions", "price_per_ad", "daily_active_people", "family_arpu"),
        kpis=("daily_active_people", "family_arpu", "ad_impressions_yoy", "price_per_ad_yoy", "operating_margin", "capex", "reality_labs_operating_loss"),
        unit_economics=("ad impressions × average price per ad", "DAP × Family ARPU"),
        segment_model=("family_of_apps", "reality_labs", "geography"),
        binding_constraints=("engagement", "ad_load_ceiling", "privacy_regulation", "competition_attention", "ai_capex"),
        active_modules=COMMON_MODULES + ("market_opportunity", "unit_economics", "segment_model", "macro_sensitivity"),
        required_fact_metrics=(),
    ),
    "subscriber": CompanyFramework(
        key="subscriber",
        label="Subscriber / recurring revenue",
        primary_question="Can subscriber growth, retention and ARPU support durable FCF and reinvestment?",
        market_opportunity_mode="recommended",
        revenue_drivers=("subscribers", "active_accounts", "penetration", "monthly_arpu", "churn", "retention"),
        kpis=("subscribers", "net_adds", "churn", "retention", "ARPU", "content_or_marketing_spend"),
        unit_economics=("subscribers × monthly ARPU × 12",),
        segment_model=("subscription", "advertising", "geography", "product_tier"),
        binding_constraints=("churn", "content_or_marketing_cost", "competition", "pricing", "regulation"),
        active_modules=COMMON_MODULES + ("market_opportunity", "unit_economics", "segment_model", "macro_sensitivity"),
        required_fact_metrics=("subscribers", "monthly_arpu", "churn", "retention"),
    ),
    "software_ai": CompanyFramework(
        key="software_ai",
        label="Software / AI platform",
        primary_question="Can seats, usage, pricing and retention grow faster than compute and go-to-market costs?",
        market_opportunity_mode="recommended",
        revenue_drivers=("customers", "seats", "arpu", "arr", "usage", "price", "retention"),
        kpis=("ARR", "net_revenue_retention", "gross_retention", "RPO", "cloud_cost", "R&D", "SBC"),
        unit_economics=("customers × seats × ARPU", "ARR × retention × expansion"),
        segment_model=("subscription", "consumption", "services", "geography"),
        binding_constraints=("competition", "AI_disruption", "cloud_cost", "distribution", "regulation"),
        active_modules=COMMON_MODULES + ("market_opportunity", "unit_economics", "segment_model", "macro_sensitivity"),
        required_fact_metrics=("customers", "arr", "retention", "arpu", "cloud_cost"),
    ),
    "capacity_infrastructure": CompanyFramework(
        key="capacity_infrastructure",
        label="Capacity / infrastructure",
        primary_question="Can capacity, utilization and pricing earn an acceptable return on heavy investment?",
        market_opportunity_mode="required",
        revenue_drivers=("capacity_units", "utilization", "price_per_unit", "power_capacity", "customers"),
        kpis=("capacity", "utilization", "price", "power_cost", "capex", "funding", "ROIC"),
        unit_economics=("capacity × utilization × price",),
        segment_model=("capacity", "services", "geography"),
        binding_constraints=("capital", "power", "supply_chain", "utilization", "funding"),
        active_modules=COMMON_MODULES + ("market_opportunity", "unit_economics", "segment_model", "macro_sensitivity"),
        required_fact_metrics=("capacity_units", "utilization", "price_per_unit", "capex"),
    ),
    "holding_asset_manager": CompanyFramework(
        key="holding_asset_manager",
        label="Holding company / asset manager",
        primary_question="Can the asset base compound NAV and cash earnings through disciplined capital allocation?",
        market_opportunity_mode="reinvestment_runway",
        revenue_drivers=("aum", "fee_rate", "fee_related_earnings", "asset_value", "cash_yield"),
        kpis=("fee_related_earnings", "AUM", "inflows", "carry", "holdco_debt", "NAV", "buybacks"),
        unit_economics=("AUM × fee rate", "asset value × ownership × realization"),
        segment_model=("asset_management", "wealth_solutions", "operating_businesses", "real_estate", "infrastructure", "holdco_debt"),
        binding_constraints=("rates", "asset_values", "capital_allocation", "complexity", "liquidity"),
        active_modules=COMMON_MODULES + ("market_opportunity", "segment_model", "macro_sensitivity", "sotp"),
        required_fact_metrics=("aum", "fee_rate", "nav", "holdco_debt", "asset_value"),
    ),
    "bank": CompanyFramework(
        key="bank",
        label="Bank / deposit franchise",
        primary_question="Can the deposit franchise earn returns above its cost of equity through the credit cycle?",
        market_opportunity_mode="recommended",
        revenue_drivers=("loan_growth", "deposit_growth", "net_interest_margin", "fee_income", "cost_of_deposits"),
        kpis=("return_on_tangible_equity", "cet1_ratio", "nonperforming_loan_ratio", "net_charge_off_rate", "efficiency_ratio", "tangible_book_value"),
        unit_economics=("earning assets × net interest margin", "tangible book × sustainable ROTE"),
        segment_model=("consumer_banking", "commercial_banking", "wealth", "markets"),
        binding_constraints=("credit_losses", "funding_cost", "capital_requirements", "liquidity", "rate_sensitivity"),
        active_modules=COMMON_MODULES + ("credit_cycle", "capital_adequacy", "residual_income", "macro_sensitivity"),
        required_fact_metrics=("tangible_book_value", "shares_diluted", "return_on_tangible_equity", "cost_of_equity", "net_interest_margin", "cet1_ratio"),
    ),
    "insurer": CompanyFramework(
        key="insurer",
        label="Insurance underwriter",
        primary_question="Can underwriting discipline and investment returns compound book value above the cost of equity?",
        market_opportunity_mode="recommended",
        revenue_drivers=("earned_premiums", "premium_growth", "combined_ratio", "investment_income", "retention"),
        kpis=("combined_ratio", "loss_ratio", "expense_ratio", "reserve_development", "roe", "book_value_per_share"),
        unit_economics=("earned premium × underwriting margin", "float × investment yield"),
        segment_model=("underwriting_lines", "geography", "investment_portfolio"),
        binding_constraints=("catastrophe_losses", "reserve_adequacy", "pricing_cycle", "capital", "investment_yield"),
        active_modules=COMMON_MODULES + ("underwriting_cycle", "reserve_quality", "book_value_model", "macro_sensitivity"),
        required_fact_metrics=("book_value", "shares_diluted", "roe", "cost_of_equity", "combined_ratio"),
    ),
    "reit": CompanyFramework(
        key="reit",
        label="REIT / property owner",
        primary_question="Can same-store NOI and accretive investment outgrow financing and cap-rate pressure?",
        market_opportunity_mode="recommended",
        revenue_drivers=("occupied_area", "occupancy", "rent_per_area", "same_store_noi_growth", "development_pipeline"),
        kpis=("net_operating_income", "occupancy", "same_store_noi_growth", "affo_per_share", "cap_rate", "net_debt_to_ebitda"),
        unit_economics=("occupied area × rent", "NOI ÷ capitalization rate"),
        segment_model=("property_type", "geography", "development", "joint_ventures"),
        binding_constraints=("interest_rates", "refinancing", "cap_rates", "occupancy", "development_cost"),
        active_modules=COMMON_MODULES + ("reit_nav", "same_store_growth", "lease_maturity", "macro_sensitivity"),
        required_fact_metrics=("net_operating_income", "cap_rate", "net_debt", "shares_diluted", "occupancy"),
    ),
    "commodity": CompanyFramework(
        key="commodity",
        label="Commodity / royalty / resource",
        primary_question="What is the normalized cash return across price, volume, reserves and reinvestment cycles?",
        market_opportunity_mode="recommended",
        revenue_drivers=("production_volume", "commodity_price", "realized_price", "royalty_rate", "reserve_life"),
        kpis=("production", "realized_price", "all_in_cost", "reserves", "reserve_life", "royalty_revenue", "NOI"),
        unit_economics=("volume × realized price", "tons × royalty per ton"),
        segment_model=("resource", "royalty", "land", "rental_income"),
        binding_constraints=("commodity_price", "reserves", "permitting", "cost_curve", "reinvestment"),
        active_modules=COMMON_MODULES + ("market_opportunity", "unit_economics", "segment_model", "macro_sensitivity"),
        required_fact_metrics=("production_volume", "realized_price", "all_in_cost", "reserve_life"),
    ),
    "biotech_pre_fcf": CompanyFramework(
        key="biotech_pre_fcf",
        label="Biotech / AI-biology pre-FCF",
        primary_question="Can the pipeline or platform reach durable revenue before the cash runway and dilution capacity run out?",
        market_opportunity_mode="recommended",
        revenue_drivers=("revenue", "collaboration_revenue", "product_revenue", "milestones", "pipeline_stage"),
        kpis=("revenue", "cash_burn", "cash_and_investments", "runway", "dilution", "pipeline_stage", "partner_dependence"),
        unit_economics=("reported_revenue_only",),
        segment_model=("reported_segments", "product", "collaboration"),
        binding_constraints=("funding", "clinical_or_technical_validation", "regulation", "partner_dependence", "dilution"),
        active_modules=COMMON_MODULES + ("market_opportunity", "segment_model", "macro_sensitivity"),
    ),
    "generic_fcf": CompanyFramework(
        key="generic_fcf",
        label="FCF compounder",
        primary_question="Can organic growth, margins and reinvestment compound owner earnings at attractive returns?",
        market_opportunity_mode="recommended",
        revenue_drivers=("revenue", "price", "volume", "mix", "organic_growth"),
        kpis=("organic_growth", "gross_margin", "FCF_margin", "ROIC", "share_count", "working_capital"),
        unit_economics=("revenue × normalized margin",),
        segment_model=("reported_segments", "geography", "product"),
        binding_constraints=("market_size", "competition", "pricing", "reinvestment", "management"),
        active_modules=COMMON_MODULES + ("market_opportunity", "segment_model", "macro_sensitivity"),
    ),
}


def resolve_company_framework(company: Company) -> CompanyFramework:
    """Resolve a framework using explicit company identity before broad tags."""
    ticker = company.ticker.upper()
    company_type = (company.company_type or "").lower()
    model = (company.valuation_model or "").lower()
    tags = set(company.factor_tags or [])

    explicit_tickers = {
        "ASTS": "space_network",
        "RKLB": "space_defense",
        "META": "advertising_platform",
        "PYPL": "platform",
        "UBER": "platform",
        "HIMS": "subscriber",
        "IBRX": "biotech_pre_fcf",
        "NAUT": "biotech_pre_fcf",
        "RXRX": "biotech_pre_fcf",
        "ABCL": "biotech_pre_fcf",
        "NFLX": "subscriber",
        "NBIS": "capacity_infrastructure",
        "IREN": "capacity_infrastructure",
        "BN": "holding_asset_manager",
        "BABA": "holding_asset_manager",
        "KKR": "holding_asset_manager",
        "CB": "insurer",
        "CPT": "reit",
        "CCJ": "commodity",
        "FRPH": "commodity",
    }
    if ticker in explicit_tickers:
        return FRAMEWORKS[explicit_tickers[ticker]]
    if "biotech" in company_type or "biotech" in tags:
        return FRAMEWORKS["biotech_pre_fcf"]
    if "bank" in company_type or "bank" in model:
        return FRAMEWORKS["bank"]
    if "insur" in company_type or "insur" in model:
        return FRAMEWORKS["insurer"]
    if "reit" in company_type or "reit" in model or "real_estate_nav" in model:
        return FRAMEWORKS["reit"]
    # Señal por industria (Finnhub profile / maestro) cuando el company_type
    # no decide: asigna el MARCO de tesis correcto (drivers/KPIs). El motor de
    # valoración solo cambia para los tickers verificados de registry.py.
    # Reglas del auditor: "broker" excluido de insurer (AON/MMC son brokers,
    # no aseguradoras) y "real estate" genérico NO es REIT (CBRE, Zillow son
    # servicios/desarrollo, no vehículos de FFO/AFFO).
    industry = (getattr(company, "industry", None) or "").lower()
    if "insur" in industry and "broker" not in industry:
        return FRAMEWORKS["insurer"]
    if "reit" in industry:
        return FRAMEWORKS["reit"]
    if "asset management" in industry:
        return FRAMEWORKS["holding_asset_manager"]
    if "bank" in industry:
        return FRAMEWORKS["bank"]

    if is_holding_company_type(company_type) or "sotp" in model:
        return FRAMEWORKS["holding_asset_manager"]
    if "commodity" in tags or "mining" in company_type or "uranium" in company_type or "royalty" in company_type:
        return FRAMEWORKS["commodity"]
    if "subscriber" in tags or "subscriber" in company_type:
        return FRAMEWORKS["subscriber"]
    if "platform" in tags or "marketplace" in company_type:
        return FRAMEWORKS["platform"]
    if "infra" in tags or "capacity" in company_type:
        return FRAMEWORKS["capacity_infrastructure"]
    if "software" in tags or "ai" in tags or "cloud" in tags:
        return FRAMEWORKS["software_ai"]
    if "space" in tags or "defense" in tags:
        return FRAMEWORKS["space_defense"]
    return FRAMEWORKS["generic_fcf"]
