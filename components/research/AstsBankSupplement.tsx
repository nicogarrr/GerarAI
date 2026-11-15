import type { Locale } from '@/lib/i18n/locale';
import type { TranslateFn } from '@/lib/i18n/translate';
import { ASTS_BANK_SUPPLEMENT as data } from '@/lib/research/asts-bank-supplement';

/** Isolated reading appendix: never feeds model facts or approved thesis versions. */
export function AstsBankSupplement({ ticker, locale, t }: { ticker: string; locale: Locale; t: TranslateFn }) {
  if (ticker.toUpperCase() !== 'ASTS') return null;
  const number = new Intl.NumberFormat(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const fields = [
    ['revenue', t('research.astsBankSupplement.revenue')],
    ['adjustedEbitda', t('research.astsBankSupplement.ebitda')],
    ['fcf', t('research.astsBankSupplement.fcf')],
    ['capex', t('research.astsBankSupplement.capex')],
    ['satellites', t('research.astsBankSupplement.satellites')],
  ] as const;
  return (
    <section aria-labelledby="asts-bank-title" className="my-8 min-w-0 max-w-full space-y-4 rounded-xl border border-amber-800/60 p-4 text-sm text-gray-200" data-testid="asts-bank-supplement">
      <h2 id="asts-bank-title" className="text-xl font-semibold">{t('research.astsBankSupplement.title')}</h2>
      <p role="note" className="text-amber-200">{t('research.astsBankSupplement.warning')}</p>
      <p className="text-xs text-gray-400">{t('research.astsBankSupplement.dates')}</p>
      <p>{t('research.astsBankSupplement.table')}</p>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {data.rows.map((row) => (
          <section key={row.year} className="min-w-0 rounded-lg border border-gray-800 p-3" aria-label={String(row.year)}>
            <h3 className="font-semibold">{row.year}{row.year > 2025 ? 'E' : ''}</h3>
            <dl className="mt-2 space-y-2">
              {fields.map(([field, label]) => (
                <div key={field} className="flex justify-between gap-4">
                  <dt className="min-w-0 text-gray-400">{label}</dt>
                  <dd className="shrink-0 tabular-nums">{row[field] === null ? t('research.astsBankSupplement.missing') : field === 'satellites' ? row[field] : number.format(row[field])}</dd>
                </div>
              ))}
            </dl>
          </section>
        ))}
      </div>
      <p>{t('research.astsBankSupplement.ramp')}</p>
      <p>{t('research.astsBankSupplement.funding')}</p>
      <p>{t('research.astsBankSupplement.blacklift')}</p>
      <ul className="space-y-2 break-words text-teal-300 underline">
        <li><a href={data.socialMirrorUrl} target="_blank" rel="noopener noreferrer">{t('research.astsBankSupplement.social')}</a></li>
        <li><a href={data.blackliftPrimaryUrl} target="_blank" rel="noopener noreferrer">{t('research.astsBankSupplement.primary')}</a></li>
      </ul>
      <p className="text-xs text-gray-400">{t('research.astsBankSupplement.exports')}</p>
    </section>
  );
}
