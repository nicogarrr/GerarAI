import { metricLabel } from '@/lib/research/metric-labels';

/**
 * Motivo de un N/D con las claves internas que lo acompañan vueltas legibles.
 *
 * El backend (fair_value_service._insufficient_reason) termina el motivo con
 * «faltan net_debt, fx_rate:TWD/USD.» / «missing …». Esas claves son nombres
 * de columna, no castellano: cada una pasa por metricLabel («deuda neta»,
 * «tipo de cambio TWD/USD») y el verbo concuerda con el número («falta» /
 * «faltan»). Un motivo sin esa cola, o con palabras que no son claves, pasa tal
 * cual: nunca se inventa ni se quita información.
 */
const KEY = /^[a-z][a-z0-9_]*(?::[A-Za-z]{3}\/[A-Za-z]{3})?$/;

export function readableMissingReason(text: string | null | undefined, locale: 'es' | 'en' = 'es'): string {
  if (!text) return '';
  const m = /(^|[\s:(])(faltan|missing) ([^.]+)\.?$/.exec(text);
  if (!m) return text;
  const items = m[3].split(/,\s*/).map((s) => s.trim()).filter(Boolean);
  if (!items.length || !items.every((s) => KEY.test(s))) return text;
  // «Deuda neta» → «deuda neta» en mitad de la frase; siglas («EBITDA», «FCF») intactas.
  const labels = items.map((s) => metricLabel(s, locale)).map((l) => (/^[A-ZÁÉÍÓÚ][a-záéíóúñ]/.test(l) ? l[0].toLowerCase() + l.slice(1) : l));
  const verb = m[2] === 'missing' ? 'missing' : labels.length === 1 ? 'falta' : 'faltan';
  const joiner = locale === 'en' || m[2] === 'missing' ? ' and ' : ' y ';
  const list = labels.length > 1 ? `${labels.slice(0, -1).join(', ')}${joiner}${labels.at(-1)}` : labels[0];
  return `${text.slice(0, m.index)}${m[1]}${verb} ${list}.`;
}
