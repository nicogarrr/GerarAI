/**
 * Diario de decisiones enlazado a operaciones reales (IBKR o manuales).
 *
 * Funciones puras (sin Next) para describir la operación y el valor justo de
 * ese día en es-ES. Mismo contrato que data-engine/app/services/journal_trade_link.py.
 */

// @ts-expect-error TS5097: node --test (--experimental-strip-types) necesita la extensión.
import { t as esT, type TranslationKey, type TranslationVars } from '../i18n/t.ts';

/** Traductor del idioma elegido; por defecto el español de referencia. */
type TiFn = (key: TranslationKey, vars?: TranslationVars) => string;
// @ts-expect-error TS5097: idem
import { intlLocale, type Locale } from '../i18n/locale.ts';

export type JournalTrade = {
  id: number;
  trade_date: string;
  action: string;
  action_label?: string;
  quantity: number | null;
  price: number | null;
  fees?: number | null;
  currency: string | null;
  source?: string;
  linked_entry_ids?: number[];
};

export type JournalFairValue = {
  value: number;
  source: 'tesis' | 'motor';
  version: number | null;
  as_of: string | null;
  stale: boolean;
  label: string;
  margin_vs_trade_price: number | null;
  note: string | null;
};

const ACTION_KEYS: Record<string, TranslationKey> = { buy: 'research.journal.buy', sell: 'research.journal.sell' };

function number(value: number, digits = 2, locale: Locale = 'es'): string {
  return new Intl.NumberFormat(intlLocale(locale), { minimumFractionDigits: 0, maximumFractionDigits: digits }).format(value);
}

function money(value: number, locale: Locale = 'es'): string {
  return new Intl.NumberFormat(intlLocale(locale), { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);
}

/** «12/03/2026» a partir de «2026-03-12» (día de calendario, sin zona). */
export function dayEs(isoDay: string | null | undefined, locale: Locale = 'es'): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(isoDay ?? '');
  if (!match) return locale === 'en' ? 'n/a' : 's/d';
  // Inglés: formato ISO (sin ambigüedad día/mes); español: dd/mm/aaaa.
  return locale === 'en' ? `${match[1]}-${match[2]}-${match[3]}` : `${match[3]}/${match[2]}/${match[1]}`;
}

/** «Compra 10 @ 70,50 USD · 12/03/2026». */
export function describeTrade(trade: JournalTrade, ti: TiFn = esT, locale: Locale = 'es'): string {
  // action_label llega del backend en español: en inglés manda la acción traducida.
  const key = ACTION_KEYS[trade.action];
  const label = (locale === 'es' ? trade.action_label : undefined) ?? (key ? ti(key) : undefined) ?? trade.action_label ?? trade.action;
  const qty = trade.quantity != null ? ` ${number(trade.quantity, 4, locale)}` : '';
  const price = trade.price != null ? ` @ ${money(trade.price, locale)}${trade.currency ? ` ${trade.currency}` : ''}` : '';
  return `${label}${qty}${price} · ${dayEs(trade.trade_date, locale)}`;
}

/** «Valor justo ese día: 90,00 (Tesis publicada v1, 10/01/2026) · margen +25,0 %». */
export function describeFairValue(reading: JournalFairValue | null | undefined, ti: TiFn = esT, locale: Locale = 'es'): string {
  if (!reading) return ti('research.journal.fairNone');
  const origin = reading.as_of ? `${reading.label}, ${dayEs(reading.as_of, locale)}` : reading.label;
  let text = ti('research.journal.fairValue', { value: money(reading.value, locale), origin });
  if (reading.margin_vs_trade_price != null) {
    const pct = new Intl.NumberFormat(intlLocale(locale), {
      style: 'percent',
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
      signDisplay: 'exceptZero',
    }).format(reading.margin_vs_trade_price);
    text += ti('research.journal.fairMargin', { pct: pct.replace(/\u00a0/g, ' ') });
  } else if (reading.note) {
    text += ` · ${reading.note}`;
  }
  return text;
}
