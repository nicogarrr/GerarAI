// Sin imports de alias (@/): el guard lo carga con node --experimental-strip-types.
const NA = 'N/D';

function validCurrency(currency: string | null | undefined): currency is string {
    if (!currency || !/^[A-Z]{3}$/.test(currency)) return false;
    try {
        new Intl.NumberFormat('es-ES', { style: 'currency', currency });
        return true;
    } catch {
        return false;
    }
}

/** Tira de tickers relacionados de una noticia (backend: news_related_tickers). */
export type RelatedTicker = {
    ticker: string;
    name?: string | null;
    currency?: string | null;
    primary?: boolean;
    /** 'etf': ETF tematico que tiene el ticker principal (holdings oficiales del emisor). */
    kind?: 'stock' | 'etf';
    weight_pct?: number | null;
    holdings_as_of?: string | null;
    source_url?: string | null;
    price: number | null;
    /** Fecha del cierre oficial usado (ISO). */
    date: string | null;
    /** Variacion del dia en %; null si no hay dos cierres consecutivos. */
    change_pct: number | null;
};

export type RelatedTickerView = {
    ticker: string;
    href: string;
    priceText: string;
    changeText: string;
    /** Fecha corta (dd/mm) del cierre cuando no es comparable con el anterior; '' si hay variacion. */
    dateText: string;
    tone: 'up' | 'down' | 'flat' | 'none';
    title: string;
    isEtf: boolean;
};

/**
 * Texto de una celda de la tira. Honestidad: sin precio, N/D; sin dos
 * cierres consecutivos, variacion N/D (nunca 0 %). El precio es SIEMPRE un
 * cierre datado, nunca una cotizacion en vivo. Divisa no ISO (GBX, ZAC):
 * se muestra el numero con su divisa tal cual, sin convertir ni sustituir.
 */
export function relatedTickerView(item: RelatedTicker): RelatedTickerView {
    if (item.kind === 'etf') {
        const w = typeof item.weight_pct === 'number' && Number.isFinite(item.weight_pct)
            ? new Intl.NumberFormat('es-ES', { minimumFractionDigits: 1, maximumFractionDigits: 2 }).format(item.weight_pct)
            : null;
        return {
            ticker: item.ticker,
            href: '',
            priceText: w ? `${w} % del ETF` : NA,
            changeText: '',
            dateText: '',
            tone: 'none',
            isEtf: true,
            title: `ETF ${item.name ?? item.ticker} · peso del ticker segun holdings oficiales${item.holdings_as_of ? ` al ${item.holdings_as_of}` : ''}`,
        };
    }
    const hasPrice = typeof item.price === 'number' && Number.isFinite(item.price);
    let priceText = NA;
    if (hasPrice) {
        const value = item.price as number;
        priceText = validCurrency(item.currency)
            ? new Intl.NumberFormat('es-ES', { style: 'currency', currency: item.currency, useGrouping: 'always', minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value)
            : `${new Intl.NumberFormat('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value)}${item.currency ? ` ${item.currency}` : ''}`;
    }
    const hasChange = typeof item.change_pct === 'number' && Number.isFinite(item.change_pct);
    const changeText = hasChange
        ? new Intl.NumberFormat('es-ES', { style: 'percent', minimumFractionDigits: 2, maximumFractionDigits: 2, signDisplay: 'exceptZero' }).format((item.change_pct as number) / 100)
        : NA;
    const tone = !hasChange ? 'none' : item.change_pct! > 0 ? 'up' : item.change_pct! < 0 ? 'down' : 'flat';
    const m = item.date ? /^\d{4}-(\d{2})-(\d{2})/.exec(item.date) : null;
    const dateText = !hasChange && hasPrice && m ? `${m[2]}/${m[1]}` : '';
    const day = item.date ? `cierre ${item.date}` : 'sin cierre disponible';
    return {
        ticker: item.ticker,
        href: `/research/${encodeURIComponent(item.ticker)}`,
        priceText,
        changeText,
        dateText,
        isEtf: false,
        tone,
        title: `${item.name ?? item.ticker} · ${day}`,
    };
}
