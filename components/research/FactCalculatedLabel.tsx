import type { ResearchFact } from '@/lib/actions/research.actions';
import type { Locale } from '@/lib/i18n/locale';
import { createTranslator } from '@/lib/i18n/translate';

/** A filing source does not make a derived value a reported value. */
export function FactCalculatedLabel({ fact, locale = 'es' }: { fact: Pick<ResearchFact, 'is_reported'>; locale?: Locale }) {
  return fact.is_reported === false
    ? <span className="ml-2 text-xs text-amber-300">{createTranslator(locale)('research.terminalSection.status.calculated')}</span>
    : null;
}
