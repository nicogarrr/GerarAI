/**
 * Verificación EN VIVO de la cobertura y el retraso del catálogo /mercados.
 *
 * Pide cada símbolo del catálogo (lib/market/live-quotes.ts) a la chart API
 * de Yahoo con la MISMA request que usa la app (yahooChartRequest) y pinta un
 * informe por fila: precio, antigüedad medida, identidad del proveedor,
 * barras de referencia y si el cambio saldría N/D. Sale con código 1 si algún
 * símbolo del catálogo no devuelve precio utilizable (cobertura rota).
 *
 * No corre en CI (red real, proveedor externo): es la herramienta con la que
 * se re-verifica el catálogo antes de tocarlo y para medir el retraso real
 * durante la sesión.
 *
 * Uso:
 *   node --experimental-strip-types scripts/verify-live-markets.mjs
 */
import { LIVE_QUOTE_GROUPS, yahooChartRequest } from '../lib/market/live-quotes.ts';
import {
    buildVerifyRow,
    formatVerifyRow,
    summarizeVerifyRows,
    verificationPassed,
} from '../lib/market/live-markets-verify.ts';

const PER_SYMBOL_TIMEOUT_MS = 8_000;
const CONCURRENCY = 6;

async function fetchSymbol(spec) {
    const { url, init } = yahooChartRequest(spec.symbol);
    try {
        const resp = await fetch(url, { ...init, signal: AbortSignal.timeout(PER_SYMBOL_TIMEOUT_MS) });
        const payload = await resp.json().catch(() => null);
        return { httpStatus: resp.status, payload };
    } catch {
        return { httpStatus: null, payload: null };
    }
}

const specs = LIVE_QUOTE_GROUPS.flatMap((group) => group.specs);
const responses = new Map();
let next = 0;
const worker = async () => {
    while (next < specs.length) {
        const spec = specs[next++];
        responses.set(spec.symbol, await fetchSymbol(spec));
    }
};
await Promise.all(Array.from({ length: Math.min(CONCURRENCY, specs.length) }, worker));

const nowMs = Date.now();
const rows = specs.map((spec) => buildVerifyRow(spec, responses.get(spec.symbol), nowMs));
for (const row of rows) {
    console.log(formatVerifyRow(row));
}

const summary = summarizeVerifyRows(rows);
const maxAge = summary.maxAgeSeconds === null ? 'N/D' : `${Math.round(summary.maxAgeSeconds / 60)} min`;
console.log('');
console.log(
    `cobertura: ${summary.ok}/${summary.total} OK` +
    ` (sin precio: ${summary.sinPrecio}, error http: ${summary.errorHttp}, payload roto: ${summary.payloadRoto})`,
);
console.log(`cambio sin referencia (N/D): ${summary.sinReferencia} fila(s) OK`);
console.log(`antigüedad máxima medida: ${maxAge} (fuera de sesión es la edad del último cierre, no un fallo)`);

process.exit(verificationPassed(rows) ? 0 : 1);
