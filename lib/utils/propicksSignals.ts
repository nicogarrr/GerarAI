/**
 * Overlays de señales para Propicks (fases 1-3).
 *
 * SOLO USO EN SERVIDOR: lee API keys de `process.env` y llama a la
 * server action de insider. No importar desde componentes cliente.
 *
 * Garantías (exigidas por validación):
 *  - NUNCA lanza: cada fuente tiene su propio try/catch y la función
 *    principal también; si todo falla se devuelve [].
 *  - NUNCA usa datos posteriores a `asOf`: toda observación con fecha
 *    (trimestre, filing, liquidación, VIX) se filtra con fecha <= asOf.
 *    Los endpoints que solo devuelven "foto actual" sin fecha no se usan
 *    para cortes históricos (se descartan, no se extrapolan).
 *  - NUNCA inventa: sin dato real no hay overlay (se devuelve null).
 *  - Cada fuente usa timeout (8s) y caché en memoria corta (3 min).
 *  - `impact` siempre en [-10, +10] y `detail` incluye el valor numérico.
 */

import { getInsiderSignals } from '@/lib/actions/insider.actions';
import { formatNumber } from '@/lib/format';

export interface SignalOverlay {
    factor: 'revisiones' | 'insider' | 'shortInterest' | 'regimen';
    impact: number;
    detail: string;
    metric: string;
    value: number | string;
    asOf: string;
}

const FETCH_TIMEOUT_MS = 8000;
const CACHE_TTL_MS = 180_000; // 3 min: corta, solo evita repetir round-trips en bucle
const MS_PER_DAY = 86_400_000;

type CacheEntry = { exp: number; value: unknown };
const MEM_CACHE = new Map<string, CacheEntry>();

function cacheGet<T>(key: string): T | null {
    const entry = MEM_CACHE.get(key);
    if (!entry) return null;
    if (Date.now() > entry.exp) {
        MEM_CACHE.delete(key);
        return null;
    }
    return entry.value as T;
}

function cacheSet(key: string, value: unknown): void {
    if (MEM_CACHE.size > 500) MEM_CACHE.clear();
    MEM_CACHE.set(key, { exp: Date.now() + CACHE_TTL_MS, value });
}

function clampImpact(n: number): number {
    if (!Number.isFinite(n)) return 0;
    return Math.max(-10, Math.min(10, Math.round(n * 10) / 10));
}

function round1(n: number): number {
    return Math.round(n * 10) / 10;
}

/** Número con separadores es-ES para la prosa del `detail`. Ojo: el `detail`
 *  sigue incluyendo el valor CRUDO entre paréntesis porque la regla R5
 *  (propicksValidation) exige que `detail` contenga `String(overlay.value)`
 *  literal; formatearlo ahí rompería la trazabilidad del número. */
function fmtSigned(n: number): string {
    return formatNumber(round1(n), {
        minimumFractionDigits: 1,
        maximumFractionDigits: 1,
        signDisplay: 'always',
    });
}

function plural(count: number, singular: string, pluralForm: string): string {
    return `${formatNumber(count, { maximumFractionDigits: 0 })} ${count === 1 ? singular : pluralForm}`;
}

/** Día YYYY-MM-DD de un ISO, o null si inválido. */
function dayOf(iso: string): string | null {
    if (typeof iso !== 'string' || iso.length < 8) return null;
    const ms = Date.parse(iso);
    if (!Number.isFinite(ms)) return null;
    return new Date(ms).toISOString().slice(0, 10);
}

async function fetchWithTimeout(url: string, ms = FETCH_TIMEOUT_MS, init?: RequestInit): Promise<Response> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), ms);
    try {
        return await fetch(url, { ...init, signal: controller.signal, cache: 'no-store' });
    } finally {
        clearTimeout(timer);
    }
}

async function fetchJson<T>(url: string, cacheKey?: string): Promise<T | null> {
    try {
        if (cacheKey) {
            const hit = cacheGet<T>(cacheKey);
            if (hit !== null) return hit;
        }
        const res = await fetchWithTimeout(url);
        if (!res.ok) return null;
        const data = (await res.json()) as T;
        if (cacheKey && data !== null && data !== undefined) cacheSet(cacheKey, data);
        return data;
    } catch {
        return null;
    }
}

function strField(obj: Record<string, unknown>, keys: string[]): string | null {
    for (const key of keys) {
        const v = obj[key];
        if (typeof v === 'string' && v.trim().length > 0) return v.trim();
    }
    return null;
}

function numField(obj: Record<string, unknown>, keys: string[]): number | null {
    for (const key of keys) {
        const v = obj[key];
        if (typeof v === 'number' && Number.isFinite(v)) return v;
        if (typeof v === 'string' && v.trim() !== '' && Number.isFinite(Number(v))) return Number(v);
    }
    return null;
}

/* ------------------------------------------------------------------ */
/* 1. Revisiones de estimados / sorpresas de beneficios (Finnhub).      */
/* Endpoint con fecha por trimestre: se filtra period <= asOf.         */
/* ------------------------------------------------------------------ */

type FinnhubEarningsRow = {
    actual?: number | null;
    estimate?: number | null;
    period?: string;
};

async function revisionOverlay(symbol: string, cutoffDay: string): Promise<SignalOverlay | null> {
    try {
        const token = process.env.FINNHUB_API_KEY;
        if (!token) return null;
        const url = `https://finnhub.io/api/v1/stock/earnings?symbol=${encodeURIComponent(symbol)}&token=${token}`;
        const rows = await fetchJson<FinnhubEarningsRow[]>(url, `ov:rev:${symbol}:${cutoffDay}`);
        if (!Array.isArray(rows) || rows.length === 0) return null;

        const valid = rows
            .filter((r) => {
                const period = typeof r?.period === 'string' ? r.period.slice(0, 10) : '';
                if (!period || period > cutoffDay) return false; // NUNCA dato posterior a asOf
                if (typeof r?.actual !== 'number' || !Number.isFinite(r.actual)) return false;
                if (typeof r?.estimate !== 'number' || !Number.isFinite(r.estimate) || r.estimate === 0) return false;
                return true;
            })
            .sort((a, b) => String(b.period).localeCompare(String(a.period)))
            .slice(0, 4);
        if (valid.length === 0) return null;

        const surprises = valid.map((r) => ((r.actual as number) - (r.estimate as number)) / Math.abs(r.estimate as number) * 100);
        const avg = surprises.reduce((s, v) => s + v, 0) / surprises.length;
        if (!Number.isFinite(avg)) return null;
        const impact = clampImpact(avg / 2); // +10% sorpresa media -> +5
        if (impact === 0) return null;

        const lastPeriod = String(valid[0]?.period).slice(0, 10);
        const avgR = round1(avg);
        return {
            factor: 'revisiones',
            impact,
            detail: `Sorpresa media de beneficios ${fmtSigned(avgR)} % en ${plural(valid.length, 'trimestre', 'trimestres')} hasta ${lastPeriod} (valor ${avgR})`,
            metric: 'ov_revisiones',
            value: avgR,
            asOf: cutoffDay,
        };
    } catch {
        return null;
    }
}

/* ------------------------------------------------------------------ */
/* 2. Insider buying neto 90d (server action existente).               */
/* Solo filings con fecha <= asOf y dentro de la ventana 90d.          */
/* ------------------------------------------------------------------ */

async function insiderOverlay(
    symbol: string,
    cutoffMs: number,
    cutoffDay: string,
): Promise<SignalOverlay | null> {
    try {
        const res = await getInsiderSignals(symbol, { limit: 50 });
        const signals = Array.isArray(res?.signals) ? res.signals : [];
        if (signals.length === 0) return null;

        const windowStart = cutoffMs - 90 * MS_PER_DAY;
        let buys = 0;
        let sells = 0;
        let netShares = 0;

        for (const raw of signals) {
            if (!raw || typeof raw !== 'object') continue;
            const s = raw as Record<string, unknown>;
            const dateStr = strField(s, ['filed_at', 'filing_date', 'filedAt', 'filingDate', 'date', 'transaction_date']);
            if (!dateStr) continue; // sin fecha no se puede probar que sea <= asOf: se descarta
            const ms = Date.parse(dateStr);
            if (!Number.isFinite(ms) || ms > cutoffMs || ms < windowStart) continue;

            const side = (strField(s, ['transaction_type', 'transaction', 'side', 'type', 'acquisition_disposition']) ?? '').toLowerCase();
            const isBuy = side.includes('buy') || side === 'p' || side.includes('acquir') || side.includes('purchase');
            const isSell = side.includes('sell') || side === 's' || side.includes('dispos') || side.includes('sale');
            if (isBuy === isSell) continue; // dirección ambigua: no se cuenta, no se inventa
            const shares = numField(s, ['shares', 'share_count', 'amount', 'quantity']);
            const weight = shares !== null && shares > 0 ? shares : 1;

            if (isBuy) {
                buys += 1;
                netShares += weight;
            } else {
                sells += 1;
                netShares -= weight;
            }
        }

        if (buys + sells === 0) return null;
        const impact = clampImpact(((buys - sells) / (buys + sells)) * 10);
        if (impact === 0) return null;

        const netR = round1(netShares);
        return {
            factor: 'insider',
            impact,
            detail: `Compra neta insider: ${plural(buys, 'compra', 'compras')} frente a ${plural(sells, 'venta', 'ventas')} en 90 días hasta ${cutoffDay} (valor ${netR})`,
            metric: 'ov_insider',
            value: netR,
            asOf: cutoffDay,
        };
    } catch {
        return null;
    }
}

/* ------------------------------------------------------------------ */
/* 3. Short interest FINRA (fichero público quincenal, timeout 8s).    */
/* Si el fichero no existe / no parsea / no trae el símbolo: sin       */
/* overlay. El mapeo SI->impact es heurístico y está documentado aquí. */
/* ------------------------------------------------------------------ */

function finraSettlementCandidates(cutoffDay: string): string[] {
    // Liquidaciones quincenales aprox: día 15 y último día de mes <= asOf.
    const [y, m] = cutoffDay.split('-').map(Number);
    const out: string[] = [];
    const push = (yy: number, mm: number, dd: number) => {
        const d = `${yy}-${String(mm).padStart(2, '0')}-${String(dd).padStart(2, '0')}`;
        if (d <= cutoffDay) out.push(d.replace(/-/g, ''));
    };
    const lastDay = new Date(Date.UTC(y, m, 0)).getUTCDate();
    push(y, m, lastDay);
    push(y, m, 15);
    const pm = m === 1 ? 12 : m - 1;
    const py = m === 1 ? y - 1 : y;
    push(py, pm, new Date(Date.UTC(py, pm, 0)).getUTCDate());
    return [...new Set(out)];
}

function parseFinraShortInterest(text: string, symbol: string, cutoffDay: string): { si: number; settle: string } | null {
    const lines = text.split(/\r?\n/);
    for (const line of lines) {
        if (!line) continue;
        const tokens = line.split(/[|,;\t]/).map((t) => t.trim());
        if (tokens.length < 3) continue;
        const symIdx = tokens.findIndex((t) => t.toUpperCase() === symbol);
        if (symIdx === -1) continue;
        const dateTok = tokens.find((t) => /^\d{4}-?\d{2}-?\d{2}$/.test(t));
        const settle = dateTok ? dateTok.replace(/-/g, '').length === 8
            ? `${dateTok.replace(/-/g, '').slice(0, 4)}-${dateTok.replace(/-/g, '').slice(4, 6)}-${dateTok.replace(/-/g, '').slice(6, 8)}`
            : dateTok.slice(0, 10) : null;
        if (!settle || settle > cutoffDay) continue; // NUNCA dato posterior a asOf
        const nums = tokens
            // Excluir el token de fecha (yyyymmdd ~ 20M): si entraba en la
            // lista, Math.max devolvía la fecha como "short interest" para
            // cualquier valor con SI real menor que ~20M acciones.
            .filter((t) => !/^\d{4}-?\d{2}-?\d{2}$/.test(t))
            .map((t) => Number(t.replace(/,/g, '')))
            .filter((n) => Number.isFinite(n) && n > 0 && Number.isInteger(n));
        if (nums.length === 0) continue;
        const si = Math.max(...nums);
        return { si, settle };
    }
    return null;
}

async function shortInterestOverlay(symbol: string, cutoffDay: string): Promise<SignalOverlay | null> {
    try {
        for (const stamp of finraSettlementCandidates(cutoffDay)) {
            const cacheKey = `ov:si:${symbol}:${stamp}`;
            const cached = cacheGet<{ si: number; settle: string }>(cacheKey);
            if (cached) {
                const impact = siImpact(cached.si);
                if (impact === 0) return null;
                return {
                    factor: 'shortInterest',
                    impact,
                    detail: `Interés en corto FINRA de ${formatNumber(cached.si, { maximumFractionDigits: 0 })} acciones a ${cached.settle} (valor ${cached.si})`,
                    metric: 'ov_shortInterest',
                    value: cached.si,
                    asOf: cutoffDay,
                };
            }
            const candidates = [
                `https://cdn.finra.org/equity/shortinterest/biweekly/v2/short-interest-consolidated-${stamp}.txt`,
                `https://cdn.finra.org/equity/shortinterest/biweekly/short-interest-consolidated-${stamp}.txt`,
            ];
            for (const url of candidates) {
                try {
                    const res = await fetchWithTimeout(url, FETCH_TIMEOUT_MS);
                    if (!res.ok) continue;
                    const text = await res.text();
                    if (!text || text.length < 10) continue;
                    const parsed = parseFinraShortInterest(text, symbol, cutoffDay);
                    if (!parsed) continue;
                    cacheSet(cacheKey, parsed);
                    const impact = siImpact(parsed.si);
                    if (impact === 0) return null;
                    return {
                        factor: 'shortInterest',
                        impact,
                        detail: `Interés en corto FINRA de ${formatNumber(parsed.si, { maximumFractionDigits: 0 })} acciones a ${parsed.settle} (valor ${parsed.si})`,
                        metric: 'ov_shortInterest',
                        value: parsed.si,
                        asOf: cutoffDay,
                    };
                } catch {
                    continue; // si falla, se prueba la siguiente URL; sin overlay si todo falla
                }
            }
        }
        return null;
    } catch {
        return null;
    }
}

/** Heurística documentada: a mayor short interest, sesgo negativo. */
function siImpact(si: number): number {
    if (!Number.isFinite(si) || si <= 0) return 0;
    if (si >= 10_000_000) return -6;
    if (si >= 1_000_000) return -3;
    if (si >= 100_000) return -1;
    return 0;
}

/* ------------------------------------------------------------------ */
/* 4. Régimen VIX (FRED VIXCLS si hay key; si no, Stooq ^VIX).         */
/* Se toma el último cierre con fecha <= asOf. Impacto negativo con    */
/* VIX > 30; positivo moderado con VIX < 15; neutro sin overlay.       */
/* ------------------------------------------------------------------ */

type FredObs = { observations?: Array<{ date?: string; value?: string }> };

async function fredVix(cutoffDay: string): Promise<{ vix: number; date: string } | null> {
    const key = process.env.FRED_API_KEY;
    if (!key) return null;
    const url = `https://api.stlouisfed.org/fred/series/observations?series_id=VIXCLS&api_key=${key}&file_type=json&sort_order=desc&observation_end=${cutoffDay}&limit=1`;
    const data = await fetchJson<FredObs>(url, `ov:vix:fred:${cutoffDay}`);
    const obs = data?.observations?.[0];
    if (!obs?.date || obs.date.slice(0, 10) > cutoffDay) return null;
    const v = Number(obs.value);
    if (!Number.isFinite(v)) return null; // FRED usa "." en festivos: sin dato, sin overlay
    return { vix: v, date: obs.date.slice(0, 10) };
}

async function stooqVix(cutoffDay: string): Promise<{ vix: number; date: string } | null> {
    const compact = cutoffDay.replace(/-/g, '');
    const url = `https://stooq.com/q/d/l/?s=%5Evix&d1=19900101&d2=${compact}&i=d`;
    const cacheKey = `ov:vix:stooq:${cutoffDay}`;
    const cached = cacheGet<{ vix: number; date: string }>(cacheKey);
    if (cached) return cached;
    try {
        const res = await fetchWithTimeout(url, FETCH_TIMEOUT_MS);
        if (!res.ok) return null;
        const text = await res.text();
        const lines = text.trim().split(/\r?\n/);
        let best: { vix: number; date: string } | null = null;
        for (let i = 1; i < lines.length; i++) {
            const cols = (lines[i] ?? '').split(',');
            const d = (cols[0] ?? '').slice(0, 10);
            const close = Number(cols[4]);
            if (!d || d > cutoffDay || !Number.isFinite(close)) continue;
            best = { vix: close, date: d }; // el CSV viene ordenado: nos quedamos con el último <= asOf
        }
        if (best) cacheSet(cacheKey, best);
        return best;
    } catch {
        return null;
    }
}

async function regimenOverlay(cutoffDay: string): Promise<SignalOverlay | null> {
    try {
        const found = (await fredVix(cutoffDay).catch(() => null)) ?? (await stooqVix(cutoffDay).catch(() => null));
        if (!found) return null;
        const v = round1(found.vix);
        let impact: number;
        let regime: string;
        if (found.vix > 35) {
            impact = -8;
            regime = 'pánico';
        } else if (found.vix > 30) {
            impact = -5;
            regime = 'aversión al riesgo alta';
        } else if (found.vix > 25) {
            impact = -2;
            regime = 'tensión moderada';
        } else if (found.vix < 15) {
            impact = 2;
            regime = 'complacencia/calma';
        } else {
            return null; // régimen neutro: sin overlay, no se inventa señal
        }
        return {
            factor: 'regimen',
            impact,
            detail: `VIX en ${formatNumber(v, { minimumFractionDigits: 1, maximumFractionDigits: 1 })} el ${found.date} (régimen de ${regime}) (valor ${v})`,
            metric: 'ov_vix',
            value: v,
            asOf: cutoffDay,
        };
    } catch {
        return null;
    }
}

/* ------------------------------------------------------------------ */

export async function getSignalOverlays(symbol: string, asOf: string): Promise<SignalOverlay[]> {
    try {
        const sym = (symbol ?? '').trim().toUpperCase();
        const cutoffDay = dayOf(asOf);
        const cutoffMs = Date.parse(asOf);
        if (!sym || !cutoffDay || !Number.isFinite(cutoffMs)) return [];

        const [rev, ins, si, reg] = await Promise.all([
            revisionOverlay(sym, cutoffDay),
            insiderOverlay(sym, cutoffMs, cutoffDay),
            shortInterestOverlay(sym, cutoffDay),
            regimenOverlay(cutoffDay),
        ]);
        return [rev, ins, si, reg].filter((o): o is SignalOverlay => o !== null);
    } catch {
        return [];
    }
}
