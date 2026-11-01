import { formatGeneratedDate } from '@/lib/format';
import { DEFAULT_LOCALE, type Locale } from '@/lib/i18n/locale';
import { createTranslator } from '@/lib/i18n/translate';
import { cleanThesisText } from '@/lib/research/thesis-text';

export type ThesisTextVersion = { status: string; version: number; created_at?: string | null; executive_summary?: string | null };

/** Publication alone does not establish that persisted valuation prose is usable. */
export function canShowThesisText(thesis: ThesisTextVersion, model: { publishable: boolean } | null | undefined): boolean {
  return (thesis.status === 'published' || thesis.status === 'approved') && model?.publishable === true;
}

export function WithheldThesisText({ thesis, model, locale = DEFAULT_LOCALE }: { thesis: ThesisTextVersion; model: { publishable: boolean } | null | undefined; locale?: Locale }) {
  const t = createTranslator(locale);
  const generated = formatGeneratedDate(thesis.created_at, undefined, locale);
  const reason = thesis.status !== 'published' && thesis.status !== 'approved'
    ? t('research.thesisWithheld.reasonNotPublic')
    : model?.publishable === false
      ? t('research.thesisWithheld.reasonNotPublishable')
      : t('research.thesisWithheld.reasonUnverified');
  return <p role="note" className="mt-3 rounded-lg border border-amber-900/60 bg-amber-950/20 p-3 text-sm leading-6 text-amber-200">
    {generated
      ? t('research.thesisWithheld.dated', { version: thesis.version, date: generated, reason })
      : t('research.thesisWithheld.undated', { version: thesis.version, reason })}
  </p>;
}

export function ThesisSummary({ thesis, model, locale = DEFAULT_LOCALE }: { thesis: ThesisTextVersion; model: { publishable: boolean } | null | undefined; locale?: Locale }) {
  return canShowThesisText(thesis, model)
    ? <p className="mt-3 line-clamp-3 text-sm leading-6 text-gray-300 md:line-clamp-none">{cleanThesisText(thesis.executive_summary)}</p>
    : <WithheldThesisText thesis={thesis} model={model} locale={locale} />;
}
