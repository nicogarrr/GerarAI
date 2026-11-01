import type { components } from '@/lib/research/openapi.generated';
// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { naFor } from '../format.ts';
export type ExtendedQuote = components['schemas']['ExtendedQuote'];

/** Idioma de las etiquetas: «es» (por defecto) o «en» (Ajustes → Idioma). */
export type QuoteLocale = 'es' | 'en';
const tag = (locale: QuoteLocale) => (locale === 'en' ? 'en-GB' : 'es-ES');
const na = (locale: QuoteLocale) => naFor(locale);

const clock = (timestamp: number, locale: QuoteLocale = 'es') => new Intl.DateTimeFormat(tag(locale), {
    timeZone: 'Europe/Madrid', hour: '2-digit', minute: '2-digit', hour12: false,
}).format(new Date(timestamp * 1000));
const datedClock = (timestamp: number, locale: QuoteLocale = 'es') => new Intl.DateTimeFormat(tag(locale), {
    timeZone: 'Europe/Madrid', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false,
    timeZoneName: 'short',
}).format(new Date(timestamp * 1000));

const LABELS = {
    es: { pre: 'Premercado', post: 'Post-cierre', open: 'Mercado abierto', lastPost: 'Último post-cierre', lastPre: 'Último premercado', close: 'Cierre', lastRegular: 'Último precio regular', delayed: 'Retrasado' },
    en: { pre: 'Pre-market', post: 'After hours', open: 'Market open', lastPost: 'Last after-hours', lastPre: 'Last pre-market', close: 'Closing price', lastRegular: 'Last regular price', delayed: 'Delayed' },
} as const;

export function extendedQuoteLabel(quote: ExtendedQuote | null, locale: QuoteLocale = 'es'): string {
    if (!quote?.source || !quote.timestamp || quote.price == null || quote.status === 'unavailable') return na(locale);
    const time = datedClock(quote.timestamp, locale);
    const priceSession = quote.price_session;
    if (!priceSession || priceSession === 'cerrado') return na(locale);
    const l = LABELS[locale];
    const sameSession = quote.session === priceSession;
    const sessionLabel = priceSession === 'pre' ? l.pre
        : priceSession === 'post' ? l.post : l.open;
    let label: string;
    if (sameSession) {
        label = `${sessionLabel} · ${time}`;
    } else {
        const datedLabel = priceSession === 'post' ? l.lastPost
            : priceSession === 'pre' ? l.lastPre
            : quote.regular_close_timestamp === quote.timestamp ? l.close : l.lastRegular;
        label = `${datedLabel} · ${time}`;
    }
    return quote.status === 'retrasado' ? `${label} · ${l.delayed}` : label;
}

export function quoteTime(timestamp: number | null | undefined, locale: QuoteLocale = 'es'): string {
    return timestamp ? clock(timestamp, locale) : na(locale);
}

export function quoteDate(timestamp: number | null | undefined, locale: QuoteLocale = 'es'): string {
    return timestamp ? new Intl.DateTimeFormat(tag(locale), {
        timeZone: 'Europe/Madrid', day: 'numeric', month: 'short',
    }).format(new Date(timestamp * 1000)) : na(locale);
}

/** Session date only: never claim the daily bar's opening time is its close. */
export function quoteSessionDate(value: string | null | undefined, locale: QuoteLocale = 'es'): string {
    if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return na(locale);
    return new Intl.DateTimeFormat(tag(locale), { timeZone: 'UTC', day: 'numeric', month: 'short', year: 'numeric' }).format(new Date(`${value}T12:00:00Z`));
}
