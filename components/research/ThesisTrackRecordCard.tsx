'use client';
import type { components } from '@/lib/research/openapi.generated';
import { useFormat, useT } from '@/lib/i18n/client';

type TrackRecord = components['schemas']['CompanyTrackRecordOut'];
type HorizonStats = components['schemas']['TrackRecordHorizonOut'];

const HORIZONS = ['6M', '12M'] as const;

/**
 * «Nuestro acierto»: cómo acertaron nuestros valores razonables contra el
 * precio real a 6 y 12 meses. Hasta que vence el primer horizonte enseña la
 * fecha del primer resultado; sin tesis con valor razonable no se pinta.
 */
export function ThesisTrackRecordCard({ data }: { data: TrackRecord | null }) {
  const t = useT();
  const fmt = useFormat();
  // Solo los dos estados con contenido; una respuesta sin la forma esperada no pinta nada.
  if (!data || (data.status !== 'pending' && data.status !== 'ready') || typeof data.horizons !== 'object' || !data.horizons) return null;
  const horizonLabel = (h: string) => (h === '12M' ? t('ui.thesisTrackRecord.months12') : t('ui.thesisTrackRecord.months6'));
  const pct = (value: number | null | undefined, sign = false) =>
    value === null || value === undefined
      ? fmt.na
      : fmt.formatPercent(value, { fromRatio: true, digits: 0, signDisplay: sign ? 'always' : 'auto' });
  const firstDate = data.first_maturity_date
    ? fmt.formatMarketDate(data.first_maturity_date, { day: '2-digit', month: '2-digit', year: 'numeric' })
    : null;
  return (
    <section aria-labelledby="track-record-title" className="mt-6 rounded-xl border border-gray-800 bg-surface-1 p-4" data-testid="thesis-track-record">
      <h3 id="track-record-title" className="text-sm font-semibold text-gray-100">{t('ui.thesisTrackRecord.title')}</h3>
      <p className="mt-1 text-xs leading-5 text-gray-400">{t('ui.thesisTrackRecord.description')}</p>
      {data.status === 'pending' ? (
        <p className="mt-3 text-sm text-gray-300" data-testid="thesis-track-record-pending">
          {firstDate ? t('ui.thesisTrackRecord.firstResult', { date: firstDate }) : t('ui.thesisTrackRecord.noMatured')}
        </p>
      ) : (
        <>
          <dl className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
            {HORIZONS.map((h) => {
              const stats: HorizonStats | undefined = data.horizons?.[h];
              const best = data.best_horizon === h;
              return (
                <div key={h} className={best ? 'min-w-0 rounded-lg border border-teal-700/60 p-3' : 'min-w-0 rounded-lg border border-gray-800 p-3'} data-testid={`thesis-track-record-${h}`}>
                  <dt className="flex flex-wrap items-baseline justify-between gap-x-2 text-xs text-gray-500">
                    <span>{horizonLabel(h)}</span>
                    {best ? <span className="font-medium text-teal-300">{t('ui.thesisTrackRecord.bestBadge')}</span> : null}
                  </dt>
                  {!stats || stats.samples === 0 ? (
                    <dd className="mt-1 text-sm text-gray-400">{t('ui.thesisTrackRecord.horizonPending')}</dd>
                  ) : (
                    <dd className="mt-1 space-y-0.5 text-sm text-gray-200">
                      <p><span className="font-medium tabular-nums text-gray-100">{pct(stats.hit_rate)}</span> {t('ui.thesisTrackRecord.hitRate', { hits: stats.hits, samples: stats.samples })}</p>
                      <p><span className="tabular-nums">{pct(stats.median_signed_error, true)}</span> {t('ui.thesisTrackRecord.medianError')}</p>
                      <p><span className="tabular-nums">{pct(stats.touched_rate)}</span> {t('ui.thesisTrackRecord.touched')}</p>
                    </dd>
                  )}
                </div>
              );
            })}
          </dl>
          <p className="mt-3 text-xs text-gray-400" data-testid="thesis-track-record-best">
            {data.best_horizon
              ? t('ui.thesisTrackRecord.best', { horizon: horizonLabel(data.best_horizon) })
              : t('ui.thesisTrackRecord.bestInsufficient', { min: data.min_samples_best_horizon })}
          </p>
        </>
      )}
    </section>
  );
}
