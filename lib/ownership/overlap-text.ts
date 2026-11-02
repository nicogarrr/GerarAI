import type { Locale } from '@/lib/i18n/locale';

// investor_overlap.py manda en castellano el aviso de la vista «Solape con tu
// cartera» y de dónde sale el CUSIP de cada posición. Con inglés se traducen
// aquí; en castellano (o un texto que no conocemos) se pinta tal cual.
export const OVERLAP_TEXT_EN: Record<string, string> = {
  'Cartera sin posiciones abiertas.': 'Portfolio with no open positions.',
  'Sin informes 13F sincronizados.': 'No 13F reports synced.',
  'Identidad en conflicto: la referencia no corresponde al ticker.': 'Identity conflict: the reference does not match the ticker.',
  'Identidad en conflicto: los ISIN registrados no coinciden.': 'Identity conflict: the recorded ISINs do not match.',
  'Referencia CUSIP inválida.': 'Invalid CUSIP reference.',
  'Identidad en conflicto: CUSIP e ISIN de la referencia.': "Identity conflict: the reference's CUSIP and ISIN.",
  'Identidad en conflicto: CUSIP de referencia e ISIN de cartera.': "Identity conflict: the reference CUSIP and the portfolio's ISIN.",
  'CUSIP derivado del ISIN registrado': 'CUSIP derived from the recorded ISIN',
  'ISIN registrado sin CUSIP derivable verificado.': 'Recorded ISIN with no verified derivable CUSIP.',
  'ISIN de referencia sin CUSIP derivable verificado.': 'Reference ISIN with no verified derivable CUSIP.',
};

export function overlapText(text: string, locale: Locale): string;
export function overlapText(text: string | null | undefined, locale: Locale): string | null;
export function overlapText(text: string | null | undefined, locale: Locale): string | null {
  if (!text) return text ?? null;
  if (locale !== 'en') return text;
  const exact = OVERLAP_TEXT_EN[text];
  if (exact) return exact;
  // f"Referencia {reference.source} · {reference.as_of.isoformat()}"
  const reference = /^Referencia (.+) · (\d{4}-\d{2}-\d{2}\S*)$/.exec(text);
  return reference ? `Reference ${reference[1]} · ${reference[2]}` : text;
}
