import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import BackendOffline from '@/components/system/BackendOffline';
import type { MarketRegime, RegimeComputedMetric, RegimeObservedMetric, RegimeStatusBlock, RegimeTopTen } from '@/lib/actions/market-regime.actions';
import { getMarketRegimeResult } from '@/lib/actions/market-regime.actions';
import { isBackendUnavailableError } from '@/lib/backend-offline';
import { formatNumber, type Formatters } from '@/lib/format';
import { getFormat, getT } from '@/lib/i18n/server';
import type { Locale } from '@/lib/i18n/locale';
import type { TranslateFn } from '@/lib/i18n/translate';

/**
 * Vista «Régimen» de la seccion Mercado: pinta el ultimo snapshot de
 * /api/market/regime exactamente como viene declarado. Cada bloque muestra su
 * fecha y su fuente; lo que el snapshot no declara queda como «Sin datos»,
 * nunca rellenado.
 */

/** «1 sesión» / «N sesiones»: concordancia es-ES del conteo de entrenamiento. */
export function trainingSessionsText(count: number, locale: Locale = 'es'): string {
  const n = formatNumber(count, { maximumFractionDigits: 0 }, undefined, locale);
  if (locale === 'en') return `${n} ${count === 1 ? 'session' : 'sessions'}`;
  return `${n} ${count === 1 ? 'sesión' : 'sesiones'}`;
}

const METRICAS: { key: keyof MarketRegime['metrics']; label: string; en: string }[] = [
  { key: 'treasury_10y_us', label: 'Bono EE. UU. 10 años', en: 'US 10-year Treasury' },
  { key: 'treasury_2y_us', label: 'Bono EE. UU. 2 años', en: 'US 2-year Treasury' },
  { key: 'yield_curve_10y_2y_us', label: 'Curva 10 años − 2 años', en: '10-year − 2-year curve' },
  { key: 'breakeven_10y_us', label: 'Inflación implícita 10 años', en: '10-year breakeven inflation' },
  { key: 'high_yield_spread_us', label: 'Diferencial high yield', en: 'High-yield spread' },
  { key: 'vix_us', label: 'VIX', en: 'VIX' },
  { key: 'mortgage_30y_us', label: 'Hipoteca 30 años EE. UU.', en: 'US 30-year mortgage' },
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
const MOTIVO_CONCENTRACION_SIN_DATOS: Record<string, string> = {
  no_snapshot_in_disk: 'El factsheet del S&P 500 aún no está cargado; aparecerá en la próxima sincronización.',
  snapshot_dir_not_configured: 'El factsheet del S&P 500 no está disponible en este momento.',
  snapshot_integrity_failed: 'El factsheet del S&P 500 no pasó la verificación de integridad; sin datos hasta la próxima sincronización.',
  snapshot_vintage_after_requested_date: 'El factsheet disponible es posterior a la fecha consultada; no describe el índice en esa fecha.',
  requested_date_invalid: 'Sin fecha de consulta válida no se puede leer el factsheet del S&P 500.',
  snapshot_too_stale_for_requested_date: 'El último factsheet del S&P 500 es demasiado antiguo para la fecha de hoy; sin datos hasta que se actualice.',
  index_weights_not_published_by_source: 'El factsheet no publica el peso de los mayores constituyentes.',
};

// Mismos motivos en inglés (Ajustes → Idioma); las claves son las del backend.
const MOTIVO_CONCENTRACION_SIN_DATOS_EN: Record<string, string> = {
  no_snapshot_in_disk: 'The S&P 500 factsheet is not loaded yet; it will appear at the next sync.',
  snapshot_dir_not_configured: 'The S&P 500 factsheet is not available right now.',
  snapshot_integrity_failed: 'The S&P 500 factsheet failed its integrity check; no data until the next sync.',
  snapshot_vintage_after_requested_date: 'The available factsheet is later than the requested date; it does not describe the index on that date.',
  requested_date_invalid: 'Without a valid requested date the S&P 500 factsheet cannot be read.',
  snapshot_too_stale_for_requested_date: 'The latest S&P 500 factsheet is too old for today; no data until it is updated.',
  index_weights_not_published_by_source: 'The factsheet does not publish the weight of the largest constituents.',
};

/**
 * Motivos y métodos que el motor declara en español (bloque HMM, beta de
 * cartera, curva 10a−2a). Con el inglés elegido se muestran traducidos; un
 * texto que no está en la lista se muestra tal cual.
 */
const TEXTO_REGIMEN_EN: Record<string, string> = {
  'sesiones discontinuas': 'non-consecutive sessions',
  'varianza de benchmark nula': 'zero benchmark variance',
  'universo de constituyentes incompleto': 'incomplete constituent universe',
  'capitalizaciones positivas y fechadas incompletas': 'incomplete positive, dated market caps',
  'historial insuficiente': 'not enough history',
  'valores inválidos': 'invalid values',
  'serie constante': 'constant series',
  'ajuste no convergente': 'the fit did not converge',
  'probabilidad inválida': 'invalid probability',
  'modelo no disponible': 'model not available',
  'observaciones recientes ausentes': 'no recent observations',
  'sin posiciones o benchmark S&P 500': 'no positions or S&P 500 benchmark',
  'benchmark S&P 500 sin cierres ajustados': 'S&P 500 benchmark without adjusted closes',
  'La beta de tu cartera aún no está disponible.': 'Your portfolio beta is not available yet.',
  'La beta de tu cartera aún no está disponible; el snapshot macro es global y no mezcla carteras.':
    'Your portfolio beta is not available yet; the macro snapshot is global and does not mix portfolios.',
  'HMM gaussiano de 2 estados; filtro hacia adelante; estados sin etiqueta económica':
    '2-state Gaussian HMM; forward filter; states with no economic label',
  'DGS10 menos DGS2 en la misma fecha': 'DGS10 minus DGS2 on the same date',
  'cov(retorno activo, retorno S&P 500) / var(retorno S&P 500); cierres ajustados pareados':
    'cov(active return, S&P 500 return) / var(S&P 500 return); paired adjusted closes',
};

export function textoRegimen(text: string, locale: Locale = 'es'): string {
  return locale === 'en' ? (TEXTO_REGIMEN_EN[text] ?? text) : text;
}

function motivoConcentracionSinDatos(top?: RegimeTopTen, locale: Locale = 'es') {
  if (!top?.reason && !top?.detail) return null;
  const motivo = locale === 'en'
    ? ((top.reason && MOTIVO_CONCENTRACION_SIN_DATOS_EN[top.reason]) ?? 'The S&P 500 factsheet is not available right now.')
    : ((top.reason && MOTIVO_CONCENTRACION_SIN_DATOS[top.reason])
    ?? 'El factsheet del S&P 500 no está disponible en este momento.');
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
    throw error ?? new Error('Sin respuesta de régimen de mercado');
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
            {METRICAS.map(({ key, label, en: labelEn }) => (
              <TarjetaMetrica
                key={key}
                label={fmt.locale === 'en' ? labelEn : label}
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
          {regimen.note ? <p className="text-xs text-gray-500">{regimen.note}</p> : null}
        </>
      )}
    </div>
  );
}

