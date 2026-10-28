export const SOURCE_LABELS: Record<string, string> = {
  primary_official: 'Fuente oficial primaria',
  yahoo_finance_intraday: 'Yahoo Finance · intradía',
  yahoo_finance: 'Yahoo Finance',
  yfinance: 'Yahoo Finance',
  yahoo_fundamentals: 'Yahoo Finance (fuente no oficial)',
  YAHOO_FUNDAMENTALS: 'Yahoo Finance (fuente no oficial)',
  manual_upload: 'Subida manual',
  company_ir: 'Relaciones con inversores',
  manual_transcript: 'Transcripción manual',
  filing: 'Documento regulatorio',
  transcript: 'Transcripción',
  sec: 'SEC EDGAR',
  gdelt: 'GDELT',
  calculated_metric: 'Métrica calculada',
};

/** Solo cambia la presentación; nunca modifica claves ni cifras de la fuente. */
export function sourceDisplay(value: string): string {
  return Object.hasOwn(SOURCE_LABELS, value) ? SOURCE_LABELS[value] : value.replaceAll('_', ' ');
}
