/**
 * Informe frente al año anterior (filing_yoy_service.py y filing_changes.py):
 * el backend manda en castellano los motivos de «sin datos», la etiqueta del
 * análisis de texto y los nombres de sección. En inglés se traducen; en
 * castellano, y con un texto que no se reconoce, pasa el del backend tal cual.
 */
import type { Locale } from '@/lib/i18n/locale';

const FILINGS_YOY_EN: Record<string, string> = {
  'Sin informe comparable del mismo periodo del año anterior.': 'No comparable report for the same period of the prior year.',
  'Análisis de texto aún no generado para este informe.': 'Text analysis not generated yet for this report.',
  'Sin texto identificable en uno o ambos informes.': 'No identifiable text in one or both reports.',
  'Sección demasiado extensa para la comparación acotada.': 'Section too long for the bounded comparison.',
  'Comparación textual, no materialidad financiera': 'Text comparison, not financial materiality',
  'Factores de riesgo': 'Risk factors',
  'Perspectivas y guidance': 'Outlook and guidance',
  'Partes relacionadas': 'Related parties',
};

// f"Sin {form} oficial de la SEC guardado para esta empresa."
const NO_FORM = /^Sin (\S+) oficial de la SEC guardado para esta empresa\.$/;

export function filingsYoyText<T extends string | null | undefined>(text: T, locale: Locale): T | string {
  if (locale !== 'en' || !text) return text;
  if (Object.hasOwn(FILINGS_YOY_EN, text)) return FILINGS_YOY_EN[text];
  const form = NO_FORM.exec(text);
  return form ? `No official SEC ${form[1]} stored for this company.` : text;
}
