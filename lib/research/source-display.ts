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

export function sourceDisplay(value: string): string {
  return Object.hasOwn(SOURCE_LABELS, value) ? SOURCE_LABELS[value] : value.replaceAll('_', ' ');
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

export function sourceTierDisplay(value: string): string {
  return Object.hasOwn(SOURCE_TIER_LABELS, value) ? SOURCE_TIER_LABELS[value] : value.replaceAll('_', ' ');
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

export function entityTypeDisplay(value: string): string {
  return Object.hasOwn(ENTITY_TYPE_LABELS, value) ? ENTITY_TYPE_LABELS[value] : value.replaceAll('_', ' ');
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

export function evidenceStatusDisplay(value: string): string {
  return Object.hasOwn(EVIDENCE_STATUS_LABELS, value) ? EVIDENCE_STATUS_LABELS[value] : value.replaceAll('_', ' ');
}
