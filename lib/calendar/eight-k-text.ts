/**
 * Resumen de 8-K del calendario macro (eight_k_digest.py): el backend manda
 * en castellano el título de cada apartado (por código SEC) y el motivo
 * cuando no hay texto legible. En inglés se muestran los títulos de la SEC y
 * los motivos traducidos; en castellano, y con lo que no se reconoce, pasa el
 * texto del backend tal cual.
 */
import type { Locale } from '@/lib/i18n/locale';

const ITEM_TITLES_EN: Record<string, string> = {
  '1.01': 'Entry into a Material Definitive Agreement',
  '1.02': 'Termination of a Material Definitive Agreement',
  '1.03': 'Bankruptcy or Receivership',
  '1.05': 'Material Cybersecurity Incidents',
  '2.01': 'Completion of Acquisition or Disposition of Assets',
  '2.02': 'Results of Operations and Financial Condition',
  '2.03': 'Creation of a Direct Financial Obligation',
  '2.04': 'Triggering Events That Accelerate a Direct Financial Obligation',
  '2.05': 'Costs Associated with Exit or Disposal Activities',
  '2.06': 'Material Impairments',
  '3.01': 'Notice of Delisting or Failure to Satisfy a Listing Rule',
  '3.02': 'Unregistered Sales of Equity Securities',
  '3.03': 'Material Modification to Rights of Security Holders',
  '4.01': 'Changes in Certifying Accountant',
  '4.02': 'Non-Reliance on Previously Issued Financial Statements',
  '5.01': 'Changes in Control of Registrant',
  '5.02': 'Departure or Appointment of Directors or Certain Officers',
  '5.03': 'Amendments to Articles or Bylaws; Change in Fiscal Year',
  '5.04': 'Temporary Suspension of Trading Under Employee Benefit Plans',
  '5.05': 'Amendments to the Code of Ethics',
  '5.07': 'Submission of Matters to a Vote of Security Holders',
  '5.08': 'Shareholder Director Nominations',
  '6.01': 'ABS Informational and Computational Material',
  '7.01': 'Regulation FD Disclosure',
  '8.01': 'Other Events',
  '9.01': 'Financial Statements and Exhibits',
};

const REASONS_EN: Record<string, string> = {
  'Sin posiciones ni watchlist.': 'No positions or watchlist.',
  'Sin texto completo disponible; se muestran solo los apartados declarados ante la SEC.':
    'Full text not available; only the items declared to the SEC are shown.',
  'Sin texto completo disponible; revisa el documento oficial.': 'Full text not available; check the official document.',
  'No se identificaron apartados legibles en el 8-K; se muestran los declarados ante la SEC.':
    'No readable items were identified in the 8-K; the items declared to the SEC are shown.',
  'No se identificaron apartados legibles en el 8-K.': 'No readable items were identified in the 8-K.',
  'Sin 8-K relevantes de tus compañías.': 'No relevant 8-Ks from your companies.',
};

export function eightKItemTitle(item: { code: string; title: string }, locale: Locale): string {
  if (locale !== 'en') return item.title;
  if (Object.hasOwn(ITEM_TITLES_EN, item.code)) return ITEM_TITLES_EN[item.code];
  const generic = /^Apartado (\S+)$/.exec(item.title.trim());
  return generic ? `Item ${generic[1]}` : item.title;
}

export function eightKReason(reason: string, locale: Locale): string;
export function eightKReason(reason: string | null | undefined, locale: Locale): string | null | undefined;
export function eightKReason(reason: string | null | undefined, locale: Locale): string | null | undefined {
  if (locale !== 'en' || !reason) return reason;
  return Object.hasOwn(REASONS_EN, reason) ? REASONS_EN[reason] : reason;
}
