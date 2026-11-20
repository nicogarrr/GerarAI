import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { VixContext } from '@/lib/actions/market-regime.actions';
import type { Locale } from '@/lib/i18n/locale';
import { createTranslator } from '@/lib/i18n/translate';

/** Read-only context. No orders, DCA multipliers or portfolio actions. */
export function VixContextCard({ context, locale }: { context?: VixContext; locale: Locale }) {
  const t = createTranslator(locale);
  const fresh = context?.status === 'available'
    && typeof context.value === 'number' && Number.isFinite(context.value) && context.value > 0
    && ['low', 'middle', 'high'].includes(context.band ?? '')
    && context.source_url === 'https://fred.stlouisfed.org/series/VIXCLS'
    && /^\d{4}-\d{2}-\d{2}$/.test(context.date ?? '')
    && Number.isFinite(Date.parse(`${context.date}T00:00:00Z`));
  const band = context?.band;
  const label = !fresh ? t('movers.regime.vixContext.unavailable')
    : band === 'high' ? t('movers.regime.vixContext.high')
    : band === 'low' ? t('movers.regime.vixContext.low')
    : t('movers.regime.vixContext.middle');
  return (
    <Card className="min-w-0 border-gray-800">
      <CardHeader className="pb-2"><CardTitle className="text-base">{t('movers.regime.vixContext.title')}</CardTitle></CardHeader>
      <CardContent className="space-y-2 break-words text-sm">
        <p className="font-medium text-gray-100">{label}{fresh ? ` · ${context.value!.toLocaleString(locale === 'es' ? 'es-ES' : 'en-US', { maximumFractionDigits: 2, minimumFractionDigits: 2 })}` : ''}</p>
        {fresh && context.date ? <p className="text-xs text-gray-400">{t('movers.regime.vixContext.close', { date: context.date })}</p> : null}
        <p className="text-gray-400">{!fresh ? t('movers.regime.vixContext.noSignal') : band === 'high' ? t('movers.regime.vixContext.highNote') : band === 'low' ? t('movers.regime.vixContext.lowNote') : t('movers.regime.vixContext.middleNote')}</p>
        <p className="text-xs text-gray-500">{t('movers.regime.vixContext.thresholds')}</p>
        <p className="text-xs text-gray-500">{t('movers.regime.vixContext.limits')}</p>
      </CardContent>
    </Card>
  );
}
