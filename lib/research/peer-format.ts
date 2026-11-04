// F26: formato honesto de comparables. Un valor ausente es "Sin datos", nunca 0.
// Con la app en inglés (Ajustes → Idioma) cifras y textos salen en inglés:
// «12.3%», «1.50x», «No data»; el castellano queda igual («12,3 %», «1,50x»).
import type { Locale } from '../i18n/locale.ts';

const MULTIPLE_METRICS = new Set(['net_debt_to_ebitda']);

const noData = (locale: Locale) => (locale === 'en' ? 'No data' : 'Sin datos');

export function formatPeerValue(value: string | null | undefined, metric: string, locale: Locale = 'es'): string {
  if (value === null || value === undefined || value === '') return noData(locale);
  const number = Number(value);
  if (!Number.isFinite(number)) return noData(locale);
  const tag = locale === 'en' ? 'en-US' : 'es-ES';
  if (MULTIPLE_METRICS.has(metric)) {
    return `${number.toLocaleString(tag, { maximumFractionDigits: 2, minimumFractionDigits: 2 })}x`;
  }
  const percent = (number * 100).toLocaleString(tag, { maximumFractionDigits: 1, minimumFractionDigits: 1 });
  return locale === 'en' ? `${percent}%` : `${percent} %`;
}

/**
 * La nota del backend («muestra insuficiente (n<3)») es texto en castellano;
 * en inglés se dice lo mismo a partir de la bandera insufficient_sample,
 * conservando el umbral si la nota lo trae.
 */
function insufficientSampleEn(note: string | null | undefined): string {
  const threshold = /n\s*<\s*(\d+)/.exec(note ?? '');
  return threshold ? `insufficient sample (n<${threshold[1]})` : 'insufficient sample';
}

export function peerMedianText(
  benchmark: { peer_median: string | null; note?: string | null; insufficient_sample?: boolean },
  metric: string,
  locale: Locale = 'es',
): string {
  if (benchmark.peer_median === null || benchmark.insufficient_sample) {
    if (locale === 'en') return benchmark.insufficient_sample || benchmark.note ? insufficientSampleEn(benchmark.note) : noData(locale);
    return benchmark.note ?? noData(locale);
  }
  return formatPeerValue(benchmark.peer_median, metric, locale);
}
