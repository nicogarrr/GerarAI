/**
 * Calendario de catalizadores: el backend (catalyst_calendar_service.py) manda
 * en castellano el detalle de cada evento y el nombre de las acciones
 * corporativas. En inglés se reescriben por trozos conocidos; si algún trozo no
 * se reconoce, el texto entero pasa tal cual (nunca medio traducido). En
 * castellano pasa siempre tal cual.
 */
import type { CatalystEvent } from '@/lib/actions/catalysts.actions';
import type { Locale } from '@/lib/i18n/locale';

const MONTHS_ES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sept', 'oct', 'nov', 'dic'];
const MONTHS_EN = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

const ACTIONS_EN: Record<string, string> = {
  Split: 'Split',
  Contrasplit: 'Reverse split',
  'Cambio de ticker': 'Ticker change',
  Fusion: 'Merger',
  Escision: 'Spin-off',
  'Acción corporativa': 'Corporate action',
};

const FIXED_EN: Record<string, string> = {
  'antes de la apertura': 'before the open',
  'tras el cierre': 'after the close',
  'hora por confirmar': 'time to be confirmed',
  'emisor de 52/53 semanas: fecha aproximada (hasta ~1 semana)': '52/53-week issuer: approximate date (up to ~1 week)',
  'categoría de filer no disponible: se usa el plazo máximo de la regla': "filer category not available: the rule's maximum deadline is used",
};

const FILER_EN: Record<string, string> = {
  'emisor acelerado grande': 'large accelerated filer',
  'emisor acelerado': 'accelerated filer',
  'emisor no acelerado': 'non-accelerated filer',
  'empresa de información reducida': 'smaller reporting company',
};

const num = (value: string) => value.replace(',', '.');

function dateEn(text: string): string | null {
  const match = /^(\d{1,2}) (\S+) (\d{4})$/.exec(text);
  const month = match ? MONTHS_ES.indexOf(match[2]) : -1;
  return match && month >= 0 ? `${MONTHS_EN[month]} ${match[1]}, ${match[3]}` : null;
}

function partEn(part: string): string | null {
  if (Object.hasOwn(FIXED_EN, part)) return FIXED_EN[part];
  let match = /^BPA estimado (-?\d+,\d+)$/.exec(part);
  if (match) return `estimated EPS ${num(match[1])}`;
  match = /^(-?\d+,\d+)((?: [A-Za-z]{3})?) por acción$/.exec(part);
  if (match) return `${num(match[1])}${match[2]} per share`;
  match = /^pago el (\d{1,2})\/(\d{1,2})\/(\d{4})$/.exec(part);
  if (match) return `paid on ${MONTHS_EN[Number(match[2]) - 1] ?? match[2]} ${match[1]}, ${match[3]}`;
  match = /^ratio (\d+(?:,\d+)?)$/.exec(part);
  if (match) return `ratio ${num(match[1])}`;
  match = /^categoría EDGAR: (.+)$/.exec(part);
  if (match) return `EDGAR category: ${Object.hasOwn(FILER_EN, match[1]) ? FILER_EN[match[1]] : match[1]}`;
  match = /^(\d+) días tras el cierre de periodo estimado \((.+)\) sobre el último informe periódico \(cierre (.+)\)$/.exec(part);
  if (match) {
    const estimated = dateEn(match[2]);
    const last = dateEn(match[3]);
    return estimated && last ? `${match[1]} days after the estimated period end (${estimated}) based on the latest periodic report (period end ${last})` : null;
  }
  return null;
}

function translateJoined(detail: string, separator: string): string | null {
  const parts = detail.split(separator).map(partEn);
  return parts.every((part) => part !== null) ? parts.join(separator) : null;
}

export function catalystDetailText(event: Pick<CatalystEvent, 'type' | 'detail'>, locale: Locale): string | null | undefined {
  const detail = event.detail;
  if (locale !== 'en' || !detail) return detail;
  const separator = event.type === 'filing_deadline' ? '; ' : event.type === 'earnings' ? ', ' : ' · ';
  return translateJoined(detail, separator) ?? detail;
}

export function catalystActionTitle(title: string, locale: Locale): string {
  if (locale !== 'en') return title;
  return Object.hasOwn(ACTIONS_EN, title) ? ACTIONS_EN[title] : title;
}
