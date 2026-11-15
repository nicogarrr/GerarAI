/**
 * Verificación de COBERTURA y RETRASO del catálogo del panel /mercados.
 *
 * El catálogo de lib/market/live-quotes.ts solo admite símbolos verificados
 * contra la chart API de Yahoo; este módulo convierte la respuesta cruda de
 * cada símbolo en una fila de informe que responde, con datos del propio
 * proveedor:
 *  - ¿cubre Yahoo este símbolo AHORA? (status: precio utilizable o motivo);
 *  - ¿qué retraso tiene? (ageSeconds = ahora - timestamp del proveedor; en
 *    fin de semana es la edad del cierre del viernes, honesta, no un fallo);
 *  - ¿tendría el cambio referencia demostrable o saldría N/D?
 *    (changeComputable: barras diarias suficientes para el cierre previo);
 *  - identidad informada: mercado (exchangeName) y tipo (instrumentType).
 *
 * Lo usa scripts/verify-live-markets.mjs (red real, fuera de CI) y lo prueban
 * tests/unit/market/live-markets-verify.test.ts con fixtures, sin red.
 *
 * Modulo PURO: sin imports de servidor, para probarlo con node --test/vitest.
 */

// node --test / node --experimental-strip-types exige la extension .ts en
// runtime y tsc la prohibe (TS5097): misma convencion que los guards de
// scripts/, con el supresor pegado a la linea del path. Vitest y el bundler
// de Next resuelven ambas formas.
// @ts-expect-error -- TS5097: extension .ts exigida por node strip-types
import { parseYahooQuote, quoteAgeSeconds, formatQuoteAge, type LiveQuoteKind, type LiveQuoteSpec, type YahooBars, type YahooChartMeta } from './live-quotes.ts';

export type VerifyStatus =
    /** Precio utilizable devuelto por el proveedor. */
    | 'ok'
    /** Respuesta bien formada pero sin precio utilizable (la UI pintaría N/D). */
    | 'sin_precio'
    /** La petición falló (timeout, HTTP no-2xx) antes de tener payload. */
    | 'error_http'
    /** HTTP 2xx pero el cuerpo no tiene la forma chart.result[0]. */
    | 'payload_roto';

export interface VerifyRow {
    symbol: string;
    name: string;
    kind: LiveQuoteKind;
    status: VerifyStatus;
    price: number | null;
    /** Segundos entre nowMs y el timestamp del proveedor; null si no hay hora. */
    ageSeconds: number | null;
    exchangeName: string | null;
    instrumentType: string | null;
    /** Divisa informada por el proveedor (informativa). */
    currency: string | null;
    /** Barras diarias válidas recibidas (base del cierre de referencia). */
    bars: number;
    /** true = el cambio tendría cierre de referencia demostrable (no N/D). */
    changeComputable: boolean;
}

/** Respuesta de red ya resuelta: status HTTP (null = fallo de red/timeout) y cuerpo parseado. */
export interface VerifyResponse {
    httpStatus: number | null;
    payload: unknown;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
    typeof value === 'object' && value !== null;

/**
 * Construye la fila de verificación de UN símbolo. Nunca lanza: cualquier
 * respuesta rota se clasifica, porque el informe existe justo para ver los
 * símbolos que fallan.
 */
export function buildVerifyRow(spec: LiveQuoteSpec, response: VerifyResponse, nowMs: number): VerifyRow {
    const base: VerifyRow = {
        symbol: spec.symbol,
        name: spec.name,
        kind: spec.kind,
        status: 'ok',
        price: null,
        ageSeconds: null,
        exchangeName: null,
        instrumentType: null,
        currency: null,
        bars: 0,
        changeComputable: false,
    };
    if (response.httpStatus === null || response.httpStatus < 200 || response.httpStatus >= 300) {
        return { ...base, status: 'error_http' };
    }
    if (!isRecord(response.payload) || !isRecord(response.payload.chart)) {
        return { ...base, status: 'payload_roto' };
    }
    const chart = response.payload.chart;
    // Yahoo informa el fallo por símbolo como chart.error (p.ej. "Not Found").
    if (chart.error !== null && chart.error !== undefined) {
        return { ...base, status: 'payload_roto' };
    }
    const result0 = Array.isArray(chart.result) ? chart.result[0] : undefined;
    if (!isRecord(result0)) {
        return { ...base, status: 'payload_roto' };
    }
    const meta = (isRecord(result0.meta) ? result0.meta : null) as YahooChartMeta | null;
    const timestamps = Array.isArray(result0.timestamp) ? (result0.timestamp as (number | null)[]) : undefined;
    const indicators = isRecord(result0.indicators) ? result0.indicators : null;
    const quote0 = indicators && Array.isArray(indicators.quote) ? indicators.quote[0] : null;
    const closes = isRecord(quote0) && Array.isArray(quote0.close) ? (quote0.close as (number | null)[]) : undefined;
    const bars: YahooBars = { timestamps, closes };
    const quote = parseYahooQuote(spec, meta, bars);
    if (!quote) {
        return { ...base, status: 'sin_precio' };
    }
    const validBars = (timestamps ?? []).filter(
        (t, i) => typeof t === 'number' && typeof closes?.[i] === 'number' && (closes[i] as number) > 0,
    );
    return {
        ...base,
        status: 'ok',
        price: quote.price,
        ageSeconds: quoteAgeSeconds(nowMs, quote.timestamp),
        exchangeName: quote.exchangeName,
        instrumentType: quote.instrumentType,
        currency: quote.currency,
        bars: validBars.length,
        changeComputable: quote.change !== null,
    };
}

export interface VerifySummary {
    total: number;
    ok: number;
    sinPrecio: number;
    errorHttp: number;
    payloadRoto: number;
    /** Filas OK cuyo cambio saldría N/D por falta de cierre de referencia. */
    sinReferencia: number;
    /** Mayor antigüedad medida entre las filas OK con hora (segundos); null si ninguna. */
    maxAgeSeconds: number | null;
}

export function summarizeVerifyRows(rows: VerifyRow[]): VerifySummary {
    const summary: VerifySummary = {
        total: rows.length,
        ok: 0,
        sinPrecio: 0,
        errorHttp: 0,
        payloadRoto: 0,
        sinReferencia: 0,
        maxAgeSeconds: null,
    };
    for (const row of rows) {
        if (row.status === 'ok') {
            summary.ok += 1;
            if (!row.changeComputable) summary.sinReferencia += 1;
            if (row.ageSeconds !== null && (summary.maxAgeSeconds === null || row.ageSeconds > summary.maxAgeSeconds)) {
                summary.maxAgeSeconds = row.ageSeconds;
            }
        } else if (row.status === 'sin_precio') {
            summary.sinPrecio += 1;
        } else if (row.status === 'error_http') {
            summary.errorHttp += 1;
        } else {
            summary.payloadRoto += 1;
        }
    }
    return summary;
}

// Etiquetas estructurales en inglés (texto de consola para desarrollo, no UI;
// el guard i18n de texto español hardcodeado mide todo lib/). La frase de
// antigüedad sí respeta el locale via formatQuoteAge.
const STATUS_LABEL: Record<VerifyStatus, string> = {
    ok: 'OK',
    sin_precio: 'NO_PRICE',
    error_http: 'HTTP_ERROR',
    payload_roto: 'BROKEN_PAYLOAD',
};

/**
 * Línea de informe para la consola: símbolo, estado, precio, antigüedad
 * medida (la escala honesta de formatQuoteAge), identidad del proveedor y
 * si el cambio tendría referencia. Sin colores ni emojis: sale en CI y logs.
 */
export function formatVerifyRow(row: VerifyRow, locale: 'es' | 'en' = 'es'): string {
    const parts = [
        row.symbol.padEnd(12),
        STATUS_LABEL[row.status].padEnd(12),
    ];
    if (row.status === 'ok') {
        parts.push(`price=${row.price}`);
        parts.push(`age=${row.ageSeconds === null ? 'N/D' : formatQuoteAge(row.ageSeconds, locale)}`);
        const identity = [row.exchangeName, row.instrumentType].filter((p) => p !== null).join('/');
        if (identity) parts.push(identity);
        parts.push(`bars=${row.bars}`);
        if (!row.changeComputable) parts.push('change=N/D');
    }
    return parts.join(' ');
}

/**
 * Veredicto del informe: la cobertura falla si algún símbolo del catálogo no
 * devuelve precio utilizable. El retraso NO se juzga (depende de la sesión
 * del mercado): se mide y se muestra, nunca se convierte en semáforo falso.
 */
export function verificationPassed(rows: VerifyRow[]): boolean {
    return rows.every((row) => row.status === 'ok');
}
