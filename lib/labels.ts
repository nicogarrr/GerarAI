/**
 * Etiquetas visibles para valores que el backend codifica en inglés.
 *
 * El `value` de los <select>/query params DEBE seguir siendo la clave
 * inglesa (el backend la espera tal cual); lo que se traduce es solo lo que
 * el usuario lee. Compartido por el Screener y por los filtros de ProPicks,
 * que antes tenían dos listas de sectores distintas.
 *
 * Las etiquetas viven en los diccionarios (labels.*, patrón flow-text). El
 * código del backend puede llevar espacios o '&', que la forma de clave i18n
 * no admite: cada catálogo cruza código -> clave con su mapa *_CODES.
 */
import esLabels from './i18n/messages/es/labels.json' with { type: 'json' };
import enLabels from './i18n/messages/en/labels.json' with { type: 'json' };

// Uso por literal para el guard de i18n (claves consumidas por objeto).
export const LABELS_KEY_LITERALS = [
    'labels.sectors.technology',
    'labels.sectors.information_technology',
    'labels.sectors.healthcare',
    'labels.sectors.health_care',
    'labels.sectors.financial_services',
    'labels.sectors.financials',
    'labels.sectors.consumer_discretionary',
    'labels.sectors.consumer_cyclical',
    'labels.sectors.industrials',
    'labels.sectors.consumer_staples',
    'labels.sectors.energy',
    'labels.sectors.utilities',
    'labels.sectors.real_estate',
    'labels.sectors.materials',
    'labels.sectors.communication_services',
    'labels.sectors.media',
    'labels.sectors.unknown',
    'labels.industries.telecommunication',
    'labels.industries.telecommunications',
    'labels.industries.telecom_services',
    'labels.industries.satellite_telecom',
    'labels.industries.semiconductors',
    'labels.industries.software',
    'labels.industries.software_and_cloud',
    'labels.industries.application_software',
    'labels.industries.data_analytics_software',
    'labels.industries.enterprise_software',
    'labels.industries.marketing_software',
    'labels.industries.ai_infrastructure',
    'labels.industries.asset_management_and_holdings',
    'labels.industries.aerospace_and_defense',
    'labels.industries.biological_products_sic_2836',
    'labels.industries.laboratory_analytical_instruments_sic_3826',
    'labels.industries.china_ecommerce_and_cloud',
    'labels.industries.ecommerce_and_cloud',
    'labels.industries.digital_health',
    'labels.industries.gold_and_silver_mining',
    'labels.industries.industrial_connectivity_and_drones',
    'labels.industries.marine_robotics',
    'labels.industries.mobility_platform',
    'labels.industries.pharmaceutical_preparations_sic_2834',
    'labels.industries.pharmaceuticals',
    'labels.industries.social_platforms',
    'labels.industries.streaming_entertainment',
    'labels.industries.uranium_mining',
    'labels.industries.biotechnology',
    'labels.industries.banking',
    'labels.industries.banks',
    'labels.industries.insurance',
    'labels.industries.retail',
    'labels.industries.beverages',
    'labels.industries.media',
    'labels.industries.utilities',
    'labels.industries.aerospace_defense',
    'labels.industries.oil_gas',
    'labels.industries.real_estate',
    'labels.industries.automobiles',
    'labels.industries.consumer_electronics',
    'labels.industries.communications',
    'labels.industries.professional_services',
    'labels.industries.electrical_equipment',
    'labels.industries.communication_equipment',
    'labels.industries.electronic_components',
    'labels.industries.computer_hardware',
    'labels.industries.hardware',
    'labels.industries.information_technology_services',
    'labels.industries.internet_content_information',
    'labels.industries.specialty_retail',
    'labels.industries.auto_manufacturers',
    'labels.industries.drug_manufacturers',
    'labels.industries.medical_devices',
    'labels.industries.capital_markets',
    'labels.industries.asset_management',
    'labels.industries.credit_services',
    'labels.industries.entertainment',
    'labels.industries.gold',
    'labels.industries.copper',
    'labels.industries.steel',
    'labels.industries.chemicals',
    'labels.industries.machinery',
    'labels.industries.airlines',
    'labels.industries.restaurants',
    'labels.industries.solar',
    'labels.industries.uranium',
    'labels.industries.engineering_construction',
    'labels.industries.building_products',
    'labels.industries.packaged_foods',
    'labels.industries.semiconductor_equipment',
    'labels.industries.software_application',
    'labels.industries.software_infrastructure',
    'labels.sourceTiers.tier_1_regulatory',
    'labels.sourceTiers.tier_2_company',
    'labels.sourceTiers.tier_3_transcript',
    'labels.sourceTiers.tier_4_reputable_media',
    'labels.sourceTiers.tier_5_data_provider',
    'labels.sourceTiers.tier_6_bootstrap',
    'labels.sourceTiers.tier_7_user_input',
    'labels.sourceTiers.tier_8_social',
    'labels.sourceTiers.tier_unknown',
    'labels.impactDirections.positive',
    'labels.impactDirections.negative',
    'labels.impactDirections.neutral',
    'labels.impactDirections.mixed',
    'labels.eventTypes.regulatory',
    'labels.eventTypes.earnings',
    'labels.eventTypes.dilution',
    'labels.eventTypes.contract',
    'labels.eventTypes.capital_allocation',
    'labels.eventTypes.general_news',
    'labels.eventTypes.legal_solicitation',
    'labels.eventTypes.macro',
    'labels.eventTypes.opinion',
    'labels.eventTypes.unknown',
    'labels.attributionComponents.fundamental_growth',
    'labels.attributionComponents.multiple',
    'labels.attributionComponents.dividends',
    'labels.attributionComponents.buybacks',
    'labels.attributionComponents.dilution',
    'labels.attributionComponents.fx',
    'labels.attributionComponents.sizing',
    'labels.instrumentTypes.common_stock',
    'labels.instrumentTypes.preferred_stock',
    'labels.instrumentTypes.canadian_dr',
    'labels.instrumentTypes.adr',
    'labels.instrumentTypes.etf',
    'labels.instrumentTypes.etn',
    'labels.instrumentTypes.etp',
    'labels.instrumentTypes.reit',
    'labels.instrumentTypes.warrant',
    'labels.instrumentTypes.right',
    'labels.instrumentTypes.unit',
    'labels.instrumentTypes.public',
    'labels.macroThemes.gold_central_banks',
    'labels.macroThemes.interest_rates',
    'labels.macroThemes.commodities',
    'labels.macroThemes.trucking_freight',
    'labels.macroThemes.ai_investment',
    'labels.macroThemes.hormuz_oil',
    'labels.macroThemes.energy',
    'labels.macroThemes.semiconductors',
    'labels.macroThemes.dollar_fx',
    'labels.macroThemes.inflation',
    'labels.macroThemes.china_supply_chains',
    'labels.macroThemes.us_trade_policy',
    'labels.severities.critical',
    'labels.severities.high',
    'labels.severities.medium',
    'labels.severities.low',
    'labels.severities.info',
    'labels.factors.ads',
    'labels.factors.ai',
    'labels.factors.ai_biology',
    'labels.factors.auto',
    'labels.factors.biotech',
    'labels.factors.china',
    'labels.factors.cloud',
    'labels.factors.commodities',
    'labels.factors.cyclical',
    'labels.factors.defense',
    'labels.factors.drones',
    'labels.factors.ecommerce',
    'labels.factors.energy',
    'labels.factors.fcf',
    'labels.factors.financials',
    'labels.factors.glp1',
    'labels.factors.government',
    'labels.factors.growth',
    'labels.factors.healthcare',
    'labels.factors.infra',
    'labels.factors.media',
    'labels.factors.mining',
    'labels.factors.mobility',
    'labels.factors.optionality',
    'labels.factors.platform',
    'labels.factors.pre_fcf',
    'labels.factors.quality',
    'labels.factors.rates',
    'labels.factors.regulatory',
    'labels.factors.robotics',
    'labels.factors.semiconductors',
    'labels.factors.small_cap',
    'labels.factors.software',
    'labels.factors.sotp',
    'labels.factors.space',
    'labels.factors.speculative',
    'labels.factors.subscriber',
    'labels.factors.telecom',
    'labels.factors.uranium',
    'labels.companyTypes.ai_big_tech',
    'labels.companyTypes.ai_infra_capacity',
    'labels.companyTypes.asset_manager_holding',
    'labels.companyTypes.auto_energy_optionality',
    'labels.companyTypes.china_adr_holding',
    'labels.companyTypes.defense_contract_backlog',
    'labels.companyTypes.healthcare_regulatory',
    'labels.companyTypes.mining_pre_revenue',
    'labels.companyTypes.platform_fcf_compounder',
    'labels.companyTypes.software_ai_disruption',
    'labels.companyTypes.software_ai_platform',
    'labels.companyTypes.software_durable_growth',
    'labels.companyTypes.space_defense_growth',
    'labels.companyTypes.speculative_scenario',
    'labels.companyTypes.subscriber_media',
    'labels.companyTypes.uranium_mining',
    'labels.companyTypes.operating_company',
    'labels.companyTypes.research_candidate',
    'labels.companyTypes.fund',
    'labels.companyTypes.etf',
    'labels.companyTypes.trust',
    'labels.backendValues.unproven',
    'labels.backendValues.proven',
    'labels.backendValues.uncertain',
    'labels.backendValues.improving',
    'labels.backendValues.deteriorating',
    'labels.backendValues.strengthening',
    'labels.backendValues.weakening',
    'labels.backendValues.moderate',
    'labels.backendValues.durable',
    'labels.backendValues.insufficient_evidence',
    'labels.backendValues.insufficient_data',
    'labels.backendValues.primary_official',
    'labels.backendValues.wacc_policy',
    'labels.backendValues.damodaran',
    'labels.backendValues.model_policy',
    'labels.backendValues.calculated_metric',
    'labels.backendValues.financial_facts',
    'labels.backendValues.historical_case',
    'labels.backendValues.inferred_input',
    'labels.backendValues.manual_transcript',
    'labels.backendValues.manual_upload',
    'labels.backendValues.sec_filing',
    'labels.backendValues.earnings_call',
    'labels.backendValues.investor_relations',
    'labels.backendValues.transcript',
    'labels.backendValues.yfinance',
    'labels.backendValues.yahoo_fundamentals',
    'labels.backendValues.user',
    'labels.backendValues.chat',
    'labels.backendValues.url',
    'labels.backendValues.brand',
    'labels.backendValues.capital_barrier',
    'labels.misc.sectorNotAvailable',
    'labels.misc.reviewOpenOne',
    'labels.misc.reviewOpenMany',
    'labels.misc.alertOpenOne',
    'labels.misc.alertOpenMany',
    'labels.misc.adrRatio',
] as const;

const byCode = (codes: Record<string, string>, dict: Record<string, string>): Record<string, string> =>
  Object.fromEntries(Object.entries(codes).map(([code, key]) => [code, dict[key]]));

const SECTOR_CODES: Record<string, string> = {
  "Technology": 'technology',
  "Information Technology": 'information_technology',
  "Healthcare": 'healthcare',
  "Health Care": 'health_care',
  "Financial Services": 'financial_services',
  "Financials": 'financials',
  "Consumer Discretionary": 'consumer_discretionary',
  "Consumer Cyclical": 'consumer_cyclical',
  "Industrials": 'industrials',
  "Consumer Staples": 'consumer_staples',
  "Energy": 'energy',
  "Utilities": 'utilities',
  "Real Estate": 'real_estate',
  "Materials": 'materials',
  "Communication Services": 'communication_services',
  "Media": 'media',
  // Sin comillas a proposito: "Unknown" esta en la lista de etiquetas EN del guard.
  Unknown: 'unknown',
};
export const SECTORES: Record<string, string> = byCode(SECTOR_CODES, esLabels.sectors);

/** Industrias que llegan en inglés (Finnhub/Yahoo) y se leen mezcladas con el
 *  sector ES. Solo se traduce lo conocido; lo demás se muestra tal cual. */
const INDUSTRIA_CODES: Record<string, string> = {
  "Telecommunication": 'telecommunication',
  "Telecommunications": 'telecommunications',
  "Telecom Services": 'telecom_services',
  "Satellite telecom": 'satellite_telecom',
  "Semiconductors": 'semiconductors',
  "Software": 'software',
  "Software and cloud": 'software_and_cloud',
  "Application software": 'application_software',
  "Data analytics software": 'data_analytics_software',
  "Enterprise software": 'enterprise_software',
  "Marketing software": 'marketing_software',
  "AI infrastructure": 'ai_infrastructure',
  "Asset management and holdings": 'asset_management_and_holdings',
  "Aerospace and defense": 'aerospace_and_defense',
  "Biological products (SIC 2836)": 'biological_products_sic_2836',
  "Laboratory analytical instruments (SIC 3826)": 'laboratory_analytical_instruments_sic_3826',
  "China ecommerce and cloud": 'china_ecommerce_and_cloud',
  "Ecommerce and cloud": 'ecommerce_and_cloud',
  "Digital health": 'digital_health',
  "Gold and silver mining": 'gold_and_silver_mining',
  "Industrial connectivity and drones": 'industrial_connectivity_and_drones',
  "Marine robotics": 'marine_robotics',
  "Mobility platform": 'mobility_platform',
  "Pharmaceutical preparations (SIC 2834)": 'pharmaceutical_preparations_sic_2834',
  "Pharmaceuticals": 'pharmaceuticals',
  "Social platforms": 'social_platforms',
  "Streaming entertainment": 'streaming_entertainment',
  "Uranium mining": 'uranium_mining',
  "Biotechnology": 'biotechnology',
  "Banking": 'banking',
  "Banks": 'banks',
  "Insurance": 'insurance',
  "Retail": 'retail',
  "Beverages": 'beverages',
  "Media": 'media',
  "Utilities": 'utilities',
  "Aerospace & Defense": 'aerospace_defense',
  "Oil & Gas": 'oil_gas',
  "Real Estate": 'real_estate',
  "Automobiles": 'automobiles',
  "Consumer Electronics": 'consumer_electronics',
  "Communications": 'communications',
  "Professional Services": 'professional_services',
  "Electrical Equipment": 'electrical_equipment',
  "Communication Equipment": 'communication_equipment',
  "Electronic Components": 'electronic_components',
  "Computer Hardware": 'computer_hardware',
  "Hardware": 'hardware',
  "Information Technology Services": 'information_technology_services',
  "Internet Content & Information": 'internet_content_information',
  "Specialty Retail": 'specialty_retail',
  "Auto Manufacturers": 'auto_manufacturers',
  "Drug Manufacturers": 'drug_manufacturers',
  "Medical Devices": 'medical_devices',
  "Capital Markets": 'capital_markets',
  "Asset Management": 'asset_management',
  "Credit Services": 'credit_services',
  "Entertainment": 'entertainment',
  "Gold": 'gold',
  "Copper": 'copper',
  "Steel": 'steel',
  "Chemicals": 'chemicals',
  "Machinery": 'machinery',
  "Airlines": 'airlines',
  "Restaurants": 'restaurants',
  "Solar": 'solar',
  "Uranium": 'uranium',
  "Engineering & Construction": 'engineering_construction',
  "Building Products": 'building_products',
  "Packaged Foods": 'packaged_foods',
  "Semiconductor Equipment": 'semiconductor_equipment',
  "Software - Application": 'software_application',
  "Software - Infrastructure": 'software_infrastructure',
};
export const INDUSTRIAS: Record<string, string> = byCode(INDUSTRIA_CODES, esLabels.industries);

/** Etiqueta ES de un sector; si el backend manda uno desconocido, se muestra tal cual. */
export function etiquetaSector(value: string, locale: 'es' | 'en' = 'es'): string {
  // En inglés el backend ya manda el nombre original (GICS en inglés).
  if (locale === 'en') return value;
  return SECTORES[value] ?? value;
}

/** Etiqueta ES del tier de fuente (F175): el token interno
 *  («tier_1_regulatory») no se muestra tal cual; desconocido -> tal cual. */
// Las ocho claves del catálogo backend (source_hierarchy_service.SOURCE_TIERS).
// Si el backend añade una clave nueva, aquí debe llegar su etiqueta; hasta
// entonces se muestra el código crudo (visible y honesto, nunca inventado).
const TIER_CODES: Record<string, string> = {
  "tier_1_regulatory": 'tier_1_regulatory',
  "tier_2_company": 'tier_2_company',
  "tier_3_transcript": 'tier_3_transcript',
  "tier_4_reputable_media": 'tier_4_reputable_media',
  "tier_5_data_provider": 'tier_5_data_provider',
  "tier_6_bootstrap": 'tier_6_bootstrap',
  "tier_7_user_input": 'tier_7_user_input',
  "tier_8_social": 'tier_8_social',
  "tier_unknown": 'tier_unknown',
};
const TIERS_FUENTE: Record<string, string> = byCode(TIER_CODES, esLabels.sourceTiers);
const TIERS_FUENTE_EN: Record<string, string> = byCode(TIER_CODES, enLabels.sourceTiers);

/** Etiqueta ES de la direccion de impacto de una noticia (positive/negative/
 *  neutral/mixed). Codigo futuro desconocido: se muestra crudo (honesto),
 *  nunca inventado. */
const DIRECCION_CODES: Record<string, string> = {
  "positive": 'positive',
  "negative": 'negative',
  "neutral": 'neutral',
  "mixed": 'mixed',
};
const DIRECCIONES_IMPACTO: Record<string, string> = byCode(DIRECCION_CODES, esLabels.impactDirections);
const DIRECCIONES_IMPACTO_EN: Record<string, string> = byCode(DIRECCION_CODES, enLabels.impactDirections);

export function etiquetaDireccionImpacto(value: string, locale: 'es' | 'en' = 'es'): string {
  return (locale === 'en' ? DIRECCIONES_IMPACTO_EN : DIRECCIONES_IMPACTO)[value] ?? value;
}

export function etiquetaTierFuente(value: string, locale: 'es' | 'en' = 'es'): string {
  return (locale === 'en' ? TIERS_FUENTE_EN : TIERS_FUENTE)[value] ?? value;
}

/**
 * Orden de presentación por tier: la fuente primaria (reguladora, empresa)
 * primero; lo interno o sin clasificar al final. Clave desconocida: se muestra
 * su etiqueta cruda (etiquetaTierFuente) y se ordena con las sin clasificar,
 * nunca por delante de una fuente primaria.
 */
export function tierRankFuente(value: string): number {
  const order = [
    'tier_1_regulatory',
    'tier_2_company',
    'tier_3_transcript',
    'tier_4_reputable_media',
    'tier_5_data_provider',
    'tier_6_bootstrap',
    'tier_7_user_input',
    'tier_8_social',
  ];
  const index = order.indexOf(value);
  return index === -1 ? order.length : index;
}

/** Etiqueta ES del tipo de evento de noticias (F175). */
const EVENTO_CODES: Record<string, string> = {
  "regulatory": 'regulatory',
  "earnings": 'earnings',
  "dilution": 'dilution',
  "contract": 'contract',
  "capital_allocation": 'capital_allocation',
  "general_news": 'general_news',
  "legal_solicitation": 'legal_solicitation',
  "macro": 'macro',
  "opinion": 'opinion',
  "unknown": 'unknown',
};
const TIPOS_EVENTO: Record<string, string> = byCode(EVENTO_CODES, esLabels.eventTypes);
const TIPOS_EVENTO_EN: Record<string, string> = byCode(EVENTO_CODES, enLabels.eventTypes);

export function etiquetaTipoEvento(value: string, locale: 'es' | 'en' = 'es'): string {
  return (locale === 'en' ? TIPOS_EVENTO_EN : TIPOS_EVENTO)[value] ?? value;
}

/** Etiqueta ES de los componentes de atribucion heuristica de
 *  /portfolio/intelligence (F282). Catalogo cerrado de
 *  portfolio_intelligence_service (fundamental_growth, multiple, dividends,
 *  buybacks, dilution, fx, sizing); antes se pintaba la clave cruda en
 *  mayusculas («FUNDAMENTAL GROWTH»). */
const ATRIBUCION_CODES: Record<string, string> = {
  "fundamental_growth": 'fundamental_growth',
  "multiple": 'multiple',
  "dividends": 'dividends',
  "buybacks": 'buybacks',
  "dilution": 'dilution',
  "fx": 'fx',
  "sizing": 'sizing',
};
const COMPONENTES_ATRIBUCION: Record<string, string> = byCode(ATRIBUCION_CODES, esLabels.attributionComponents);
const COMPONENTES_ATRIBUCION_EN: Record<string, string> = byCode(ATRIBUCION_CODES, enLabels.attributionComponents);

export function etiquetaComponenteAtribucion(value: string, locale: 'es' | 'en' = 'es'): string {
  return (locale === 'en' ? COMPONENTES_ATRIBUCION_EN : COMPONENTES_ATRIBUCION)[value] ?? value;
}

/** Etiqueta ES del tipo de instrumento del buscador (F174): Finnhub devuelve
 *  «Common Stock», «Canadian DR»... y se pintaban en inglés. */
// «PUBLIC» es un securityType OpenFIGI (el estándar que usa Finnhub).
// OpenFIGI no le da un significado de clase de activo: aparece también en
// preferentes 144A (p. ej. BBG0001JJNS5 «SANTAN 6.41 PERP», marketSector
// Pfd), así que cualquier traducción («acción», «emisión pública»…)
// inferiría semántica que la fuente no afirma. Se muestra el código crudo
// del estándar, sin traducir.
const INSTRUMENTO_CODES: Record<string, string> = {
  "Common Stock": 'common_stock',
  "Preferred Stock": 'preferred_stock',
  "Canadian DR": 'canadian_dr',
  "ADR": 'adr',
  "ETF": 'etf',
  "ETN": 'etn',
  "ETP": 'etp',
  "REIT": 'reit',
  "Warrant": 'warrant',
  "Right": 'right',
  "Unit": 'unit',
  "PUBLIC": 'public',
};
const TIPOS_INSTRUMENTO: Record<string, string> = byCode(INSTRUMENTO_CODES, esLabels.instrumentTypes);

export function etiquetaTipoInstrumento(value: string, locale: 'es' | 'en' = 'es'): string {
  // En inglés el tipo ya llega en inglés desde el proveedor.
  if (locale === 'en') return value;
  return TIPOS_INSTRUMENTO[value] ?? value;
}

/** Etiqueta ES de los temas macro GDELT (espejo de las claves de
 *  MACRO_GDELT_QUERIES en data-engine/app/services/macro_news.py; si se
 *  anade un tema hay que mapearlo aqui — el fallback muestra la clave). */
const TEMA_CODES: Record<string, string> = {
  "gold_central_banks": 'gold_central_banks',
  "interest_rates": 'interest_rates',
  "commodities": 'commodities',
  "trucking_freight": 'trucking_freight',
  "ai_investment": 'ai_investment',
  "hormuz_oil": 'hormuz_oil',
  "energy": 'energy',
  "semiconductors": 'semiconductors',
  "dollar_fx": 'dollar_fx',
  "inflation": 'inflation',
  "china_supply_chains": 'china_supply_chains',
  "us_trade_policy": 'us_trade_policy',
};
const TEMAS_MACRO: Record<string, string> = byCode(TEMA_CODES, esLabels.macroThemes);
const TEMAS_MACRO_EN: Record<string, string> = byCode(TEMA_CODES, enLabels.macroThemes);

export function etiquetaTemaMacro(value: string, locale: 'es' | 'en' = 'es'): string {
  return (locale === 'en' ? TEMAS_MACRO_EN : TEMAS_MACRO)[value] ?? value;
}

/** F106: el master guarda la cadena 'Unknown' en sector/industry cuando no
 * tiene clasificación (300 de 2115 empresas, p.ej. ALM, A3M). Mostrarla
 * cruda en la UI española es un placeholder en inglés que parece dato.
 * 'Unknown' se trata como ausencia: se omiten las partes sin dato y, si no
 * hay ninguna, la línea lo declara. */
const cleanSectorPart = (value: unknown): string | null => {
    if (typeof value !== 'string') return null;
    const trimmed = value.trim();
    return trimmed && trimmed.toLowerCase() !== 'unknown' ? trimmed : null;
};

/** Línea «Sector · Industria» de la ficha y las tarjetas de research.
 * Quick win UX 4: se traduce lo conocido (etiquetaSector deja lo
 * desconocido tal cual, nunca inventa) y se colapsa cuando sector e
 * industria traducen lo mismo («Tecnología · Tecnología» -> «Tecnología»). */
export function sectorIndustryLine(sector: unknown, industry: unknown, locale: 'es' | 'en' = 'es'): string {
    const parts = [cleanSectorPart(sector), cleanSectorPart(industry)]
        .filter((p): p is string => p !== null)
        .map((part) => (locale === 'en' ? part : INDUSTRIAS[part] ?? etiquetaSector(part)));
    const unique = parts.filter((part, index) => parts.indexOf(part) === index);
    if (unique.length) return unique.join(' · ');
    return locale === 'en' ? enLabels.misc.sectorNotAvailable : esLabels.misc.sectorNotAvailable;
}

/** Etiqueta ES de la severidad de una alerta de riesgo (high/medium/low).
 *  Valor desconocido: se muestra tal cual, nunca inventado. */
const SEVERIDAD_CODES: Record<string, string> = {
  "critical": 'critical',
  "high": 'high',
  "medium": 'medium',
  "low": 'low',
  "info": 'info',
};
const SEVERIDADES: Record<string, string> = byCode(SEVERIDAD_CODES, esLabels.severities);
const SEVERIDADES_EN: Record<string, string> = byCode(SEVERIDAD_CODES, enLabels.severities);

export function etiquetaSeveridad(value: string, locale: 'es' | 'en' = 'es'): string {
  return (locale === 'en' ? SEVERIDADES_EN : SEVERIDADES)[value.toLowerCase()] ?? value;
}

/** Etiquetas ES de los factores/temas de cartera (factor_tags del backend).
 *  Etiqueta desconocida: se humaniza el snake_case (sin inventar significado). */
const FACTOR_CODES: Record<string, string> = {
  "ads": 'ads',
  "ai": 'ai',
  "ai_biology": 'ai_biology',
  "auto": 'auto',
  "biotech": 'biotech',
  "china": 'china',
  "cloud": 'cloud',
  "commodities": 'commodities',
  "cyclical": 'cyclical',
  "defense": 'defense',
  "drones": 'drones',
  "ecommerce": 'ecommerce',
  "energy": 'energy',
  "fcf": 'fcf',
  "financials": 'financials',
  "glp1": 'glp1',
  "government": 'government',
  "growth": 'growth',
  "healthcare": 'healthcare',
  "infra": 'infra',
  "media": 'media',
  "mining": 'mining',
  "mobility": 'mobility',
  "optionality": 'optionality',
  "platform": 'platform',
  "pre_fcf": 'pre_fcf',
  "quality": 'quality',
  "rates": 'rates',
  "regulatory": 'regulatory',
  "robotics": 'robotics',
  "semiconductors": 'semiconductors',
  "small_cap": 'small_cap',
  "software": 'software',
  "sotp": 'sotp',
  "space": 'space',
  "speculative": 'speculative',
  "subscriber": 'subscriber',
  "telecom": 'telecom',
  "uranium": 'uranium',
};
const FACTORES: Record<string, string> = byCode(FACTOR_CODES, esLabels.factors);
const FACTORES_EN: Record<string, string> = byCode(FACTOR_CODES, enLabels.factors);

/** Tipos de empresa simples con etiqueta propia (no son factores). */
const TIPO_EMPRESA_CODES: Record<string, string> = {
  "ai_big_tech": 'ai_big_tech',
  "ai_infra_capacity": 'ai_infra_capacity',
  "asset_manager_holding": 'asset_manager_holding',
  "auto_energy_optionality": 'auto_energy_optionality',
  "china_adr_holding": 'china_adr_holding',
  "defense_contract_backlog": 'defense_contract_backlog',
  "healthcare_regulatory": 'healthcare_regulatory',
  "mining_pre_revenue": 'mining_pre_revenue',
  "platform_fcf_compounder": 'platform_fcf_compounder',
  "software_ai_disruption": 'software_ai_disruption',
  "software_ai_platform": 'software_ai_platform',
  "software_durable_growth": 'software_durable_growth',
  "space_defense_growth": 'space_defense_growth',
  "speculative_scenario": 'speculative_scenario',
  "subscriber_media": 'subscriber_media',
  "uranium_mining": 'uranium_mining',
  "operating_company": 'operating_company',
  "research_candidate": 'research_candidate',
  "fund": 'fund',
  "etf": 'etf',
  "trust": 'trust',
};
const TIPOS_EMPRESA: Record<string, string> = byCode(TIPO_EMPRESA_CODES, esLabels.companyTypes);
const TIPOS_EMPRESA_EN: Record<string, string> = byCode(TIPO_EMPRESA_CODES, enLabels.companyTypes);

/** Etiqueta ES del tipo de empresa de la ficha.
 * QA 23: el tipo compuesto «space_telecom_pre_fcf» se pintaba crudo
 * («space telecom pre fcf»). Se descompone en tokens de factores
 * conocidos (primero las claves de dos tokens: pre_fcf, small_cap...);
 * un token desconocido devuelve el tipo tal cual, nunca una etiqueta
 * inventada. */
export function companyTypeLabel(value: string, locale: 'es' | 'en' = 'es'): string {
  const tipos = locale === 'en' ? TIPOS_EMPRESA_EN : TIPOS_EMPRESA;
  const factores = locale === 'en' ? FACTORES_EN : FACTORES;
  const exact = tipos[value.toLowerCase()];
  if (exact) return exact;
  const tokens = value.toLowerCase().split('_');
  const labels: string[] = [];
  let i = 0;
  while (i < tokens.length) {
    const pair = tokens.slice(i, i + 2).join('_');
    if (i + 1 < tokens.length && factores[pair]) {
      labels.push(factores[pair]);
      i += 2;
    } else if (factores[tokens[i]]) {
      labels.push(factores[tokens[i]]);
      i += 1;
    } else {
      return value;
    }
  }
  return labels.join(' · ');
}

export function etiquetaFactor(value: string, locale: 'es' | 'en' = 'es'): string {
  const known = (locale === 'en' ? FACTORES_EN : FACTORES)[value.toLowerCase()];
  if (known) return known;
  const adr = /^adr:(\d+)$/i.exec(value);
  if (adr) return (locale === 'en' ? enLabels : esLabels).misc.adrRatio.replace('{ratio}', adr[1]);
  const plain = value.replace(/_/g, ' ');
  return plain.charAt(0).toUpperCase() + plain.slice(1);
}

/** Pendientes que explican «requiere revisión»: el estado sale de revisiones
 * o alertas abiertas, no de la nota de completitud (que puede ser 100/100).
 * Sin pendientes no se inventa texto. */
export function openReviewsLabel(
    counts: { open_reviews?: number | null; open_alerts?: number | null } | null | undefined,
): string | null {
    const reviews = Number(counts?.open_reviews ?? 0);
    const alerts = Number(counts?.open_alerts ?? 0);
    const parts: string[] = [];
    if (reviews > 0) parts.push((reviews === 1 ? esLabels.misc.reviewOpenOne : esLabels.misc.reviewOpenMany).replace('{n}', String(reviews)));
    if (alerts > 0) parts.push((alerts === 1 ? esLabels.misc.alertOpenOne : esLabels.misc.alertOpenMany).replace('{n}', String(alerts)));
    return parts.length ? parts.join(' · ') : null;
}

/** Mapa central de valores que el backend persiste como códigos (persistencia,
 *  tendencia y estado del foso, tipo de fuente, tier). Los cargadores de texto
 *  de usuario pasan por `etiquetaValor`; un código desconocido se muestra con
 *  guiones bajos convertidos en espacios, nunca inventado. */
const VALOR_CODES: Record<string, string> = {
  "unproven": 'unproven',
  "proven": 'proven',
  "uncertain": 'uncertain',
  "improving": 'improving',
  "deteriorating": 'deteriorating',
  "strengthening": 'strengthening',
  "weakening": 'weakening',
  "moderate": 'moderate',
  "durable": 'durable',
  "insufficient_evidence": 'insufficient_evidence',
  "insufficient_data": 'insufficient_data',
  "primary_official": 'primary_official',
  "wacc_policy": 'wacc_policy',
  "damodaran": 'damodaran',
  "model_policy": 'model_policy',
  "calculated_metric": 'calculated_metric',
  "financial_facts": 'financial_facts',
  "historical_case": 'historical_case',
  "inferred_input": 'inferred_input',
  "manual_transcript": 'manual_transcript',
  "manual_upload": 'manual_upload',
  "sec_filing": 'sec_filing',
  "earnings_call": 'earnings_call',
  "investor_relations": 'investor_relations',
  "transcript": 'transcript',
  "yfinance": 'yfinance',
  "yahoo_fundamentals": 'yahoo_fundamentals',
  "YAHOO_FUNDAMENTALS": 'yahoo_fundamentals',
  "user": 'user',
  "chat": 'chat',
  "url": 'url',
  "brand": 'brand',
  "capital_barrier": 'capital_barrier',
};
const VALORES_BACKEND: Record<string, string> = byCode(VALOR_CODES, esLabels.backendValues);
const VALORES_BACKEND_EN: Record<string, string> = byCode(VALOR_CODES, enLabels.backendValues);

/** Etiqueta ES de un código del backend: primero tiers de fuente y el mapa
 *  central; si no está, el código con espacios en vez de guiones bajos. */
export function etiquetaValor(value: string, locale: 'es' | 'en' = 'es'): string {
  if (locale === 'en') return TIERS_FUENTE_EN[value] ?? VALORES_BACKEND_EN[value] ?? value.replaceAll('_', ' ');
  return TIERS_FUENTE[value] ?? VALORES_BACKEND[value] ?? value.replaceAll('_', ' ');
}
