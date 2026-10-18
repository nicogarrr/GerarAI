import type { components } from '@/lib/research/openapi.generated';
export type ExtendedQuote = components['schemas']['ExtendedQuote'];

const clock = (timestamp: number) => new Intl.DateTimeFormat('es-ES', {
    timeZone: 'Europe/Madrid', hour: '2-digit', minute: '2-digit', hour12: false,
}).format(new Date(timestamp * 1000));
const datedClock = (timestamp: number) => new Intl.DateTimeFormat('es-ES', {
    timeZone: 'Europe/Madrid', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false,
    timeZoneName: 'short',
}).format(new Date(timestamp * 1000));

export function extendedQuoteLabel(quote: ExtendedQuote | null): string {
    if (!quote?.source || !quote.timestamp || quote.price == null || quote.status === 'unavailable') return 'N/D';
    const time = datedClock(quote.timestamp);
    const priceSession = quote.price_session;
    if (!priceSession || priceSession === 'cerrado') return 'N/D';
    const sameSession = quote.session === priceSession;
    const sessionLabel = priceSession === 'pre' ? 'Premercado'
        : priceSession === 'post' ? 'Post-cierre' : 'Mercado abierto';
    let label: string;
    if (sameSession) {
        label = `${sessionLabel} · ${time}`;
    } else {
        const datedLabel = priceSession === 'post' ? 'Último post-cierre'
            : priceSession === 'pre' ? 'Último premercado'
            : quote.regular_close_timestamp === quote.timestamp ? 'Cierre' : 'Último precio regular';
        label = `${datedLabel} · ${time}`;
    }
    return quote.status === 'retrasado' ? `${label} · Retrasado` : label;
}

export function quoteTime(timestamp: number | null | undefined): string {
    return timestamp ? clock(timestamp) : 'N/D';
}

export function quoteDate(timestamp: number | null | undefined): string {
    return timestamp ? new Intl.DateTimeFormat('es-ES', {
        timeZone: 'Europe/Madrid', day: 'numeric', month: 'short',
    }).format(new Date(timestamp * 1000)) : 'N/D';
}

/** Session date only: never claim the daily bar's opening time is its close. */
export function quoteSessionDate(value: string | null | undefined): string {
    if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return 'N/D';
    return new Intl.DateTimeFormat('es-ES', { timeZone: 'UTC', day: 'numeric', month: 'short', year: 'numeric' }).format(new Date(`${value}T12:00:00Z`));
}
