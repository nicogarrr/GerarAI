/**
 * Etiquetas en español de los drivers, KPIs, unidades económicas, segmentos y
 * restricciones del marco por tipo de empresa (data-engine company_framework.py).
 * Las claves van en minúsculas con guiones bajos; las fórmulas
 * («ARR × retention × expansion») se traducen término a término.
 */
// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { FRAMEWORK_TERMS_EN } from './framework-terms-en.ts';

export const FRAMEWORK_TERMS: Record<string, string> = {
    non_negative_fcf_margin: 'margen de flujo de caja libre no negativo',
    normalized_fcf_or_fcf_margin: 'flujo de caja libre normalizado o margen de flujo de caja libre',
    standard_dcf: 'DCF de flujo de caja libre',
    // siglas
    arpu: 'ARPU', arr: 'ARR', aum: 'AUM', nav: 'NAV', noi: 'NOI', rpo: 'RPO', sbc: 'compensación en acciones (SBC)',
    tpv: 'volumen total de pagos (TPV)', 'r&d': 'I+D', cet1_ratio: 'ratio CET1', rote: 'ROTE', affo_per_share: 'AFFO por acción',
    // tipos de modelo de valoración (claves de company_framework.py)
    space_network: 'red espacial / conectividad', space_defense: 'plataforma espacial y de defensa', platform: 'plataforma / marketplace',
    subscriber: 'suscriptores / ingresos recurrentes', software_ai: 'software / plataforma de IA', capacity_infrastructure: 'capacidad / infraestructura',
    holding_asset_manager: 'holding / gestora de activos', bank: 'banco / negocio de depósitos', insurer: 'aseguradora', reit: 'SOCIMI / propietario de inmuebles',
    commodity: 'materias primas / royalties / recursos', biotech_pre_fcf: 'biotecnología / IA-biología pre-FCF', generic_fcf: 'compounder de flujo de caja libre',
    // métricas y drivers
    collaboration_revenue: 'ingresos por colaboraciones', product_revenue: 'ingresos por producto', milestones: 'hitos de colaboración',
    pipeline_stage: 'fase del pipeline', cash_and_investments: 'caja e inversiones', partner_dependence: 'dependencia de socios',
    reported_revenue_only: 'solo ingresos reportados (economía por activo: N/D hasta que una fuente la documente)',
    collaboration: 'colaboración', clinical_or_technical_validation: 'validación clínica o técnica',
    active_accounts: 'cuentas activas', adjacent_products: 'productos adyacentes', advertising: 'publicidad',
    all_in_cost: 'coste total (all-in)', asset_management: 'gestión de activos', asset_value: 'valor de los activos', asset_values: 'valor de los activos',
    backlog: 'cartera de pedidos', backlog_conversion: 'conversión de la cartera de pedidos', book_value: 'valor contable',
    book_value_per_share: 'valor contable por acción', bookings: 'reservas contratadas', buybacks: 'recompras de acciones',
    cap_rate: 'tasa de capitalización', capitalization_rate: 'tasa de capitalización', cap_rates: 'tasas de capitalización', capacity: 'capacidad', capacity_units: 'unidades de capacidad',
    capex: 'inversión de capital (CapEx)', carry: 'comisión de éxito (carry)', cash_burn: 'consumo de caja', cash_yield: 'rentabilidad de la caja',
    churn: 'abandono de clientes (churn)', cloud_cost: 'coste de nube', combined_ratio: 'ratio combinado', commercial_banking: 'banca comercial',
    commodity_price: 'precio de la materia prima', connectivity: 'conectividad', consumer_banking: 'banca de consumo', consumption: 'consumo',
    content_or_marketing_spend: 'gasto en contenido o marketing', content_or_marketing_cost: 'coste de contenido o marketing',
    contribution_margin: 'margen de contribución', core_platform: 'plataforma principal', cost_of_deposits: 'coste de los depósitos',
    cost_of_equity: 'coste del capital propio', coverage: 'cobertura', customer_acquisition_cost: 'coste de captación de clientes',
    customers: 'clientes', defense: 'defensa', defense_contracts: 'contratos de defensa', deposit_growth: 'crecimiento de depósitos',
    development: 'desarrollo', development_pipeline: 'cartera de desarrollos', dilution: 'dilución', earned_premiums: 'primas devengadas',
    earned_premium: 'primas devengadas', earning_assets: 'activos que generan intereses', efficiency_ratio: 'ratio de eficiencia', expense_ratio: 'ratio de gastos',
    fee_income: 'ingresos por comisiones', fee_rate: 'tasa de comisión', fee_related_earnings: 'beneficios por comisiones recurrentes',
    float: 'fondos flotantes (float)', funding: 'financiación', funding_cost: 'coste de financiación', geography: 'geografía',
    government_or_defense: 'gobierno o defensa', gross_retention: 'retención bruta', holdco_debt: 'deuda del holding', inflows: 'entradas netas',
    infrastructure: 'infraestructura', investment_income: 'ingresos por inversiones', investment_portfolio: 'cartera de inversión',
    investment_yield: 'rentabilidad de las inversiones', joint_ventures: 'empresas conjuntas', land: 'terrenos', launch: 'lanzamiento',
    launch_cadence: 'cadencia de lanzamientos', launch_execution: 'ejecución de lanzamientos', launches: 'lanzamientos', loan_growth: 'crecimiento de préstamos',
    loss_ratio: 'ratio de siniestralidad', markets: 'mercados', mno_agreements: 'acuerdos con operadores móviles (MNO)',
    mno_monetization: 'monetización con operadores móviles (MNO)', net_adds: 'altas netas', net_charge_off_rate: 'tasa de impagos netos',
    net_interest_margin: 'margen de intereses neto', net_operating_income: 'resultado operativo neto', net_revenue_retention: 'retención neta de ingresos',
    nonperforming_loan_ratio: 'ratio de morosidad', occupancy: 'ocupación', occupied_area: 'superficie ocupada', operating_businesses: 'negocios operativos',
    other: 'otros', ownership: 'participación', power: 'energía', power_capacity: 'capacidad eléctrica', power_cost: 'coste de la energía',
    premium_growth: 'crecimiento de primas', price_per_launch: 'precio por lanzamiento', price_per_unit: 'precio por unidad', product: 'producto',
    product_tier: 'nivel de producto', production: 'producción', production_volume: 'volumen de producción', property_type: 'tipo de inmueble',
    real_estate: 'inmobiliario', realization: 'realización', realized_price: 'precio realizado', rent: 'alquiler', rent_per_area: 'alquiler por superficie',
    rental_income: 'ingresos por alquileres', reported_segments: 'segmentos reportados', reserve_development: 'evolución de reservas',
    reserve_life: 'vida de las reservas', reserves: 'reservas', resource: 'recurso', retention: 'retención', expansion: 'expansión',
    return_on_tangible_equity: 'rentabilidad sobre capital tangible', revenue_per_trip: 'ingresos por viaje', royalty: 'royalty',
    royalty_rate: 'tasa de royalty', royalty_revenue: 'ingresos por royalties', runway: 'autonomía de caja', same_store_noi_growth: 'crecimiento del NOI a igual perímetro',
    seats: 'licencias', services: 'servicios', space_systems: 'sistemas espaciales', space_systems_units: 'unidades de sistemas espaciales',
    subscribers: 'suscriptores', subscription: 'suscripción', take_rate: 'comisión sobre volumen (take rate)', tangible_book_value: 'valor contable tangible',
    tangible_book: 'valor contable tangible', sustainable_rote: 'ROTE sostenible', tons: 'toneladas', royalty_per_ton: 'royalty por tonelada',
    transactions_per_account: 'transacciones por cuenta', trips: 'viajes', underwriting_lines: 'líneas de suscripción', underwriting_margin: 'margen de suscripción',
    units: 'unidades', usage: 'uso', volume: 'volumen', wealth: 'gestión patrimonial', wealth_solutions: 'soluciones patrimoniales',
    monthly_arpu: 'ARPU mensual', revenue_share: 'reparto de ingresos', price_per_gb: 'precio por GB', price_per_launch_unit: 'precio por lanzamiento',
    normalized_margin: 'margen normalizado', revenue: 'ingresos', price: 'precio', satellites: 'satélites', utilization: 'utilización',
    monetization: 'monetización', '12': '12 meses',
    // plataforma de publicidad (META): drivers desglosados por la empresa
    ad_impressions: 'impresiones de anuncios', price_per_ad: 'precio por anuncio', average_price_per_ad: 'precio medio por anuncio',
    daily_active_people: 'personas activas al día (DAP)', dap: 'personas activas al día (DAP)', family_arpu: 'ARPU de la familia de apps',
    ad_impressions_yoy: 'variación interanual de impresiones de anuncios', price_per_ad_yoy: 'variación interanual del precio por anuncio',
    reality_labs_operating_loss: 'pérdida operativa de Reality Labs', family_of_apps: 'familia de aplicaciones', reality_labs: 'Reality Labs',
    engagement: 'interacción', ad_load_ceiling: 'techo de carga publicitaria', privacy_regulation: 'regulación de privacidad',
    competition_attention: 'competencia por la atención', ai_capex: 'inversión de capital en IA',
    // restricciones vinculantes
    ai_disruption: 'disrupción por IA', capital: 'capital', capital_allocation: 'asignación de capital', capital_requirements: 'requisitos de capital',
    catastrophe_losses: 'pérdidas por catástrofes', competition: 'competencia', complexity: 'complejidad', contract_timing: 'calendario de contratos',
    cost_curve: 'curva de costes', credit_losses: 'pérdidas por crédito', development_cost: 'coste de desarrollo', distribution: 'distribución',
    interest_rates: 'tipos de interés', liquidity: 'liquidez', management: 'gestión', market_size: 'tamaño de mercado', permitting: 'permisos',
    pricing: 'precios', pricing_cycle: 'ciclo de precios', rate_sensitivity: 'sensibilidad a tipos', rates: 'tipos de interés', refinancing: 'refinanciación',
    regulation: 'regulación', reinvestment: 'reinversión', reserve_adequacy: 'suficiencia de reservas', supply_chain: 'cadena de suministro',
    mix: 'mezcla de producto',
};

export const FRAMEWORK_LABELS: Record<string, string> = {
    'Space network / connectivity': 'Red espacial / conectividad',
    'Space and defense platform': 'Plataforma espacial y de defensa',
    'Platform / marketplace': 'Plataforma / marketplace',
    'Advertising / attention platform': 'Plataforma de publicidad / atención',
    'Subscriber / recurring revenue': 'Suscriptores / ingresos recurrentes',
    'Software / AI platform': 'Software / plataforma de IA',
    'Capacity / infrastructure': 'Capacidad / infraestructura',
    'Holding company / asset manager': 'Holding / gestora de activos',
    'Bank / deposit franchise': 'Banco / negocio de depósitos',
    'Insurance underwriter': 'Aseguradora',
    'REIT / property owner': 'SOCIMI / propietario de inmuebles',
    'Commodity / royalty / resource': 'Materias primas / royalties / recursos',
    'Biotech / AI-biology pre-FCF': 'Biotecnología / IA-biología pre-FCF',
    'FCF compounder': 'Compounder de flujo de caja libre',
};

function normalise(term: string): string {
    return term.trim().toLowerCase().replaceAll(/\s+/g, '_');
}

/** Traduce un término simple o una fórmula con × / ÷; null si algún término no tiene etiqueta. */
export function frameworkTerm(raw: string, locale: 'es' | 'en' = 'es'): string | null {
    if (locale === 'en') return frameworkTermEn(raw);
    const direct = (Object.hasOwn(FRAMEWORK_TERMS, normalise(raw)) ? FRAMEWORK_TERMS[normalise(raw)] : null);
    if (direct) return direct;
    if (!/[×÷]/.test(raw)) return null;
    const parts = raw.split(/\s*([×÷])\s*/);
    const out: string[] = [];
    for (const part of parts) {
        if (part === '×' || part === '÷') {
            out.push(part);
            continue;
        }
        const t = (Object.hasOwn(FRAMEWORK_TERMS, normalise(part)) ? FRAMEWORK_TERMS[normalise(part)] : null) ?? translateWords(part);
        if (!t) return null;
        out.push(t);
    }
    return out.join(' ');
}

/** «price per launch» -> «precio por lanzamiento»: palabra a palabra con «per» -> «por». */
function translateWords(part: string): string | null {
    const direct = (Object.hasOwn(FRAMEWORK_TERMS, normalise(part)) ? FRAMEWORK_TERMS[normalise(part)] : null);
    if (direct) return direct;
    const chunks = part.trim().split(/\s+per\s+/i);
    if (chunks.length > 1) {
        const tr = chunks.map((c) => (Object.hasOwn(FRAMEWORK_TERMS, normalise(c)) ? FRAMEWORK_TERMS[normalise(c)] : null) ?? null);
        return tr.every(Boolean) ? tr.join(' por ') : null;
    }
    return null;
}

export function frameworkLabel(label: string): string {
    return Object.hasOwn(FRAMEWORK_LABELS, label) ? FRAMEWORK_LABELS[label] : label;
}

/** EN: excepciones del catálogo; el resto de claves (ya en inglés) se humaniza. Una clave sin forma de término devuelve null. */
function frameworkTermEn(raw: string): string | null {
    const one = (part: string): string | null => {
        const key = normalise(part);
        if (Object.hasOwn(FRAMEWORK_TERMS_EN, key)) return FRAMEWORK_TERMS_EN[key];
        return Object.hasOwn(FRAMEWORK_TERMS, key) ? key.replaceAll('_', ' ') : null;
    };
    const direct = one(raw);
    if (direct) return direct;
    if (!/[×÷]/.test(raw)) return null;
    const parts = raw.split(/\s*([×÷])\s*/);
    const out: string[] = [];
    for (const part of parts) {
        if (part === '×' || part === '÷') { out.push(part); continue; }
        const translated = one(part);
        if (!translated) return null;
        out.push(translated);
    }
    return out.join(' ');
}
