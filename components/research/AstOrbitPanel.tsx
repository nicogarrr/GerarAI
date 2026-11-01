import Link from 'next/link';

import type { AstOrbitObject, AstOrbitOverview, AstsAnalysis } from '@/lib/actions/asts-orbits.actions';
import { formatNumber, formatUserDateTime } from '@/lib/format';
import { Panel } from '@/components/ui/panel';
import { DEFAULT_LOCALE, type Locale } from '@/lib/i18n/locale';
import { createTranslator, type TranslateFn } from '@/lib/i18n/translate';
import { AstSmaChart } from '@/components/research/AstSmaChart';

function SourceObjects({ objects, t, locale }: { objects: AstOrbitObject[]; t: TranslateFn; locale: Locale }) {
  const num = (value: number | null, options: Intl.NumberFormatOptions) => formatNumber(value, options, undefined, locale);
  const dt = (value: string) => formatUserDateTime(value, undefined, undefined, locale);
  return <ul className="grid min-w-0 gap-3 lg:grid-cols-2">
    {objects.map((item) => <li className="min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-4" key={item.norad_cat_id}>
      <div className="flex flex-wrap items-baseline justify-between gap-2"><h3 className="break-words font-semibold text-gray-100">{item.object_name}</h3><span className="text-xs text-gray-500">NORAD {item.norad_cat_id}</span></div>
      <p className="mt-2 text-sm text-gray-300">{t('research.astOrbit.smaLine', { value: item.sma_km === null ? t('research.astOrbit.noData') : `${num(item.sma_km, { maximumFractionDigits: 1 })} km` })}</p>
      <p className="mt-1 text-sm text-gray-300">{t('research.astOrbit.trendLine', { value: item.signal.delta_sma_km === null ? item.signal.status : t('research.astOrbit.trendDelta', { delta: `${item.signal.delta_sma_km > 0 ? '+' : ''}${num(item.signal.delta_sma_km, { maximumFractionDigits: 2 })}`, hours: num(item.signal.hours, { maximumFractionDigits: 0 }) }) })}</p>
      {item.signal.delta_sma_km !== null ? <p className="mt-1 text-sm text-amber-300">{item.signal.status}</p> : null}
      <p className="mt-2 text-xs text-gray-500">{t('research.astOrbit.epochLine', { date: dt(item.epoch), count: item.history.length })}</p>
      <AstSmaChart history={item.history} locale={locale} name={item.object_name} />
      <details className="mt-3"><summary className="min-h-11 cursor-pointer py-3 text-sm text-teal-300">{t('research.astOrbit.epochData')}</summary><div className="max-h-52 overflow-auto rounded-md border border-gray-800 p-2 text-xs text-gray-300">{item.history.length ? item.history.map((sample) => <p className="flex flex-wrap justify-between gap-2 border-b border-gray-800 py-2 last:border-0" key={sample.epoch}><span>{dt(sample.epoch)}</span><span>{num(sample.sma_km, { maximumFractionDigits: 1 })} km</span></p>) : <p>{t('research.astOrbit.noHistory')}</p>}</div></details>
    </li>)}
  </ul>;
}

function CatalogReading({ analysis, t }: { analysis: AstsAnalysis | null; t: TranslateFn }) {
  const reading = analysis?.status === 'disponible' ? analysis.analysis : null;
  if (!analysis || !reading) {
    return <Panel title={t('research.astOrbit.catalogReading')}><p className="text-sm text-gray-400">{analysis ? t('research.astOrbit.catalogStale') : t('research.astOrbit.catalogUnavailable')}</p></Panel>;
  }
  const interpretation = reading.llm_interpretation;
  return <Panel title={t('research.astOrbit.catalogReading')}>
    <p className="text-sm leading-6 text-gray-300">{reading.summary}</p>
    <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-gray-300">
      {reading.observations.map((item) => <li key={item.text}>{item.text}</li>)}
    </ul>
    {interpretation ? <div className="mt-4 rounded-md border border-gray-800 p-3">
      <h3 className="text-sm font-semibold text-gray-100">{t('research.astOrbit.aiInterpretation')}</h3>
      <p className="mt-2 text-sm leading-6 text-gray-300">{interpretation.summary}</p>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-gray-300">
        {interpretation.observations.map((item) => <li key={item.text}>{item.text}</li>)}
      </ul>
    </div> : null}
  </Panel>;
}

export function AstOrbitPanel({ data, analysis, locale = DEFAULT_LOCALE }: { data: AstOrbitOverview | null; analysis: AstsAnalysis | null; locale?: Locale }) {
  const t = createTranslator(locale);
  const dt = (value: string) => formatUserDateTime(value, undefined, undefined, locale);
  const supgp = data?.supgp;
  return <div className="space-y-5">
    <Panel title={t('research.astOrbit.title')} description={t('research.astOrbit.description')}>
      <p className="text-sm leading-6 text-gray-300">{data?.usage_note ?? t('research.astOrbit.usageFallback')}</p>
      <p className="mt-3 text-xs text-gray-500">{t('research.astOrbit.cadence', { hours: data?.cadence_hours ?? 2 })}</p>
    </Panel>
    <CatalogReading analysis={analysis} t={t} />
    <section className="space-y-3" aria-label={t('research.astOrbit.gpHistory')}>
      <h2 className="text-lg font-semibold text-gray-100">{t('research.astOrbit.gpCatalog')}</h2>
      <p className="text-xs text-gray-400">{t('research.astOrbit.gpLastDownload', { date: data?.fetched_at ? dt(data.fetched_at) : t('research.astOrbit.noData') })}</p>
      {data?.status === 'disponible' && data.objects.length ? <SourceObjects locale={locale} objects={data.objects} t={t} /> : <Panel title={t('research.astOrbit.gpObjects')}><p className="text-sm text-gray-400">{t('research.astOrbit.gpEmpty')}</p></Panel>}
    </section>
    <section className="space-y-3" aria-label={t('research.astOrbit.supgpHistory')}>
      <h2 className="text-lg font-semibold text-gray-100">{t('research.astOrbit.supgpTitle')}</h2>
      <p className="text-xs text-gray-400">{t('research.astOrbit.supgpLastDownload', { date: supgp?.fetched_at ? dt(supgp.fetched_at) : t('research.astOrbit.noData') })}</p>
      {supgp?.status === 'disponible' && supgp.objects.length ? <SourceObjects locale={locale} objects={supgp.objects} t={t} /> : <Panel title={t('research.astOrbit.supgpObjects')}><p className="text-sm text-gray-400">{t('research.astOrbit.supgpEmpty')}</p></Panel>}
    </section>
    <p className="text-xs leading-5 text-gray-500">{t('research.astOrbit.disclaimer')}</p>
    <Link className="text-sm text-teal-300 hover:underline" href="/metodologia">{t('research.astOrbit.methodLink')}</Link>
  </div>;
}
