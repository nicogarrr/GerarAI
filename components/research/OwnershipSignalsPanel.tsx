import Link from 'next/link';
import { formatCountEs } from '@/lib/format';
import { DEFAULT_LOCALE, type Locale } from '@/lib/i18n/locale';
import { createTranslator } from '@/lib/i18n/translate';

import { Badge } from '@/components/ui/badge';
import { Panel } from '@/components/ui/panel';
import {
  holderChangeLabel,
  holdersLines,
  holdersTone,
  insiderLines,
  insiderTone,
  ownershipMoney,
  type OwnershipSignals,
  type OwnershipTone,
} from '@/lib/research/ownership-signals';

const TONE_CLASS: Record<OwnershipTone, string> = {
  positivo: 'border-teal-800 text-teal-300',
  negativo: 'border-red-900 text-red-300',
  neutro: 'border-gray-700 text-gray-300',
};

/**
 * Conexión 10b: insiders (Form 4) y fondos 13F del ticker, el mismo resumen
 * que lee la tesis (sección 24 del memo y hechos del narrador). Sin datos, se
 * dice por qué; nunca se pintan ceros como si fueran un dato.
 */
export function OwnershipSignalsPanel({ ticker, signals, locale = DEFAULT_LOCALE }: { ticker: string; signals: OwnershipSignals | null; locale?: Locale }) {
  const t = createTranslator(locale);
  const holdersHref = `/research/${encodeURIComponent(ticker)}?view=holders`;
  if (signals === null) {
    return (
      <Panel collapsible="mobile" title={t('research.ownershipSignals.title')}>
        <p className="text-sm text-gray-400">{t('research.ownershipSignals.loadError')}</p>
      </Panel>
    );
  }
  const { insider, holders } = signals;
  return (
    <Panel
      actions={<Link className="inline-flex min-h-[44px] sm:min-h-0 items-center text-sm text-teal-300" href={holdersHref}>{t('research.ownershipSignals.viewOwners')}</Link>}
      collapsible="mobile"
      title={t('research.ownershipSignals.title')}
    >
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <section aria-label={t('research.ownershipSignals.insidersLabel')}>
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-gray-200">{t('research.ownershipSignals.insidersTitle')}{insider.status === 'ok' ? t('research.ownershipSignals.windowDays', { days: insider.window_days }) : ''}</h3>
            {insider.status === 'ok' ? <Badge className={TONE_CLASS[insiderTone(insider)]} variant="outline">{insider.reading}</Badge> : null}
          </div>
          <ul className="space-y-1 text-sm text-gray-400">
            {insiderLines(insider, locale).map((line) => <li key={line}>{line}</li>)}
          </ul>
        </section>
        <section aria-label={t('research.ownershipSignals.fundsLabel')}>
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-gray-200">{t('research.ownershipSignals.fundsTitle')}</h3>
            {holders.status === 'ok' ? <Badge className={TONE_CLASS[holdersTone(holders)]} variant="outline">{formatCountEs(holders.holders_count, t('research.ownershipSignals.manager'), t('research.ownershipSignals.managers'), locale)}</Badge> : null}
          </div>
          <ul className="space-y-1 text-sm text-gray-400">
            {holdersLines(holders, locale).map((line) => <li key={line}>{line}</li>)}
          </ul>
          {holders.status === 'ok' && holders.top_holders.length ? (
            <ul className="mt-2 space-y-1 text-xs text-gray-500">
              {holders.top_holders.map((holder) => (
                <li key={holder.name}>
                  {holder.name}{holder.value_usd ? `: ${ownershipMoney(holder.value_usd, locale)}` : ''} ({holderChangeLabel(holder.change, locale)})
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      </div>
      <p className="mt-3 text-xs text-gray-500">{t('research.ownershipSignals.footer')}</p>
    </Panel>
  );
}
