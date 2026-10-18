/**
 * Etiquetas visibles para valores que el backend codifica en inglés.
 *
 * El `value` de los <select>/query params DEBE seguir siendo la clave
 * inglesa (el backend la espera tal cual); lo que se traduce es solo lo que
 * el usuario lee. Compartido por el Screener y por los filtros de ProPicks,
 * que antes tenían dos listas de sectores distintas.
 */
export const SECTORES: Record<string, string> = {
  Technology: 'Tecnología',
  'Information Technology': 'Tecnología',
  Healthcare: 'Salud',
  'Health Care': 'Salud',
  'Financial Services': 'Servicios financieros',
  Financials: 'Servicios financieros',
  'Consumer Discretionary': 'Consumo cíclico',
  'Consumer Cyclical': 'Consumo cíclico',
  Industrials: 'Industriales',
  'Consumer Staples': 'Consumo básico',
  Energy: 'Energía',
  Utilities: 'Servicios públicos',
  'Real Estate': 'Inmobiliario',
  Materials: 'Materiales',
  'Communication Services': 'Servicios de comunicación',
  Media: 'Medios',
  Unknown: 'Sin clasificar',
};

/** Industrias que llegan en inglés (Finnhub/Yahoo) y se leen mezcladas con el
 *  sector ES. Solo se traduce lo conocido; lo demás se muestra tal cual. */
export const INDUSTRIAS: Record<string, string> = {
  Telecommunication: 'Telecomunicaciones',
  Telecommunications: 'Telecomunicaciones',
  'Telecom Services': 'Telecomunicaciones',
  Semiconductors: 'Semiconductores',
  Software: 'Software',
  Biotechnology: 'Biotecnología',
  Banking: 'Banca',
  Banks: 'Banca',
  Insurance: 'Seguros',
  Retail: 'Distribución minorista',
  Beverages: 'Bebidas',
  Media: 'Medios',
  Utilities: 'Servicios públicos',
  'Aerospace & Defense': 'Aeroespacial y defensa',
  'Oil & Gas': 'Petróleo y gas',
  'Real Estate': 'Inmobiliario',
  Automobiles: 'Automoción',
  'Consumer Electronics': 'Electrónica de consumo',
};

/** Etiqueta ES de un sector; si el backend manda uno desconocido, se muestra tal cual. */
export function etiquetaSector(value: string): string {
  return SECTORES[value] ?? value;
}

/** Etiqueta ES del tier de fuente (F175): el token interno
 *  («tier_1_regulatory») no se muestra tal cual; desconocido -> tal cual. */
// Las ocho claves del catálogo backend (source_hierarchy_service.SOURCE_TIERS).
// Si el backend añade una clave nueva, aquí debe llegar su etiqueta; hasta
// entonces se muestra el código crudo (visible y honesto, nunca inventado).
const TIERS_FUENTE: Record<string, string> = {
  tier_1_regulatory: 'Regulatoria · T1',
  tier_2_company: 'Empresa · T2',
  tier_3_transcript: 'Transcripción · T3',
  tier_4_reputable_media: 'Medios · T4',
  tier_5_data_provider: 'Proveedor de datos · T5',
  tier_6_bootstrap: 'Datos iniciales · T6',
  tier_7_user_input: 'Aportado por el usuario · T7',
  tier_unknown: 'Fuente sin clasificar',
};

/** Etiqueta ES de la direccion de impacto de una noticia (positive/negative/
 *  neutral/mixed). Codigo futuro desconocido: se muestra crudo (honesto),
 *  nunca inventado. */
const DIRECCIONES_IMPACTO: Record<string, string> = {
  positive: 'Positivo',
  negative: 'Negativo',
  neutral: 'Neutro',
  mixed: 'Mixto',
};

export function etiquetaDireccionImpacto(value: string): string {
  return DIRECCIONES_IMPACTO[value] ?? value;
}

export function etiquetaTierFuente(value: string): string {
  return TIERS_FUENTE[value] ?? value;
}

/** Etiqueta ES del tipo de evento de noticias (F175). */
const TIPOS_EVENTO: Record<string, string> = {
  regulatory: 'Regulatorio',
  earnings: 'Resultados',
  dilution: 'Dilución',
  contract: 'Contrato',
  capital_allocation: 'Asignación de capital',
  general_news: 'Noticia general',
  macro: 'Macro',
  opinion: 'Opinión',
  unknown: 'Desconocido',
};

/** Etiqueta ES de los componentes de atribucion heuristica de
 *  /portfolio/intelligence (F282). Catalogo cerrado de
 *  portfolio_intelligence_service (fundamental_growth, multiple, dividends,
 *  buybacks, dilution, fx, sizing); antes se pintaba la clave cruda en
 *  mayusculas («FUNDAMENTAL GROWTH»). */
const COMPONENTES_ATRIBUCION: Record<string, string> = {
  fundamental_growth: 'Crecimiento fundamental',
  multiple: 'Múltiplo',
  dividends: 'Dividendos',
  buybacks: 'Recompras',
  dilution: 'Dilución',
  fx: 'Divisa',
  sizing: 'Tamaño de posición',
};

export function etiquetaComponenteAtribucion(value: string): string {
  return COMPONENTES_ATRIBUCION[value] ?? value;
}

export function etiquetaTipoEvento(value: string): string {
  return TIPOS_EVENTO[value] ?? value;
}

/** Etiqueta ES del tipo de instrumento del buscador (F174): Finnhub devuelve
 *  «Common Stock», «Canadian DR»... y se pintaban en inglés. */
const TIPOS_INSTRUMENTO: Record<string, string> = {
  'Common Stock': 'Acción ordinaria',
  'Preferred Stock': 'Acción preferente',
  'Canadian DR': 'Recibo de depósito canadiense',
  ADR: 'ADR',
  ETF: 'ETF',
  ETN: 'ETN',
  ETP: 'ETP',
  REIT: 'REIT',
  Warrant: 'Warrant',
  Right: 'Derecho',
  Unit: 'Unidad',
};

export function etiquetaTipoInstrumento(value: string): string {
  return TIPOS_INSTRUMENTO[value] ?? value;
}

/** Etiqueta ES de los temas macro GDELT (espejo de las claves de
 *  MACRO_GDELT_QUERIES en data-engine/app/services/macro_news.py; si se
 *  anade un tema hay que mapearlo aqui — el fallback muestra la clave). */
const TEMAS_MACRO: Record<string, string> = {
  gold_central_banks: 'Oro y bancos centrales',
  interest_rates: 'Tipos de interés',
  commodities: 'Materias primas',
  trucking_freight: 'Transporte y logística',
  ai_investment: 'Inversión en IA',
  hormuz_oil: 'Petróleo y Ormuz',
  energy: 'Energía',
  semiconductors: 'Semiconductores',
  dollar_fx: 'Dólar y divisas',
  inflation: 'Inflación',
  china_supply_chains: 'Cadenas de suministro de China',
  us_trade_policy: 'Política comercial de EE. UU.',
};

export function etiquetaTemaMacro(value: string): string {
  return TEMAS_MACRO[value] ?? value;
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
export function sectorIndustryLine(sector: unknown, industry: unknown): string {
    const parts = [cleanSectorPart(sector), cleanSectorPart(industry)]
        .filter((p): p is string => p !== null)
        .map((part) => INDUSTRIAS[part] ?? etiquetaSector(part));
    const unique = parts.filter((part, index) => parts.indexOf(part) === index);
    return unique.length ? unique.join(' · ') : 'Sector sin dato';
}

/** Etiqueta ES de la severidad de una alerta de riesgo (high/medium/low).
 *  Valor desconocido: se muestra tal cual, nunca inventado. */
const SEVERIDADES: Record<string, string> = {
  critical: 'Crítica',
  high: 'Alta',
  medium: 'Media',
  low: 'Baja',
  info: 'Informativa',
};

export function etiquetaSeveridad(value: string): string {
  return SEVERIDADES[value.toLowerCase()] ?? value;
}

/** Etiquetas ES de los factores/temas de cartera (factor_tags del backend).
 *  Etiqueta desconocida: se humaniza el snake_case (sin inventar significado). */
const FACTORES: Record<string, string> = {
  ads: 'Publicidad',
  ai: 'IA',
  ai_biology: 'IA aplicada a biología',
  auto: 'Automoción',
  biotech: 'Biotecnología',
  china: 'China',
  cloud: 'Nube',
  commodities: 'Materias primas',
  cyclical: 'Cíclico',
  defense: 'Defensa',
  drones: 'Drones',
  ecommerce: 'Comercio electrónico',
  energy: 'Energía',
  fcf: 'Genera flujo de caja libre',
  financials: 'Financiero',
  glp1: 'GLP-1',
  government: 'Gobierno',
  growth: 'Crecimiento',
  healthcare: 'Salud',
  infra: 'Infraestructura',
  media: 'Medios',
  mining: 'Minería',
  mobility: 'Movilidad',
  optionality: 'Opcionalidad',
  platform: 'Plataforma / marketplace',
  pre_fcf: 'Pre flujo de caja libre',
  quality: 'Calidad',
  rates: 'Tipos de interés',
  regulatory: 'Regulatorio',
  robotics: 'Robótica',
  semiconductors: 'Semiconductores',
  small_cap: 'Small cap',
  software: 'Software',
  sotp: 'Suma de partes',
  space: 'Espacio',
  speculative: 'Especulativo',
  subscriber: 'Suscripción (ingresos recurrentes)',
  telecom: 'Telecomunicaciones',
  uranium: 'Uranio',
};

export function etiquetaFactor(value: string): string {
  const known = FACTORES[value.toLowerCase()];
  if (known) return known;
  const adr = /^adr:(\d+)$/i.exec(value);
  if (adr) return `ADR (ratio ${adr[1]})`;
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
    if (reviews > 0) parts.push(`${reviews} ${reviews === 1 ? 'revisión abierta' : 'revisiones abiertas'}`);
    if (alerts > 0) parts.push(`${alerts} ${alerts === 1 ? 'alerta abierta' : 'alertas abiertas'}`);
    return parts.length ? parts.join(' · ') : null;
}
