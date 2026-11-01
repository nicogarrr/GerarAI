/**
 * Presentación es-ES de los identificadores internos de fuentes y evidencia
 * (tipos, niveles, estados, tipos de entidad). Solo cambia la presentación;
 * nunca modifica claves ni cifras de la fuente. Los ids desconocidos se
 * humanizan (guiones bajos -> espacios) en vez de mostrarse en crudo.
 */
export const SOURCE_LABELS: Record<string, string> = {
  financial_facts: 'hechos financieros registrados',
  primary_official: 'Fuente oficial primaria',
  yahoo_finance_intraday: 'Yahoo Finance · intradía',
  yahoo_finance: 'Yahoo Finance',
  yfinance: 'Yahoo Finance',
  yahoo_fundamentals: 'Yahoo Finance (fuente no oficial)',
  YAHOO_FUNDAMENTALS: 'Yahoo Finance (fuente no oficial)',
  manual_upload: 'Subida manual',
  upload: 'Subida de archivo',
  manual: 'Manual',
  seed: 'Semilla inicial',
  company_ir: 'Relaciones con inversores',
  manual_transcript: 'Transcripción manual',
  filing: 'Documento regulatorio',
  transcript: 'Transcripción',
  sec: 'SEC EDGAR',
  esef: 'ESEF',
  cnmv: 'CNMV',
  url: 'URL',
  fmp: 'FMP',
  fmp_profile: 'Perfil FMP',
  gdelt: 'GDELT',
  calculated_metric: 'Métrica calculada',
};

type DisplayLocale = 'es' | 'en';

/**
 * En inglés: la tabla inglesa primero; los nombres propios (SEC EDGAR, ESEF,
 * Yahoo Finance...) no tienen entrada inglesa y salen de la tabla común.
 */
function pickLabel(es: Record<string, string>, en: Record<string, string>, value: string, locale: DisplayLocale): string {
  if (locale === 'en' && Object.hasOwn(en, value)) return en[value];
  return Object.hasOwn(es, value) ? es[value] : value.replaceAll('_', ' ');
}

/** Etiquetas en inglés de los ids de fuente que en es-ES se traducen. */
export const SOURCE_LABELS_EN: Record<string, string> = {
  financial_facts: 'recorded financial facts',
  primary_official: 'Primary official source',
  yahoo_finance_intraday: 'Yahoo Finance · intraday',
  yahoo_fundamentals: 'Yahoo Finance (unofficial source)',
  YAHOO_FUNDAMENTALS: 'Yahoo Finance (unofficial source)',
  manual_upload: 'Manual upload',
  upload: 'File upload',
  seed: 'Initial seed',
  company_ir: 'Investor relations',
  manual_transcript: 'Manual transcript',
  filing: 'Regulatory filing',
  transcript: 'Transcript',
  fmp_profile: 'FMP profile',
  calculated_metric: 'Calculated metric',
};

export function sourceDisplay(value: string, locale: DisplayLocale = 'es'): string {
  return pickLabel(SOURCE_LABELS, SOURCE_LABELS_EN, value, locale);
}

/** Nivel de fuente del backend (classify_source), etiquetado en es-ES. */
export const SOURCE_TIER_LABELS: Record<string, string> = {
  tier_1_regulatory: 'Regulador (T1)',
  tier_2_company: 'Compañía (T2)',
  tier_3_transcript: 'Transcripción (T3)',
  tier_4_reputable_media: 'Medio reputado (T4)',
  tier_5_data_provider: 'Proveedor de datos (T5)',
  tier_6_bootstrap: 'Semilla inicial (T6)',
  tier_7_user_input: 'Entrada del usuario (T7)',
  // classify_source devuelve tier_unknown cuando nada clasifica la fuente;
  // sin esta clave el fallback la humanizaba en crudo.
  tier_unknown: 'Fuente desconocida',
  primary: 'Primaria',
  secondary: 'Secundaria',
};

export const SOURCE_TIER_LABELS_EN: Record<string, string> = {
  tier_1_regulatory: 'Regulator (T1)',
  tier_2_company: 'Company (T2)',
  tier_3_transcript: 'Transcript (T3)',
  tier_4_reputable_media: 'Reputable media (T4)',
  tier_5_data_provider: 'Data provider (T5)',
  tier_6_bootstrap: 'Initial seed (T6)',
  tier_7_user_input: 'User input (T7)',
  tier_unknown: 'Unknown source',
  primary: 'Primary',
  secondary: 'Secondary',
};

export function sourceTierDisplay(value: string, locale: DisplayLocale = 'es'): string {
  return pickLabel(SOURCE_TIER_LABELS, SOURCE_TIER_LABELS_EN, value, locale);
}

/** Tipos de entidad de la búsqueda universal (universal_search_service.py). */
export const ENTITY_TYPE_LABELS: Record<string, string> = {
  document_chunk: 'Fragmento de documento',
  knowledge_chunk: 'Fragmento de conocimiento',
  thesis_section: 'Sección de tesis',
  investment_case: 'Caso de inversión',
  investment_principle: 'Principio de inversión',
  decision: 'Decisión',
  decision_lesson: 'Lección de decisión',
  claim: 'Afirmación',
  company_fact: 'Hecho financiero',
  document: 'Documento',
  news: 'Noticia',
};

export const ENTITY_TYPE_LABELS_EN: Record<string, string> = {
  document_chunk: 'Document excerpt',
  knowledge_chunk: 'Knowledge excerpt',
  thesis_section: 'Thesis section',
  investment_case: 'Investment case',
  investment_principle: 'Investment principle',
  decision: 'Decision',
  decision_lesson: 'Decision lesson',
  claim: 'Claim',
  company_fact: 'Financial fact',
  document: 'Document',
  news: 'News',
};

export function entityTypeDisplay(value: string, locale: DisplayLocale = 'es'): string {
  return pickLabel(ENTITY_TYPE_LABELS, ENTITY_TYPE_LABELS_EN, value, locale);
}

/** Estados canónicos de la evidencia (status de chunks, tesis, decisiones). */
export const EVIDENCE_STATUS_LABELS: Record<string, string> = {
  active: 'Activa',
  approved: 'Aprobada',
  verified: 'Verificada',
  draft: 'Borrador',
  proposed: 'Propuesta',
  rejected: 'Rechazada',
  superseded: 'Sustituida',
  archived: 'Archivada',
  deprecated: 'Obsoleta',
  published: 'Publicada',
  pending_review: 'Pendiente de revisión',
};

export const EVIDENCE_STATUS_LABELS_EN: Record<string, string> = {
  active: 'Active',
  approved: 'Approved',
  verified: 'Verified',
  draft: 'Draft',
  proposed: 'Proposed',
  rejected: 'Rejected',
  superseded: 'Superseded',
  archived: 'Archived',
  deprecated: 'Deprecated',
  published: 'Published',
  pending_review: 'Pending review',
};

export function evidenceStatusDisplay(value: string, locale: DisplayLocale = 'es'): string {
  return pickLabel(EVIDENCE_STATUS_LABELS, EVIDENCE_STATUS_LABELS_EN, value, locale);
}
