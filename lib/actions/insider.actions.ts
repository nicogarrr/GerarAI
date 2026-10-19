'use server';

import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { researchRequest } from '@/lib/research/client';
import { cachedFetch } from '@/lib/cache/memoryTTL';

export type InsiderSignal = Record<string, unknown>;

export interface InsiderSignalsResult extends Record<string, unknown> {
    ticker: string;
    cik?: string | null;
    status: string;
    filings_scanned?: number;
    buy_count?: number;
    signals: InsiderSignal[];
    reason?: string;
    filing_errors?: string[];
    notification?: Record<string, unknown>;
}

export interface InsiderSignalsOptions {
    limit?: number;
    notify?: boolean;
}

/** GET /api/insider/signals — señales cluster_buy / c_suite_buy / big_buy (Form 4, SEC EDGAR) */
export async function getInsiderSignals(
    ticker: string,
    options?: InsiderSignalsOptions,
): Promise<InsiderSignalsResult> {
    // Clave de caché con userId: la caché es por proceso de servidor y sin
    // identidad devolvería los datos del usuario que 충전ó primero.
    const { id: userId } = await requireAuthenticatedUser();
    const clean = ticker.trim().toUpperCase();
    const params = new URLSearchParams({ ticker: clean });
    if (options?.limit !== undefined) params.set('limit', String(options.limit));
    if (options?.notify) params.set('notify', 'true');
    const path = `/api/insider/signals?${params.toString()}`;
    if (options?.notify) return researchRequest<InsiderSignalsResult>(path, { fast: true });
    return cachedFetch(
        `insider:user:${userId}:signals:${clean}:${params.get('limit') ?? 'default'}`,
        () => researchRequest<InsiderSignalsResult>(path, { fast: true }),
        15,
    );
}

export interface InsiderFilingTransaction {
    insider?: string | null;
    role?: string | null;
    officer_title?: string | null;
    code?: string | null;
    /** Derivado (opciones) vs acciones; explica tramos M duplicados. */
    is_derivative?: boolean | null;
    /** Titulo del valor en el Form 4 (RSU, PSU, opcion...): distingue concesiones del mismo tamano. */
    security_title?: string | null;
    /** Operacion declarada bajo plan 10b5-1 (checkbox o nota al pie del Form 4). */
    rule_10b5_1?: boolean | null;
    shares?: number | null;
    price?: number | null;
    value?: number | null;
    tx_date?: string | null;
    source_url?: string | null;
}

export interface InsiderFilingEntry {
    accession_number: string;
    form: string;
    is_amendment: boolean;
    filing_date?: string | null;
    report_date?: string | null;
    source_url?: string | null;
    transaction_count: number;
    transactions: InsiderFilingTransaction[];
}

export interface InsiderFilingsResult {
    ticker: string;
    status: string;
    reason?: string;
    count: number;
    /** Total persistido del ticker; `count` son los de esta página. */
    total?: number;
    filings: InsiderFilingEntry[];
}

/** GET /api/insider/filings — filings Form 4/4-A persistidos (lectura durable). */
export async function getInsiderFilings(
    ticker: string,
    limit = 20,
): Promise<InsiderFilingsResult> {
    const { id: userId } = await requireAuthenticatedUser();
    const clean = ticker.trim().toUpperCase();
    const params = new URLSearchParams({ ticker: clean, limit: String(limit) });
    return cachedFetch(
        `insider:user:${userId}:filings:${clean}:${limit}`,
        () => researchRequest<InsiderFilingsResult>(`/api/insider/filings?${params.toString()}`, { fast: true }),
        30,
    );
}

/** Página siguiente de filings persistidos (botón «Cargar más»); sin caché. */
export async function loadMoreInsiderFilings(
    ticker: string,
    offset: number,
    limit = 20,
): Promise<InsiderFilingsResult> {
    await requireAuthenticatedUser();
    const clean = ticker.trim().toUpperCase();
    const safeOffset = Math.max(0, Math.floor(Number(offset) || 0));
    const safeLimit = Math.min(50, Math.max(1, Math.floor(Number(limit) || 20)));
    const params = new URLSearchParams({
        ticker: clean,
        limit: String(safeLimit),
        offset: String(safeOffset),
    });
    return researchRequest<InsiderFilingsResult>(`/api/insider/filings?${params.toString()}`, { fast: true });
}

export interface InsiderFeedTransaction {
    ticker: string;
    issuer_name?: string | null;
    insider?: string | null;
    role?: string | null;
    officer_title?: string | null;
    side?: 'compra' | 'venta' | null;
    shares?: number | null;
    price?: number | null;
    value?: number | null;
    date?: string | null;
    /** Tramos Form 4 agregados en esta fila (mismo filing + insider + codigo). */
    tranches?: number;
    /** Plan 10b5-1 declarado en todos los tramos de la fila. */
    rule_10b5_1?: boolean;
    accession_number: string;
    source_url?: string | null;
}

export interface InsiderFeedSignal {
    ticker: string;
    insider?: string | null;
    role?: string | null;
    officer_title?: string | null;
    value?: number | null;
    date?: string | null;
    accession_number?: string;
    tx_line?: number;
    insider_count?: number;
    total_value?: number;
    window_start?: string;
}

export interface InsiderFeedResult {
    status: string;
    days: number;
    side: string;
    count: number;
    totals: {
        buy_count: number;
        buy_value: number;
        sell_count: number;
        sell_value: number;
        filings_total: number;
        filings_with_transactions: number;
        filings_pending: number;
    };
    clusters: InsiderFeedSignal[];
    c_suite_buys: InsiderFeedSignal[];
    /** Compras codigo P de mas de $1M (detectadas, no siempre presentes). */
    big_buys?: InsiderFeedSignal[];
    transactions: InsiderFeedTransaction[];
}

/** GET /api/insider/feed — operaciones insider persistidas de todos los emisores. */
export async function getInsiderFeed(side: string, days: number): Promise<InsiderFeedResult> {
    const { id: userId } = await requireAuthenticatedUser();
    const params = new URLSearchParams({ side, days: String(days), limit: '100' });
    return cachedFetch(
        `insider:user:${userId}:feed:${side}:${days}`,
        () => researchRequest<InsiderFeedResult>(`/api/insider/feed?${params.toString()}`, { fast: true }),
        60,
    );
}

export interface InsiderOperationsSide {
    trades: number;
    shares: number;
    value: number;
    /** Importe/acciones solo de filas con AMBOS datos; null si hay filas sin importe (declarado). */
    avg_price: number | null;
    /** Acciones de filas sin importe: no entran al precio medio. */
    shares_without_value: number;
    rows_without_value: number;
}

export interface InsiderOperationsInsider {
    insider: string | null;
    role: string | null;
    officer_title: string | null;
    buy: InsiderOperationsSide;
    sell: InsiderOperationsSide;
    last_tx: string | null;
}

export interface InsiderOperationsCompany {
    ticker: string;
    company: string;
    origin: 'cartera' | 'watchlist';
    period: { from: string | null; to: string | null };
    filings: number;
    /** Enmiendas 4/A del periodo: el original sustituido no se puede enlazar (amends_accession sin poblar). */
    amended_filings: number;
    totals: { buy: InsiderOperationsSide; sell: InsiderOperationsSide };
    insiders: InsiderOperationsInsider[];
    excluded_codes: number;
    excluded_derivative: number;
    rows_without_date: number;
}

export interface InsiderOperationsResult {
    status: 'ok' | 'unavailable';
    reason?: string;
    days: number;
    as_of?: string;
    note?: string;
    companies: InsiderOperationsCompany[];
    companies_without_data: string[];
}

/** GET /api/insider/operations — agregado P/S por empresa (cartera + watchlist), Form 4 persistidos. */
export async function getInsiderOperations(days = 365): Promise<InsiderOperationsResult> {
    const { id: userId } = await requireAuthenticatedUser();
    return cachedFetch(
        `insider:user:${userId}:operations:${days}`,
        () => researchRequest<InsiderOperationsResult>(`/api/insider/operations?days=${days}`, { fast: true }),
        60,
    );
}
