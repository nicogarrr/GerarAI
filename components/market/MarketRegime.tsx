import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import BackendOffline from '@/components/system/BackendOffline';
import type { MarketRegime, RegimeComputedMetric, RegimeObservedMetric, RegimeStatusBlock, RegimeTopTen } from '@/lib/actions/market-regime.actions';
import { getMarketRegimeResult } from '@/lib/actions/market-regime.actions';
import { isBackendUnavailableError } from '@/lib/backend-offline';
import { formatMarketDate, formatNumber, formatPercent, formatUserDateTime } from '@/lib/format';
import { ExternalLink } from 'lucide-react';

/**
 * Vista «Régimen» de la seccion Mercado: pinta el ultimo snapshot de
 * /api/market/regime exactamente como viene declarado. Cada bloque muestra su
 * fecha y su fuente; lo que el snapshot no declara queda como «Sin datos»,
 * nunca rellenado.
 */

/** «1 sesión» / «N sesiones»: concordancia es-ES del conteo de entrenamiento. */
export function trainingSessionsText(count: number): string {
  return `${formatNumber(count, { maximumFractionDigits: 0 })} ${count === 1 ? 'sesión' : 'sesiones'}`;
}

const METRICAS: { key: keyof MarketRegime['metrics']; label: string }[] = [
  { key: 'treasury_10y_us', label: 'Bono EE. UU. 10 años' },
  { key: 'treasury_2y_us', label: 'Bono EE. UU. 2 años' },
  { key: 'yield_curve_10y_2y_us', label: 'Curva 10 años − 2 años' },
  { key: 'breakeven_10y_us', label: 'Inflación implícita 10 años' },
  { key: 'high_yield_spread_us', label: 'Diferencial high yield' },
  { key: 'vix_us', label: 'VIX' },
  { key: 'mortgage_30y_us', label: 'Hipoteca 30 años EE. UU.' },
];

/** Valor con la unidad declarada; unidades desconocidas se muestran tal cual. */
function valorMetrica(m: { value: number; unit: string }): string {
  const n = formatNumber(m.value, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (m.unit === 'porcentaje') return `${n} %`;
  if (m.unit === 'puntos porcentuales') return `${n} pp`;
  if (m.unit === 'índice') return n;
  return `${n} ${m.unit}`;
}

function Fuente({ source, url }: { source?: string; url?: string | null }) {
  if (!source) return null;
  return url ? (
    <a
      className="inline-flex items-center gap-1 text-xs text-teal-300 hover:text-teal-200 hover:underline"
      href={url}
      rel="noopener noreferrer"
      target="_blank"
    >
      {source}
      <ExternalLink aria-hidden="true" className="h-3 w-3" />
    </a>
  ) : (
    <span className="text-xs text-gray-500">{source}</span>
  );
}

function TarjetaMetrica({ label, metrica }: { label: string; metrica?: RegimeObservedMetric | RegimeComputedMetric }) {
  return (
    <Card className="min-w-0 border-gray-800">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium break-words text-gray-400">{label}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-1">
        {metrica ? (
          <>
            <p className="text-xl font-semibold text-gray-100">{valorMetrica(metrica)}</p>
            <p className="text-xs text-gray-500">Dato del {formatMarketDate(metrica.date)}</p>
            {'method' in metrica && metrica.method ? (
              <p className="text-xs text-gray-500">{metrica.method}</p>
            ) : null}
            {'source' in metrica ? <Fuente source={metrica.source} url={metrica.source_url} /> : null}
          </>
        ) : (
          <p className="text-sm text-gray-500">Sin datos</p>
        )}
      </CardContent>
    </Card>
  );
}

function TarjetaHmm({ regimen }: { regimen: MarketRegime }) {
  const hmm = regimen.metrics.hmm;
  const estados = Object.entries(regimen.probabilities ?? {});
  return (
    <Card className="min-w-0 border-gray-800">
      <CardHeader className="pb-2">
        <CardTitle className="text-base break-words">Modelo de estados (HMM)</CardTitle>
      </CardHeader>
      <CardContent className="space-y-1">
        {hmm?.status === 'disponible' && estados.length > 0 ? (
          <>
            <ul className="space-y-1">
              {estados.map(([estado, prob]) => (
                <li key={estado} className="flex items-baseline justify-between gap-2">
                  <span className="text-sm text-gray-400">{estado.replace('state_', 'Estado ')}</span>
                  <span className="text-lg font-semibold text-gray-100">{formatPercent(prob)}</span>
                </li>
              ))}
            </ul>
            {hmm.date ? <p className="text-xs text-gray-500">Filtro al {formatMarketDate(hmm.date)}</p> : null}
            {hmm.trained_through ? (
              <p className="text-xs text-gray-500">
                Entrenado hasta el {formatMarketDate(hmm.trained_through)}
                {typeof hmm.training_sessions === 'number' ? ` · ${trainingSessionsText(hmm.training_sessions)}` : ''}
              </p>
            ) : null}
            {hmm.method ? <p className="text-xs text-gray-500">{hmm.method}</p> : null}
          </>
        ) : (
          <>
            <p className="text-sm text-gray-500">Sin datos</p>
            {hmm?.reason ? <p className="text-xs text-gray-500">{hmm.reason}</p> : null}
          </>
        )}
      </CardContent>
    </Card>
  );
}

function TarjetaConcentracion({ top }: { top?: RegimeTopTen }) {
  const disponible = top?.status === 'disponible' && typeof top.weight_top_ten_pct === 'number';
  return (
    <Card className="min-w-0 border-gray-800">
      <CardHeader className="pb-2">
        <CardTitle className="text-base break-words">
          Concentración top 10{top?.index ? ` · ${top.index}` : ''}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-1">
        {disponible ? (
          <>
            <p className="text-xl font-semibold text-gray-100">
              {formatPercent(top.weight_top_ten_pct as number, { fromRatio: false })}
            </p>
            {typeof top.weight_largest_pct === 'number' ? (
              <p className="text-xs text-gray-500">
                Mayor peso: {formatPercent(top.weight_largest_pct, { fromRatio: false })}
              </p>
            ) : null}
            {top.snapshot_as_of ? (
              <p className="text-xs text-gray-500">Snapshot del {formatMarketDate(top.snapshot_as_of)}</p>
            ) : null}
            <Fuente source={top.source} url={top.source_url} />
          </>
        ) : (
          <>
            <p className="text-sm text-gray-500">Sin datos</p>
            {motivoConcentracionSinDatos(top)}
            {top?.snapshot_as_of ? (
              <p className="text-xs text-gray-500">Snapshot consultado: {formatMarketDate(top.snapshot_as_of)}</p>
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

function motivoConcentracionSinDatos(top?: RegimeTopTen) {
  if (!top?.reason && !top?.detail) return null;
  const motivo = (top.reason && MOTIVO_CONCENTRACION_SIN_DATOS[top.reason])
    ?? 'El factsheet del S&P 500 no está disponible en este momento.';
  return <p className="text-xs text-gray-500">{motivo}</p>;
}

function TarjetaBeta({ beta }: { beta?: RegimeStatusBlock }) {
  return (
    <Card className="min-w-0 border-gray-800">
      <CardHeader className="pb-2">
        <CardTitle className="text-base break-words">Beta de cartera</CardTitle>
      </CardHeader>
      <CardContent className="space-y-1">
        <p className="text-sm text-gray-500">{beta?.status === 'no_disponible' ? 'No disponible' : 'Sin datos'}</p>
        {beta?.reason ? <p className="text-xs text-gray-500">{beta.reason}</p> : null}
      </CardContent>
    </Card>
  );
}

const ESTADO_BADGE: Record<string, { label: string; variant: 'default' | 'secondary' | 'outline' }> = {
  disponible: { label: 'Disponible', variant: 'default' },
  obsoleto: { label: 'Obsoleto', variant: 'secondary' },
  'sin datos': { label: 'Sin datos', variant: 'outline' },
};

export async function MarketRegimeVista() {
  const { data: regimen, error } = await getMarketRegimeResult();
  if (error || !regimen) {
    if (error && isBackendUnavailableError(error)) {
      return <BackendOffline as="section" feature="Mercado" retryHref="/screener?vista=regimen" />;
    }
    throw error ?? new Error('Sin respuesta de régimen de mercado');
  }
  const estado = ESTADO_BADGE[regimen.status] ?? { label: regimen.status, variant: 'outline' as const };
  const sinSnapshot = !regimen.date;
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={estado.variant}>{estado.label}</Badge>
        {regimen.date ? (
          <p className="text-sm text-gray-400">
            Snapshot del {formatMarketDate(regimen.date)}
            {regimen.generated_at
              ? ` · generado ${formatUserDateTime(regimen.generated_at, { hour: '2-digit', minute: '2-digit', timeZoneName: 'short' })}`
              : ''}
          </p>
        ) : null}
      </div>

      {sinSnapshot ? (
        <p className="text-sm text-gray-500">Sin datos todavía — en cuanto exista un snapshot de régimen aparecerá aquí.</p>
      ) : (
        <>
          <div className="grid min-w-0 grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-3">
            {METRICAS.map(({ key, label }) => (
              <TarjetaMetrica
                key={key}
                label={label}
                metrica={regimen.metrics[key] as RegimeObservedMetric | RegimeComputedMetric | undefined}
              />
            ))}
          </div>
          <div className="grid min-w-0 grid-cols-1 gap-3 sm:gap-4 lg:grid-cols-3">
            <TarjetaHmm regimen={regimen} />
            <TarjetaConcentracion top={regimen.metrics.top_ten_sp500} />
            <TarjetaBeta beta={regimen.portfolio_beta ?? regimen.metrics.portfolio_beta} />
          </div>
          {regimen.note ? <p className="text-xs text-gray-500">{regimen.note}</p> : null}
        </>
      )}
    </div>
  );
}

