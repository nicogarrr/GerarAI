import { Panel } from '@/components/ui/panel';
import { naFor } from '@/lib/format';
import type { Locale } from '@/lib/i18n/locale';
import { createTranslator } from '@/lib/i18n/translate';
import { participationNumber, participationSource, type ParticipationResponse } from '@/lib/research/schedule13dg';

export function ParticipationFilingsPanel({ data, locale = 'es' }: { data: ParticipationResponse | null; locale?: Locale }) {
  const t = createTranslator(locale);
  const na = naFor(locale);
  return <Panel title={t('research.participation.title')}>
    <p className="mb-3 text-sm text-gray-400">{t('research.participation.intro')}</p>
    {data === null ? <p className="text-sm text-gray-400">{t('research.participation.loadError')}</p> : data.filings.length === 0 ?
      <p className="text-sm text-gray-400">{t('research.participation.empty')}</p> :
      <ul className="space-y-3">{data.filings.map(filing => {
        const source = participationSource(filing.source_url);
        return <li key={filing.accession_number} className="rounded-lg border border-gray-800 p-3 text-sm">
          <p className="font-medium text-gray-200">{filing.holder_name || t('research.participation.holderUnknown')} · {filing.form}</p>
          <p className="mt-1 text-gray-300">{t('research.participation.shares', { shares: participationNumber(filing.aggregate_shares, false, locale), percent: participationNumber(filing.percent_of_class, true, locale) })}</p>
          <p className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-gray-400"><span>{t('research.participation.positionAt', { date: filing.snapshot_date || na })}</span><span>{t('research.participation.filedOn', { date: filing.filing_date || na })}</span></p>
          {filing.status !== 'parsed' ? <p className="mt-1 text-xs text-amber-300">{t('research.participation.pending')}</p> : null}
          <p className="mt-1 text-xs text-gray-500">{filing.accession_number}{source ? <> · <a className="inline-flex min-h-11 items-center text-teal-300 underline" href={source} target="_blank" rel="noopener noreferrer">{t('research.participation.secDocument')}</a></> : ` · ${t('research.participation.sourceUnknown')}`}</p>
        </li>;
      })}</ul>}
  </Panel>;
}
