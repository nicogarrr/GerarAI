// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { naFor } from '../format.ts';

const INTL: Record<'es' | 'en', string> = { es: 'es-ES', en: 'en-US' };

/** Only structured amounts are formatted here. Never rewrite a quoted source. */
export function thesisMoney(value: number, currency: string, locale: 'es' | 'en' = 'es'): string {
  return new Intl.NumberFormat(INTL[locale], {
    style: 'currency', currency, useGrouping: 'always', minimumFractionDigits: 2, maximumFractionDigits: 2,
  }).format(value);
}

/** The catalyst payload has no currency or share basis, so no symbol is inferred. */
export function thesisEps(value: number | null | undefined, locale: 'es' | 'en' = 'es'): string {
  return value == null || !Number.isFinite(value) ? naFor(locale) : new Intl.NumberFormat(INTL[locale], {
    useGrouping: 'always',
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  }).format(value);
}
