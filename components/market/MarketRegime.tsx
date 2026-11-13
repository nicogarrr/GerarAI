import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import BackendOffline from '@/components/system/BackendOffline';
import type { MarketRegime, RegimeComputedMetric, RegimeObservedMetric, RegimeStatusBlock, RegimeTopTen } from '@/lib/actions/market-regime.actions';
import { getMarketRegimeResult } from '@/lib/actions/market-regime.actions';
import { isBackendUnavailableError } from '@/lib/backend-offline';
import { formatNumber, type Formatters } from '@/lib/format';
import { getFormat, getT } from '@/lib/i18n/server';
import type { Locale } from '@/lib/i18n/locale';
import { createTranslator, type TranslateFn } from '@/lib/i18n/translate';
import type { TranslationKey } from '@/lib/i18n/t';
import moversEs from '@/lib/i18n/messages/es/movers.json';

/**
 * Vista «Régimen» de la seccion Mercado: pinta el ultimo snapshot de
 * /api/market/regime exactamente como viene declarado. Cada bloque muestra su
 * fecha y su fuente; lo que el snapshot no declara queda como «Sin datos»,
 * nunca rellenado.
 */

/** «1 sesión» / «N sesiones»: concordancia es-ES del conteo de entrenamiento. */
export function trainingSessionsText(count: number, locale: Locale = 'es'): string {
  const n = formatNumber(count, { maximumFractionDigits: 0 }, undefined, locale);
  return createTranslator(locale)(count === 1 ? 'movers.regime.trainingSessionOne' : 'movers.regime.trainingSessionMany', { n });
}

const METRICAS: { key: keyof MarketRegime['metrics']; labelKey: TranslationKey }[] = [
  { key: 'treasury_10y_us', labelKey: 'movers.regime.metrics.treasury_10y_us' },
  { key: 'treasury_2y_us', labelKey: 'movers.regime.metrics.treasury_2y_us' },
  { key: 'yield_curve_10y_2y_us', labelKey: 'movers.regime.metrics.yield_curve_10y_2y_us' },
  { key: 'breakeven_10y_us', labelKey: 'movers.regime.metrics.breakeven_10y_us' },
  { key: 'high_yield_spread_us', labelKey: 'movers.regime.metrics.high_yield_spread_us' },
  { key: 'vix_us', labelKey: 'movers.regime.metrics.vix_us' },
  { key: 'mortgage_30y_us', labelKey: 'movers.regime.metrics.mortgage_30y_us' },
];

/** Valor con la unidad declarada; unidades desconocidas se muestran tal cual. */
function valorMetrica(m: { value: number; unit: string }, fmt: Formatters): string {
  const n = fmt.formatNumber(m.value, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (m.unit === 'porcentaje') return fmt.locale === 'en' ? `${n}%` : `${n} %`;
  if (m.unit === 'puntos porcentuales') return `${n} pp`;
  if (m.unit === 'índice') return n;
  return `${n} ${m.unit}`;
}

function TarjetaMetrica({ label, metrica, t, fmt }: { label: string; metrica?: RegimeObservedMetric | RegimeComputedMetric; t: TranslateFn; fmt: Formatters }) {
  return (
    <Card className="min-w-0 border-gray-800">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium break-words text-gray-400">{label}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-1">
        {metrica ? (
          <>
            <p className="text-xl font-semibold text-gray-100">{valorMetrica(metrica, fmt)}</p>
            <p className="text-xs text-gray-500">{t('movers.regime.dataOf', { date: fmt.formatMarketDate(metrica.date) })}</p>
            {'method' in metrica && metrica.method ? (
              <p className="text-xs text-gray-500">{textoRegimen(metrica.method, fmt.locale)}</p>
            ) : null}
          </>
        ) : (
          <p className="text-sm text-gray-500">{t('movers.regime.noData')}</p>
        )}
      </CardContent>
    </Card>
  );
}

function TarjetaHmm({ regimen, t, fmt }: { regimen: MarketRegime; t: TranslateFn; fmt: Formatters }) {
  const hmm = regimen.metrics.hmm;
  const estados = Object.entries(regimen.probabilities ?? {});
  return (
    <Card className="min-w-0 border-gray-800">
      <CardHeader className="pb-2">
        <CardTitle className="text-base break-words">{t('movers.regime.hmmTitle')}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-1">
        {hmm?.status === 'disponible' && estados.length > 0 ? (
          <>
            <ul className="space-y-1">
              {estados.map(([estado, prob]) => (
                <li key={estado} className="flex items-baseline justify-between gap-2">
                  <span className="text-sm text-gray-400">{estado.startsWith('state_') ? t('movers.regime.state', { n: estado.slice('state_'.length) }) : estado}</span>
                  <span className="text-lg font-semibold text-gray-100">{fmt.formatPercent(prob)}</span>
                </li>
              ))}
            </ul>
            {hmm.date ? <p className="text-xs text-gray-500">{t('movers.regime.filterAt', { date: fmt.formatMarketDate(hmm.date) })}</p> : null}
            {hmm.trained_through ? (
              <p className="text-xs text-gray-500">
                {t('movers.regime.trainedThrough', { date: fmt.formatMarketDate(hmm.trained_through) })}
                {typeof hmm.training_sessions === 'number' ? ` · ${trainingSessionsText(hmm.training_sessions, fmt.locale)}` : ''}
              </p>
            ) : null}
            {hmm.method ? <p className="text-xs text-gray-500">{textoRegimen(hmm.method, fmt.locale)}</p> : null}
          </>
        ) : (
          <>
            <p className="text-sm text-gray-500">{t('movers.regime.noData')}</p>
            {hmm?.reason ? <p className="text-xs text-gray-500">{textoRegimen(hmm.reason, fmt.locale)}</p> : null}
          </>
        )}
      </CardContent>
    </Card>
  );
}

function TarjetaConcentracion({ top, t, fmt }: { top?: RegimeTopTen; t: TranslateFn; fmt: Formatters }) {
  const disponible = top?.status === 'disponible' && typeof top.weight_top_ten_pct === 'number';
  return (
    <Card className="min-w-0 border-gray-800">
      <CardHeader className="pb-2">
        <CardTitle className="text-base break-words">
          {t('movers.regime.concentrationTitle')}{top?.index ? ` · ${top.index}` : ''}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-1">
        {disponible ? (
          <>
            <p className="text-xl font-semibold text-gray-100">
              {fmt.formatPercent(top.weight_top_ten_pct as number, { fromRatio: false })}
            </p>
            {typeof top.weight_largest_pct === 'number' ? (
              <p className="text-xs text-gray-500">
                {t('movers.regime.largestWeight', { value: fmt.formatPercent(top.weight_largest_pct, { fromRatio: false }) })}
              </p>
            ) : null}
            {top.snapshot_as_of ? (
              <p className="text-xs text-gray-500">{t('movers.regime.snapshotOf', { date: fmt.formatMarketDate(top.snapshot_as_of) })}</p>
            ) : null}
          </>
        ) : (
          <>
            <p className="text-sm text-gray-500">{t('movers.regime.noData')}</p>
            {motivoConcentracionSinDatos(top, fmt.locale)}
            {top?.snapshot_as_of ? (
              <p className="text-xs text-gray-500">{t('movers.regime.snapshotChecked', { date: fmt.formatMarketDate(top.snapshot_as_of) })}</p>
            ) : null}
          </>
        )}
      </CardContent>
    </Card>
  );
}

// El backend devuelve `reason` (código estable) y `detail` (diagnóstico para
// operación: puede llevar rutas del servidor o nombres de variables de
// entorno, p. ej. «SP500_FACTSHEET_DIR sin definir» o snapshots antiguos con
// «/data/...»). En pantalla solo texto para la persona usuaria.

/**
 * Motivos y métodos que el motor declara en español (bloque HMM, beta de
 * cartera, curva 10a−2a). Con el inglés elegido se muestran traducidos; un
 * texto que no está en la lista se muestra tal cual.
 */
// Se cruza el texto exacto del motor con claves del diccionario; los textos
// nuevos o desconocidos siguen visibles, nunca se inventa una traducción.
const TEXTO_REGIMEN_KEYS = new Map<string, TranslationKey>([
  [moversEs.regime.backendText.nonConsecutiveSessions, 'movers.regime.backendText.nonConsecutiveSessions'],
  [moversEs.regime.backendText.zeroBenchmarkVariance, 'movers.regime.backendText.zeroBenchmarkVariance'],
  [moversEs.regime.backendText.incompleteConstituents, 'movers.regime.backendText.incompleteConstituents'],
  [moversEs.regime.backendText.incompleteMarketCaps, 'movers.regime.backendText.incompleteMarketCaps'],
  [moversEs.regime.backendText.insufficientHistory, 'movers.regime.backendText.insufficientHistory'],
  [moversEs.regime.backendText.invalidValues, 'movers.regime.backendText.invalidValues'],
  [moversEs.regime.backendText.constantSeries, 'movers.regime.backendText.constantSeries'],
  [moversEs.regime.backendText.fitNotConverged, 'movers.regime.backendText.fitNotConverged'],
  [moversEs.regime.backendText.invalidProbability, 'movers.regime.backendText.invalidProbability'],
  [moversEs.regime.backendText.modelUnavailable, 'movers.regime.backendText.modelUnavailable'],
  [moversEs.regime.backendText.missingRecentObservations, 'movers.regime.backendText.missingRecentObservations'],
  [moversEs.regime.backendText.noPositionsOrBenchmark, 'movers.regime.backendText.noPositionsOrBenchmark'],
  [moversEs.regime.backendText.benchmarkNoAdjustedCloses, 'movers.regime.backendText.benchmarkNoAdjustedCloses'],
  [moversEs.regime.backendText.portfolioBetaUnavailable, 'movers.regime.backendText.portfolioBetaUnavailable'],
  [moversEs.regime.backendText.globalMacroNoPortfolioMix, 'movers.regime.backendText.globalMacroNoPortfolioMix'],
  [moversEs.regime.backendText.gaussianHmmMethod, 'movers.regime.backendText.gaussianHmmMethod'],
  [moversEs.regime.backendText.yieldCurveMethod, 'movers.regime.backendText.yieldCurveMethod'],
  [moversEs.regime.backendText.portfolioBetaMethod, 'movers.regime.backendText.portfolioBetaMethod'],
  [moversEs.regime.backendText.filteredProbabilitiesNote, 'movers.regime.backendText.filteredProbabilitiesNote'],
]);
const MOTIVO_CONCENTRACION_SIN_DATOS = new Map<string, TranslationKey>([
  ['no_snapshot_in_disk', 'movers.regime.concentrationReasons.no_snapshot_in_disk'],
  ['snapshot_dir_not_configured', 'movers.regime.concentrationReasons.snapshot_dir_not_configured'],
  ['snapshot_integrity_failed', 'movers.regime.concentrationReasons.snapshot_integrity_failed'],
  ['snapshot_vintage_after_requested_date', 'movers.regime.concentrationReasons.snapshot_vintage_after_requested_date'],
  ['requested_date_invalid', 'movers.regime.concentrationReasons.requested_date_invalid'],
  ['snapshot_too_stale_for_requested_date', 'movers.regime.concentrationReasons.snapshot_too_stale_for_requested_date'],
  ['index_weights_not_published_by_source', 'movers.regime.concentrationReasons.index_weights_not_published_by_source'],
]);

export function textoRegimen(text: string, locale: Locale = 'es'): string {
  const key = TEXTO_REGIMEN_KEYS.get(text);
  return locale === 'en' && key ? createTranslator(locale)(key) : text;
}

function motivoConcentracionSinDatos(top?: RegimeTopTen, locale: Locale = 'es') {
  if (!top?.reason && !top?.detail) return null;
  const key = top.reason ? MOTIVO_CONCENTRACION_SIN_DATOS.get(top.reason) : undefined;
  const motivo = createTranslator(locale)(key ?? 'movers.regime.concentrationReasons.snapshot_dir_not_configured');
  return <p className="text-xs text-gray-500">{motivo}</p>;
}

function TarjetaBeta({ beta, t, locale = 'es' }: { beta?: RegimeStatusBlock; t: TranslateFn; locale?: Locale }) {
  return (
    <Card className="min-w-0 border-gray-800">
      <CardHeader className="pb-2">
        <CardTitle className="text-base break-words">{t('movers.regime.betaTitle')}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-1">
        <p className="text-sm text-gray-500">{beta?.status === 'no_disponible' ? t('movers.regime.unavailable') : t('movers.regime.noData')}</p>
        {beta?.reason ? <p className="text-xs text-gray-500">{textoRegimen(beta.reason, locale)}</p> : null}
      </CardContent>
    </Card>
  );
}

function estadoBadge(status: string, t: TranslateFn): { label: string; variant: 'default' | 'secondary' | 'outline' } {
  if (status === 'disponible') return { label: t('movers.regime.status.available'), variant: 'default' };
  if (status === 'obsoleto') return { label: t('movers.regime.status.stale'), variant: 'secondary' };
  if (status === 'sin datos') return { label: t('movers.regime.status.noData'), variant: 'outline' };
  return { label: status, variant: 'outline' };
}

export async function MarketRegimeVista() {
  const { data: regimen, error } = await getMarketRegimeResult();
  const t = await getT();
  const fmt = await getFormat();
  if (error || !regimen) {
    if (error && isBackendUnavailableError(error)) {
      return <BackendOffline as="section" feature={t('movers.regime.feature')} retryHref="/screener?vista=regimen" />;
    }
    throw error ?? new Error(t('movers.regime.noResponse'));
  }
  const estado = estadoBadge(regimen.status, t);
  const sinSnapshot = !regimen.date;
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={estado.variant}>{estado.label}</Badge>
        {regimen.date ? (
          <p className="text-sm text-gray-400">
            {t('movers.regime.snapshotOf', { date: fmt.formatMarketDate(regimen.date) })}
            {regimen.generated_at
              ? ` · ${t('movers.regime.generated', { datetime: fmt.formatUserDateTime(regimen.generated_at, { hour: '2-digit', minute: '2-digit', timeZoneName: 'short' }) })}`
              : ''}
          </p>
        ) : null}
      </div>

      {sinSnapshot ? (
        <p className="text-sm text-gray-500">{t('movers.regime.empty')}</p>
      ) : (
        <>
          <div className="grid min-w-0 grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-3">
            {METRICAS.map(({ key, labelKey }) => (
              <TarjetaMetrica
                key={key}
                label={t(labelKey)}
                t={t}
                fmt={fmt}
                metrica={regimen.metrics[key] as RegimeObservedMetric | RegimeComputedMetric | undefined}
              />
            ))}
          </div>
          <div className="grid min-w-0 grid-cols-1 gap-3 sm:gap-4 lg:grid-cols-3">
            <TarjetaHmm regimen={regimen} t={t} fmt={fmt} />
            <TarjetaConcentracion top={regimen.metrics.top_ten_sp500} t={t} fmt={fmt} />
            <TarjetaBeta beta={regimen.portfolio_beta ?? regimen.metrics.portfolio_beta} t={t} locale={fmt.locale} />
          </div>
          {regimen.note ? <p className="text-xs text-gray-500">{textoRegimen(regimen.note, fmt.locale)}</p> : null}
        </>
      )}
    </div>
  );
}

