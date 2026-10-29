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
  'Satellite telecom': 'Telecomunicaciones por satélite',
  Semiconductors: 'Semiconductores',
  Software: 'Software',
  'Software and cloud': 'Software y nube',
  'Application software': 'Software de aplicaciones',
  'Data analytics software': 'Software de analítica de datos',
  'Enterprise software': 'Software empresarial',
  'Marketing software': 'Software de marketing',
  'AI infrastructure': 'Infraestructura de IA',
  'Asset management and holdings': 'Gestión de activos y holdings',
  'Aerospace and defense': 'Aeroespacial y defensa',
  'Biological products (SIC 2836)': 'Productos biológicos (SIC 2836)',
  'Laboratory analytical instruments (SIC 3826)': 'Instrumentos analíticos de laboratorio (SIC 3826)',
  'China ecommerce and cloud': 'Comercio electrónico y nube en China',
  'Ecommerce and cloud': 'Comercio electrónico y nube',
  'Digital health': 'Salud digital',
  'Gold and silver mining': 'Minería de oro y plata',
  'Industrial connectivity and drones': 'Conectividad industrial y drones',
  'Marine robotics': 'Robótica marina',
  'Mobility platform': 'Plataforma de movilidad',
  'Pharmaceutical preparations (SIC 2834)': 'Preparados farmacéuticos (SIC 2834)',
  Pharmaceuticals: 'Farmacéutica',
  'Social platforms': 'Plataformas sociales',
  'Streaming entertainment': 'Entretenimiento en streaming',
  'Uranium mining': 'Minería de uranio',
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
  Communications: 'Comunicaciones',
  'Professional Services': 'Servicios profesionales',
  'Electrical Equipment': 'Equipamiento eléctrico',
  'Communication Equipment': 'Equipos de comunicación',
  'Electronic Components': 'Componentes electrónicos',
  'Computer Hardware': 'Hardware informático',
  Hardware: 'Hardware',
  'Information Technology Services': 'Servicios de tecnología',
  'Internet Content & Information': 'Contenido e información en internet',
  'Specialty Retail': 'Comercio especializado',
  'Auto Manufacturers': 'Fabricantes de automóviles',
  'Drug Manufacturers': 'Farmacéuticas',
  'Medical Devices': 'Dispositivos médicos',
  'Capital Markets': 'Mercados de capitales',
  'Asset Management': 'Gestión de activos',
  'Credit Services': 'Servicios de crédito',
  Entertainment: 'Entretenimiento',
  Gold: 'Oro',
  Copper: 'Cobre',
  Steel: 'Acero',
  Chemicals: 'Química',
  Machinery: 'Maquinaria',
  Airlines: 'Aerolíneas',
  Restaurants: 'Restaurantes',
  Solar: 'Solar',
  Uranium: 'Uranio',
  'Engineering & Construction': 'Ingeniería y construcción',
  'Building Products': 'Productos de construcción',
  'Packaged Foods': 'Alimentación envasada',
  'Semiconductor Equipment': 'Equipos de semiconductores',
  'Software - Application': 'Software de aplicaciones',
  'Software - Infrastructure': 'Software de infraestructura',
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
  tier_8_social: 'Redes sociales · sin verificar',
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
  legal_solicitation: 'Ruido: captación legal',
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
  sizing: 'Contribución ponderada',
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
  // «PUBLIC» es un securityType OpenFIGI (el estándar que usa Finnhub).
  // OpenFIGI no le da un significado de clase de activo: aparece también en
  // preferentes 144A (p. ej. BBG0001JJNS5 «SANTAN 6.41 PERP», marketSector
  // Pfd), así que cualquier traducción («acción», «emisión pública»…)
  // inferiría semántica que la fuente no afirma. Se muestra el código crudo
  // del estándar, sin traducir.
  PUBLIC: 'PUBLIC',
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

/** Tipos de empresa simples con etiqueta propia (no son factores). */
const TIPOS_EMPRESA: Record<string, string> = {
  ai_big_tech: 'big tech de IA',
  // Etiquetas exactas de los tipos compuestos del master cuyos tokens no
  // son todos factores: traducción fiel del concepto, sin reclasificar.
  ai_infra_capacity: 'infraestructura de IA',
  asset_manager_holding: 'holding gestora de activos',
  auto_energy_optionality: 'automoción con opcionalidad energética',
  china_adr_holding: 'holding china (ADR)',
  defense_contract_backlog: 'cartera de contratos de defensa',
  healthcare_regulatory: 'salud regulada',
  mining_pre_revenue: 'minería pre ingresos',
  platform_fcf_compounder: 'plataforma de crecimiento compuesto de FCL',
  software_ai_disruption: 'software en disrupción por IA',
  software_ai_platform: 'plataforma de software con IA',
  software_durable_growth: 'software de crecimiento duradero',
  space_defense_growth: 'espacio y defensa en crecimiento',
  speculative_scenario: 'escenario especulativo',
  subscriber_media: 'medios por suscripción',
  uranium_mining: 'minería de uranio',
  operating_company: 'empresa operativa',
  research_candidate: 'candidato de análisis',
  fund: 'fondo',
  etf: 'ETF',
  trust: 'trust',
};

/** Etiqueta ES del tipo de empresa de la ficha.
 * QA 23: el tipo compuesto «space_telecom_pre_fcf» se pintaba crudo
 * («space telecom pre fcf»). Se descompone en tokens de factores
 * conocidos (primero las claves de dos tokens: pre_fcf, small_cap...);
 * un token desconocido devuelve el tipo tal cual, nunca una etiqueta
 * inventada. */
export function companyTypeLabel(value: string): string {
  const exact = TIPOS_EMPRESA[value.toLowerCase()];
  if (exact) return exact;
  const tokens = value.toLowerCase().split('_');
  const labels: string[] = [];
  let i = 0;
  while (i < tokens.length) {
    const pair = tokens.slice(i, i + 2).join('_');
    if (i + 1 < tokens.length && FACTORES[pair]) {
      labels.push(FACTORES[pair]);
      i += 2;
    } else if (FACTORES[tokens[i]]) {
      labels.push(FACTORES[tokens[i]]);
      i += 1;
    } else {
      return value;
    }
  }
  return labels.join(' · ');
}

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

/** Mapa central de valores que el backend persiste como códigos (persistencia,
 *  tendencia y estado del foso, tipo de fuente, tier). Los cargadores de texto
 *  de usuario pasan por `etiquetaValor`; un código desconocido se muestra con
 *  guiones bajos convertidos en espacios, nunca inventado. */
const VALORES_BACKEND: Record<string, string> = {
  unproven: 'no probada',
  proven: 'probada',
  uncertain: 'incierta',
  improving: 'mejorando',
  deteriorating: 'deteriorándose',
  strengthening: 'reforzándose',
  weakening: 'debilitándose',
  moderate: 'moderada',
  durable: 'duradera',
  insufficient_evidence: 'evidencia insuficiente',
  insufficient_data: 'datos insuficientes',
  primary_official: 'oficial primaria',
  wacc_policy: 'política de WACC',
  damodaran: 'Damodaran (NYU Stern)',
  model_policy: 'política del modelo',
  calculated_metric: 'métrica calculada',
  financial_facts: 'datos financieros',
  historical_case: 'caso histórico',
  inferred_input: 'dato inferido',
  manual_transcript: 'transcripción manual',
  manual_upload: 'subida manual',
  sec_filing: 'informe SEC',
  earnings_call: 'llamada de resultados',
  investor_relations: 'relación con inversores',
  transcript: 'transcripción',
  yfinance: 'Yahoo Finance',
  yahoo_fundamentals: 'Yahoo Finance (fuente no oficial)',
  YAHOO_FUNDAMENTALS: 'Yahoo Finance (fuente no oficial)',
  user: 'usuario',
  chat: 'chat',
  url: 'enlace',
  brand: 'marca',
  capital_barrier: 'barrera de capital',
};

/** Etiqueta ES de un código del backend: primero tiers de fuente y el mapa
 *  central; si no está, el código con espacios en vez de guiones bajos. */
export function etiquetaValor(value: string): string {
  return TIERS_FUENTE[value] ?? VALORES_BACKEND[value] ?? value.replaceAll('_', ' ');
}
