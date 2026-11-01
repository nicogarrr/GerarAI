'use server';

import type { TrackedAnalysisStatus } from '@/lib/tracked-analysis-status';
import type { components } from '@/lib/research/openapi.generated';
import { BACKEND_PAGE_SIZE, fetchAllBackendPages, type PaginatedBackendResponse } from '@/lib/paginated-backend';

import { qualifiedHistoricalMetrics, verifiedPortfolioHistory, type PortfolioSnapshotPoint } from '@/lib/portfolio-history';

import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { jsonBody, researchRequest } from '@/lib/research/client';
import { cachedFetch } from '@/lib/cache/memoryTTL';
import { requestCache } from '@/lib/cache/requestCache';
import { AppError, AuthorizationError, ValidationError } from '@/lib/types/errors';
import { sumCashByCurrency } from '@/lib/portfolio-cash';
import { buildAllocationSlices } from '@/lib/portfolio-allocation';
import { partitionSettledRefreshes } from '@/lib/portfolio/refresh-settled';
import { importRejection, type ImportRejection } from '@/lib/portfolio/import-rejection';
import { ledgerRejection } from '@/lib/portfolio/ledger-rejection';
import { transactionFiltersQuery, type TransactionFilters } from '@/lib/portfolio/transaction-filters';

const FINNHUB_BASE_URL = 'https://finnhub.io/api/v1';
const FINNHUB_API_KEY = process.env.FINNHUB_API_KEY;

async function resolveUserId(requestedUserId?: string): Promise<string> {
    const user = await requireAuthenticatedUser();
    if (requestedUserId && requestedUserId !== user.id) {
        throw new AuthorizationError('Cannot access another user portfolio');
    }
    return user.id;
}

function invalidatePortfolioReads(userId: string): void {
    for (const suffix of ['positions', 'summary', 'transactions', 'scores', 'tearsheet', 'dividends']) {
        requestCache.invalidate(`portfolio:${userId}:${suffix}`);
    }
}

async function getQuote(symbol: string): Promise<{ c: number } | null> {
    try {
        if (!FINNHUB_API_KEY) return null;
        // Timeout por carrera y NO por signal: pasar `signal` al fetch
        // desactivaría la Data Cache de Next (revalidate: 60) y multiplicaría
        // las llamadas a Finnhub (cuota free compartida). Si Finnhub no
        // responde en 8s se devuelve null como cualquier otro fallo.
        const response = await Promise.race([
            fetch(
                `${FINNHUB_BASE_URL}/quote?symbol=${encodeURIComponent(symbol)}&token=${FINNHUB_API_KEY}`,
                { next: { revalidate: 60 } }
            ),
            new Promise<never>((_, reject) =>
                setTimeout(() => reject(new Error('Finnhub quote timeout (8s)')), 8_000)
            ),
        ]);
        if (!response.ok) return null;
        return await response.json();
    } catch (error) {
        // El simbolo llega del cliente: se pasa como argumento separado, nunca
        // dentro de la cadena de formato (CodeQL js/format-string).
        console.error('Error fetching quote for', symbol, error);
        return null;
    }
}

export type PortfolioHolding = {
    analysis?: TrackedAnalysisStatus | null;
    symbol: string;
    quantity: number;
    avgPrice: number;
    costReviewMessage?: string | null;
    /** null = valoración en suspensión: no hay cotización actual que mostrar. */
    currentPrice: number | null;
    /** Motivo y fecha de la suspensión de valoración (p. ej. split sin precio post-split verificado). */
    valuationHold: { reason: string; effectiveDate: string | null } | null;
    value: number;
    cost: number;
    gain: number;
    gainPercent: number;
    nativeCurrency: string;
    baseCurrency: string;
    fxMissing: boolean;
    /** A3: sin cotización real (el precio es el de la última operación): la plusvalía es desconocida. */
    quoteMissing?: boolean;
    /** G/P y coste en divisa nativa tal como los expone la API (null si no hay dato). */
    nativeGain: number | null;
    nativeCost: number | null;
    /** G/P en base partida: efecto precio y efecto divisa (suman la G/P). */
    priceEffect?: number | null;
    fxEffect?: number | null;
    /** El valor en divisa base no está disponible (independiente del coste). */
    valueMissing: boolean;
    firstBuyDate: string | null;
    /** Fecha de la valoración de ESTA posición (la del resumen es la mínima de todas). */
    asOf?: string | null;
    holdingDays: number | null;
    fiscalBucket: 'corto_plazo' | 'largo_plazo' | null;
};

export type PortfolioSummary = {
    totalValue: number;
    totalCost: number;
    totalGain: number;
    totalGainPercent: number;
    /** Posiciones fuera de coste/ganancia/rendimiento por no tener valor o coste en base
     *  (sin precio, sin FX o en suspensión). Opcional: 0 si falta. */
    totalsExcluded?: number;
    holdings: PortfolioHolding[];
    /** Valor en renta variable (suma de posiciones), sin caja. */
    equityValue: number;
    /** Caja total en divisa base. totalValue = equityValue + cash.
     *  Derivada del diccionario `cash` por moneda del backend. */
    cash: number;
    /** Saldos positivos y deudores separados, ya convertidos a divisa base. */
    cashAssets?: number;
    marginDebt?: number;
    baseCurrency: string;
    status: 'ok' | 'incomplete_fx' | 'incomplete_valuation';
    missingFx: Array<Record<string, unknown>>;
    /** Posiciones excluidas de los totales por valoración en suspensión (independiente de FX). */
    valuationHold: Array<{ ticker: string; reason: string; effective_date: string | null }>;
    /** Tipo (divisa base por unidad de divisa original) y fecha usados en cada conversion. */
    fxRates?: PortfolioFxRate[];
    cashAsOf?: string | null;
    positionsAsOf?: string | null;
    valuationDatesDiffer?: boolean;
    quality?: PortfolioDataQuality | null;
};

export type PortfolioFxRate = components['schemas']['PortfolioFxRateOut'];

type ResearchPortfolioTransaction = components['schemas']['PortfolioTransactionOut'];

type ResearchPortfolioPosition = components['schemas']['PortfolioPositionItemOut'];

type ResearchPortfolioSummaryResponse = components['schemas']['PortfolioSummaryOut'];

export async function addTransaction(
    userId: string,
    symbol: string,
    type: 'buy' | 'sell',
    quantity: number,
    price: number,
    date: Date,
    notes?: string,
    currency = 'USD',
    fees = 0,
): Promise<{ success: boolean; error?: string }> {
    const canonicalUserId = await resolveUserId(userId);
    if (!Number.isFinite(quantity) || quantity <= 0 || !Number.isFinite(price) || price < 0) {
        throw new ValidationError('La cantidad debe ser positiva y el precio no puede ser negativo.');
    }
    if (!Number.isFinite(fees) || fees < 0) {
        throw new ValidationError('Las comisiones no pueden ser negativas.');
    }
    try {
        // El POST admite acciones de caja (dividend/interest/fee/cash_misc):
        // su contrato es PortfolioTransactionCreateOut, mas amplio que el del listado.
        await researchRequest<components['schemas']['PortfolioTransactionCreateOut']>('/api/portfolio/transactions', {
            method: 'POST',
            body: jsonBody({
                ticker: symbol.toUpperCase(),
                action: type,
                quantity,
                price,
                trade_date: date.toISOString().slice(0, 10),
                notes: notes || null,
                currency: currency.toUpperCase(),
                fees,
            }),
        });
    } catch (error) {
        const rejection = ledgerRejection(error);
        if (rejection) return { success: false, error: rejection };
        throw error;
    }
    invalidatePortfolioReads(canonicalUserId);
    return { success: true };
}

export async function getPortfolioTransactions(userId: string) {
    const canonicalUserId = await resolveUserId(userId);
    const raw = await cachedFetch(
        `portfolio:${canonicalUserId}:transactions`,
        () => fetchAllBackendPages(
            (page) => researchRequest<PaginatedBackendResponse<ResearchPortfolioTransaction>>(`/api/portfolio/transactions?page=${page}&page_size=${BACKEND_PAGE_SIZE}`, { fast: true }),
            (transaction) => String(transaction.id),
        ),
        15,
    );
    const transactions = raw;
    return transactions.map((transaction) => ({
        _id: String(transaction.id),
        symbol: transaction.ticker,
        type: transaction.action,
        quantity: transaction.quantity,
        price: transaction.price,
        fees: transaction.fees,
        date: transaction.trade_date,
        notes: transaction.notes ?? undefined,
        currency: transaction.currency,
        createdAt: transaction.created_at,
        updatedAt: transaction.updated_at,
    }));
}

export async function getPortfolioTransactionPage(userId: string, offset = 0, filters: TransactionFilters = {}) {
    // Sin binding: la llamada es el control de autorización (lanza si la
    // cartera pedida no es la del usuario autenticado); la página la sirve el
    // backend con la sesión.
    await resolveUserId(userId);
    const safeOffset = Number.isSafeInteger(offset) && offset >= 0 ? offset : 0;
    const page = await researchRequest<components['schemas']['PortfolioTransactionPageOut']>(
        `/api/portfolio/transactions/page?limit=50&offset=${safeOffset}${transactionFiltersQuery(filters)}`, { fast: true },
    );
    const items = page.items.map((transaction) => ({
        _id: String(transaction.id),
        symbol: transaction.ticker,
        type: transaction.action,
        quantity: transaction.quantity,
        price: transaction.price,
        fees: transaction.fees,
        date: transaction.trade_date,
        notes: transaction.notes ?? undefined,
        currency: transaction.currency,
        createdAt: transaction.created_at,
        updatedAt: transaction.updated_at,
    }));
    return { items, total: page.total, offset: safeOffset, filters };
}


/**
 * Tipos de cambio de la cartera para páginas que no cargan la cartera entera
 * (watchlist): misma lectura cacheada del resumen que usa Cartera, así el
 * objetivo de analistas de un ADR se convierte igual en las dos (auditoría
 * A9). Nunca rompe la página: sin cartera o con el motor caído devuelve una
 * lista vacía y la línea vuelve a la etiqueta «(ADR, USD)».
 */
export async function getPortfolioFxContext(userId: string): Promise<{ fxRates: PortfolioFxRate[]; baseCurrency: string | null }> {
    try {
        const canonicalUserId = await resolveUserId(userId);
        const summary = await cachedFetch(
            `portfolio:${canonicalUserId}:summary`,
            () => researchRequest<ResearchPortfolioSummaryResponse>('/api/portfolio/summary', { fast: true }),
            15,
        );
        return { fxRates: summary.fx_rates ?? [], baseCurrency: summary.base_currency || null };
    } catch {
        return { fxRates: [], baseCurrency: null };
    }
}

export async function getPortfolioSummary(userId: string): Promise<PortfolioSummary> {
    const canonicalUserId = await resolveUserId(userId);
    const [rawPositions, backendSummary, quality] = await Promise.all([
        cachedFetch(
            `portfolio:${canonicalUserId}:positions`,
            () => fetchAllBackendPages(
                (page) => researchRequest<PaginatedBackendResponse<ResearchPortfolioPosition>>(`/api/portfolio/positions?page=${page}&page_size=${BACKEND_PAGE_SIZE}`, { fast: true }),
                (position) => position.ticker,
            ),
            15,
        ),
        cachedFetch(
            `portfolio:${canonicalUserId}:summary`,
            () => researchRequest<ResearchPortfolioSummaryResponse>('/api/portfolio/summary', { fast: true }),
            15,
        ),
        getPortfolioDataQuality(canonicalUserId),
    ]);
    const positions = rawPositions;
    const holdings = positions.map((position): PortfolioHolding => {
        const held = Boolean(position.valuation_hold);
        const currentPrice = held ? null : position.market_price;
        const cost = position.cost_basis_base ?? 0;
        const value = position.market_value_base ?? 0;
        const gain = position.unrealized_pnl_base ?? 0;
        return {
            symbol: position.ticker,
            analysis: position.analysis,
            quantity: position.quantity,
            avgPrice: position.average_cost ?? 0,
            costReviewMessage: position.cost_reconciliation && (position.cost_reconciliation.status !== 'ok' || position.average_cost == null) ? position.cost_reconciliation.message || 'Divisa del coste de IBKR sin verificar.' : null,
            currentPrice,
            valuationHold: position.valuation_hold ? { reason: position.valuation_hold.reason, effectiveDate: position.valuation_hold.effective_date } : null,
            value,
            cost,
            gain,
            gainPercent: cost > 0 ? (gain / cost) * 100 : 0,
            nativeCurrency: position.native_currency,
            baseCurrency: position.base_currency,
            // fxMissing = no hay valor/rentabilidad base válidos. En suspensión de valoración también
            // (la UI muestra el motivo real vía valuationHold, no «conversión»).
            fxMissing: held || position.market_value_base === null || position.cost_basis_base === null,
            quoteMissing: position.quote_missing === true,
            nativeGain: position.unrealized_pnl_native ?? null,
            nativeCost: position.cost_basis_native ?? null,
            priceEffect: position.pnl_price_effect_base ?? null,
            fxEffect: position.pnl_fx_effect_base ?? null,
            valueMissing: position.market_value_base === null,
            firstBuyDate: position.first_buy_date ?? null,
            asOf: position.as_of ?? null,
            holdingDays: position.holding_days ?? null,
            fiscalBucket: position.fiscal_bucket ?? null,
        };
    });
    const totalValue = backendSummary.total_value;
    // Coste y ganancia solo sobre las posiciones con valor Y coste en base conocidos:
    // el backend ya deja fuera del valor RV las que no tienen precio, FX o están en
    // suspensión (y un coste IBKR pendiente de revisión no es base fiable). Sumar su coste sin su ganancia diluía el rendimiento (coste 2.000,
    // ganancia 500 → +25 % en vez de +50 %) y descuadraba Cartera con /inicio.
    const valued = holdings.filter((holding) => !holding.fxMissing && !holding.quoteMissing && holding.cost > 0 && !holding.costReviewMessage);
    const totalCost = valued.reduce((sum, holding) => sum + holding.cost, 0);
    const totalGain = valued.reduce((sum, holding) => sum + holding.gain, 0);
    return {
        totalValue,
        totalCost,
        totalGain,
        totalGainPercent: totalCost > 0 ? (totalGain / totalCost) * 100 : 0,
        totalsExcluded: holdings.length - valued.length,
        holdings: holdings.sort((a, b) => b.value - a.value),
        equityValue: backendSummary.equity_value,
        cashAssets: backendSummary.cash_assets_base,
        marginDebt: backendSummary.margin_debt_base,
        cash: sumCashByCurrency(backendSummary.cash),
        baseCurrency: backendSummary.base_currency,
        status: backendSummary.status,
        missingFx: backendSummary.missing_fx,
        valuationHold: backendSummary.valuation_hold ?? [],
        fxRates: backendSummary.fx_rates,
        cashAsOf: backendSummary.cash_as_of,
        positionsAsOf: backendSummary.data_as_of,
        valuationDatesDiffer: backendSummary.valuation_dates_differ,
        quality,
    };
}

export type CompanyHoldingContext =
    | { status: 'held'; holding: PortfolioHolding; weightPercent: number | null; positionsAsOf: string | null }
    | { status: 'not_held' }
    | { status: 'error'; message: string };

/**
 * La posición real de UNA empresa para su ficha, sacada de la MISMA lectura
 * que la página de cartera (getPortfolioSummary, caché compartida): las cifras
 * no pueden divergir entre pantallas. El peso usa la regla del donut
 * «Distribución»: solo posiciones con valor conocido. Un fallo se devuelve
 * como error visible, nunca como «sin posición». La fecha es la de esta
 * posición: la del resumen es la más antigua de toda la cartera.
 */
export async function getCompanyHolding(ticker: string): Promise<CompanyHoldingContext> {
    const user = await requireAuthenticatedUser();
    try {
        const summary = await getPortfolioSummary(user.id);
        const symbol = ticker.trim().toUpperCase();
        const holding = summary.holdings.find((item) => item.symbol.toUpperCase() === symbol);
        if (!holding) return { status: 'not_held' };
        // Misma regla que el donut de cartera: el coste pendiente de
        // conciliación no excluye del peso; la valoración suspendida sí.
        const known = summary.holdings.filter((item) => !item.valueMissing && !item.valuationHold);
        const slice = known.includes(holding)
            ? buildAllocationSlices(known).find((item) => item.symbol === holding.symbol)
            : undefined;
        return { status: 'held', holding, weightPercent: slice?.percentage ?? null, positionsAsOf: holding.asOf ?? summary.positionsAsOf ?? null };
    } catch (error) {
        if (error instanceof AppError && [401, 403].includes(error.statusCode)) throw error;
        return { status: 'error', message: 'No se pudo cargar tu posición en esta empresa.' };
    }
}

// Actualizar transacción existente
export async function updateTransaction(
    userId: string,
    transactionId: string,
    symbol: string,
    type: 'buy' | 'sell',
    quantity: number,
    price: number,
    date: Date,
    notes?: string,
    currency = 'USD',
    fees?: number,
): Promise<{ success: boolean; error?: string }> {
    const canonicalUserId = await resolveUserId(userId);
    if (!Number.isFinite(quantity) || quantity <= 0 || !Number.isFinite(price) || price < 0) {
        throw new ValidationError('La cantidad debe ser positiva y el precio no puede ser negativo.');
    }
    if (fees !== undefined && (!Number.isFinite(fees) || fees < 0)) {
        throw new ValidationError('Las comisiones no pueden ser negativas.');
    }
    try {
        await researchRequest<ResearchPortfolioTransaction>(
            `/api/portfolio/transactions/${encodeURIComponent(transactionId)}`,
            {
                method: 'PUT',
                body: jsonBody({
                    ticker: symbol.toUpperCase(),
                    action: type,
                    quantity,
                    price,
                    trade_date: date.toISOString().slice(0, 10),
                    notes: notes || null,
                    currency: currency.toUpperCase(),
                    // Omitido = el backend conserva la comisión registrada.
                    ...(fees !== undefined ? { fees } : {}),
                }),
            },
        );
    } catch (error) {
        const rejection = ledgerRejection(error);
        if (rejection) return { success: false, error: rejection };
        throw error;
    }
    invalidatePortfolioReads(canonicalUserId);
    return { success: true };
}

export async function deleteTransaction(userId: string, transactionId: string): Promise<{ success: boolean; error?: string }> {
    const canonicalUserId = await resolveUserId(userId);
    try {
        await researchRequest<void>(`/api/portfolio/transactions/${encodeURIComponent(transactionId)}`, {
            method: 'DELETE',
        });
    } catch (error) {
        // Borrar una compra que respalda una venta posterior → 409 del ledger.
        const rejection = ledgerRejection(error, 'delete');
        if (rejection) return { success: false, error: rejection };
        throw error;
    }
    invalidatePortfolioReads(canonicalUserId);
    return { success: true };
}

// Eliminar todas las transacciones de un símbolo (eliminar posición)
export async function deleteHolding(userId: string, symbol: string): Promise<{ success: boolean; error?: string }> {
    const canonicalUserId = await resolveUserId(userId);
    await researchRequest<void>(`/api/portfolio/holdings/${encodeURIComponent(symbol.toUpperCase())}`, {
        method: 'DELETE',
    });
    invalidatePortfolioReads(canonicalUserId);
    return { success: true };
}

// ============================================
// Funciones adicionales para Portfolio
// ============================================

export type PortfolioAnalyticsResult = {
    cagr: number | null;
    volatility_ann: number | null;
    max_drawdown: number | null;
    sharpe: number | null;
    sortino: number | null;
    var_95: number | null;
    cvar_95: number | null;
    win_rate: number | null;
    calmar: number | null;
    // null cuando la métrica que alimenta la banda no existe (sin historial,
    // sin cobertura). Un 0 es una medición; null es su ausencia.
    score_quality: number | null;
    score_growth: number | null;
    score_value: number | null;
    score_cagr3y: number | null;
    trading_days: number;
    start_date: string;
    end_date: string;
    alpha?: number | null;
    beta?: number | null;
    information_ratio?: number | null;
};

export type PortfolioPerformanceHistory = {
    dates: string[];
    nav: number[];
    daily_returns: number[];
    twr: number;
    start_date: string;
    end_date: string;
    /** Fecha de la base nueva tras una reconstrucción del TWR (la serie se reinicia ahí); null si no hay corte. */
    rebuild_reset_date?: string | null;
};

/**
 * Portfolio factor scores, 0-100.
 *
 * `null` means "not computable from what we have", and it is NOT the same as 0:
 * a 0 is a real measurement (a portfolio with no growth has 0 growth), while
 * null is the absence of the metric the score would come from. The distinction
 * used to be erased here: every missing tearsheet metric, a portfolio with no
 * holdings and a failed backend request all produced five zeros, so a backend
 * hiccup was displayed as "your portfolio scores 0/100" and a portfolio with no
 * history looked identical to a portfolio with terrible history.
 */
export type PortfolioScores = {
    quality: number | null;
    growth: number | null;
    value: number | null;
    dividend: number | null;
    cagr3y: number | null;
    analytics?: PortfolioAnalyticsResult;
    history?: PortfolioPerformanceHistory;
};

const NO_PORTFOLIO_SCORES = {
    quality: null,
    growth: null,
    value: null,
    dividend: null,
    cagr3y: null,
} as const satisfies Omit<PortfolioScores, 'analytics' | 'history'>;

// Obtener métricas reales del portfolio via quantstats-pro
export async function getPortfolioScores(userId: string): Promise<PortfolioScores> {
    const canonicalUserId = await resolveUserId(userId);

    try {
        const summary = await getPortfolioSummary(canonicalUserId);
        if (summary.holdings.length === 0) return { ...NO_PORTFOLIO_SCORES };

        // Scores 0-100 derivados de métricas reales del tearsheet
        // (GET /api/portfolio/tearsheet): bandas documentadas, sin inventos.
        // quality = consistencia (Sharpe/win_rate), growth = acumulado,
        // value = resiliencia (drawdown). Cada banda devuelve null cuando la
        // métrica que la alimenta no existe: un 0 seria una medición.
        const clamp100 = (v: number) => Math.max(0, Math.min(100, Math.round(v)));
        const sheet = await getPortfolioTearsheet(canonicalUserId);
        const rawSnapshots = await cachedFetch(
            `portfolio:${canonicalUserId}:snapshots`,
            () => fetchAllBackendPages(
                (page) => researchRequest<PaginatedBackendResponse<PortfolioSnapshotPoint>>(`/api/portfolio/snapshots?page=${page}&page_size=${BACKEND_PAGE_SIZE}`, { fast: true }),
                (snapshot) => snapshot.snapshot_date,
            ),
            15,
        ).catch(() => [] as PortfolioSnapshotPoint[]);
        const snapshots = rawSnapshots;
        const history = verifiedPortfolioHistory(snapshots, summary.baseCurrency);
        // Real dividend score: trailing-12M declared-dividend yield from
        // GET /api/portfolio/dividends (FMP-ingested records, provenance
        // attached). Linear band documented here: 0% yield -> 0, 6% -> 100.
        // Sin posiciones con dividendos ingeridos la puntuación es null, no 0:
        // un yield de 0% es un hecho ("no reparte") y "no lo sabemos" no lo es.
        // portfolio_yield es el yield de las posiciones CUBIERTAS: con la
        // mitad del valor sin datos, puntuarlo como si fuera de toda la
        // cartera inflaría el score. Se pondera por covered_value_fraction:
        // el resultado es el límite inferior del yield del libro completo
        // (lo desconocido no suma). Sin el campo (backend viejo) el yield
        // ya venía diluido sobre el valor total: fracción 1 es consistente.
        let dividendScore: number | null = null;
        try {
            const dividends = await cachedFetch<PortfolioDividendYields>(
                `portfolio:${canonicalUserId}:dividends`,
                () => researchRequest<PortfolioDividendYields>('/api/portfolio/dividends', { fast: true }),
                30,
            );
            if (
                dividends.coverage.positions_with_dividend_data > 0 &&
                dividends.portfolio_yield != null
            ) {
                const coveredFraction = dividends.coverage.covered_value_fraction ?? 1;
                dividendScore = clamp100(((dividends.portfolio_yield * coveredFraction) / 0.06) * 100);
            }
        } catch {
            // Endpoint unavailable: the yield is unknown, not zero.
            dividendScore = null;
        }
        // The tearsheet filters null returns. Never let that bridge incomplete
        // snapshots or display metrics computed over another unqualified period.
        const m = qualifiedHistoricalMetrics(snapshots, history, sheet?.metrics ?? null);
        const sharpe = m?.sharpe ?? null;
        const winRate = m?.win_rate ?? null;
        const maxDD = m?.max_drawdown ?? null;
        const cumulative = m?.cumulative_return ?? null;
        const quality = sharpe == null ? null : clamp100(50 + sharpe * 25);
        const growth = cumulative == null ? null : clamp100(50 + cumulative * 200);
        const value = maxDD == null ? null : clamp100(100 + maxDD * 200);
        const consistency =
            quality == null
                ? null
                : winRate == null
                  ? quality
                  : clamp100(quality * 0.7 + winRate * 100 * 0.3);
        const data: PortfolioAnalyticsResult = {
            cagr: null, // No annualised return is provided by this endpoint.
            volatility_ann: null,
            max_drawdown: maxDD,
            sharpe,
            sortino: m?.sortino ?? null,
            var_95: null,
            cvar_95: null,
            win_rate: winRate,
            calmar: null,
            score_quality: consistency,
            score_growth: growth,
            score_value: value,
            score_cagr3y: null,
            trading_days: m?.periods_per_year ?? 252,
            start_date: '',
            end_date: '',
        };

        return {
            quality: data.score_quality ?? null,
            growth: data.score_growth ?? null,
            value: data.score_value ?? null,
            dividend: dividendScore,
            // Legacy transport key, not a 3Y CAGR. UI explicitly says cumulative.
            cagr3y: cumulative != null ? Math.round(cumulative * 10000) / 100 : null,
            analytics: data,
            history,
        };
    } catch (error) {
        console.error('Error getting portfolio scores:', error);
        return { ...NO_PORTFOLIO_SCORES };
    }
}

// Añadir posición rápida desde buscador
export async function quickAddPosition(
    userId: string,
    symbol: string,
    shares: number,
    price: number
): Promise<{ success: boolean; error?: string }> {
    await resolveUserId(userId);
    return addTransaction(userId, symbol, 'buy', shares, price, new Date());
}

// Obtener holdings con peso de portfolio
/**
 * Resultado de `refreshPortfolioHoldings`: lo que SE ESCRIBIÓ, no lo que se
 * pidió. Antes la acción devolvía el array de entrada con la forma del éxito
 * ante cualquier fallo y el componente pintaba «Precios actualizados» verde sin
 * haber escrito nada (con FINNHUB_API_KEY sin configurar no se escribía ni una
 * sola fila, porque `getQuote` devolvía null y el bucle hacía `return`).
 */
export type PortfolioPriceRefreshResult =
    | {
        /** Algún precio llegó al backend. `holdings` viene releído del servidor. */
        ok: true;
        /** Símbolos cuyo precio se escribió. */
        updated: string[];
        /** Símbolos sin cotización del proveedor (sin clave, error o respuesta vacía). */
        skipped: string[];
        /** Símbolos cuya ESCRITURA falló (red/5xx): ni escritos ni sin cotización. */
        failed: string[];
        holdings: PortfolioHolding[];
        /**
         * true = la relectura tras escribir falló: los precios SÍ se grabaron
         * pero `holdings` no refleja la escritura. Distinto de un fallo de
         * escritura: aquí el dato está en el servidor.
         */
        holdingsStale?: boolean;
    }
    | {
        /** No se escribió ningún precio: no hay nada que actualizar. */
        ok: false;
        updated: [];
        /** Símbolos sin cotización utilizable. */
        skipped: string[];
        /** Símbolos cuya escritura se intentó y falló. */
        failed: string[];
    };

/**
 * Actualiza los precios de las posiciones existentes contra el proveedor de
 * cotizaciones (PATCH /api/portfolio/prices) y relee el resumen.
 *
 * Los errores del backend YA NO se tragan: un 5xx o un fallo de red suben al
 * `showErrorToast` del componente en vez de devolver las posiciones intactas con
 * la apariencia del éxito.
 */
export async function refreshPortfolioHoldings(holdings: PortfolioHolding[]): Promise<PortfolioPriceRefreshResult> {
    const user = await requireAuthenticatedUser();
    const symbols = holdings.map((holding) => holding.symbol);
    if (symbols.length === 0) {
        // Cartera vacía: no es un error. Antes se lanzaba ValidationError y en
        // producción Next oculta el mensaje de los errores de server action,
        // así que el usuario nuevo veía «El motor de análisis no responde».
        return { ok: true, updated: [], skipped: [], failed: [], holdings: [] };
    }

    // allSettled, no Promise.all: con all, si A se guardaba y B fallaba, la
    // promesa rechazaba ANTES de invalidar la caché - la escritura de A ya
    // estaba en el servidor pero la UI seguía sirviendo la caché vieja y el
    // usuario veía el error sin saber que algo sí se escribió.
    const settled = await Promise.allSettled(
        symbols.map(async (symbol) => {
            const quote = await getQuote(symbol);
            if (!quote?.c) return { symbol, written: false };
            await researchRequest('/api/portfolio/prices', {
                method: 'PATCH',
                body: jsonBody({ ticker: symbol, price: quote.c }),
            });
            return { symbol, written: true };
        }),
    );
    const { updated, skipped, failed } = partitionSettledRefreshes(symbols, settled);

    if (updated.length === 0) {
        // Sin clave de proveedor, o con el proveedor caído, el bucle entero se
        // salta. Decirlo (ok: false) es lo único honesto: devolver las
        // posiciones de entrada hacía que el toast afirmara una actualización
        // que no ocurrió. Si hubo intentos de escritura fallidos, se declaran
        // aparte: no es lo mismo "sin cotización" que "no se pudo escribir".
        // Los simbolos vienen de las posiciones del cliente: argumentos
        // separados y acotados, nunca interpolados en la cadena de formato
        // (CodeQL js/format-string). El log no necesita la lista entera.
        console.error(
            'refreshPortfolioHoldings: precios escritos 0 de',
            skipped.length + failed.length,
            `(FINNHUB_API_KEY ${FINNHUB_API_KEY ? 'configurada' : 'sin configurar'})`,
            'sin cotizacion:',
            skipped.slice(0, 20),
            'escritura fallida:',
            failed.slice(0, 20),
        );
        return { ok: false, updated: [], skipped, failed };
    }

    // Con AL MENOS una escritura la caché queda obsoleta: invalidar SIEMPRE,
    // aunque otras escrituras hayan fallado.
    invalidatePortfolioReads(user.id);
    let refreshedHoldings: PortfolioHolding[];
    let holdingsStale = false;
    try {
        refreshedHoldings = (await getPortfolioSummary(user.id)).holdings;
    } catch (readError) {
        // Escritura OK + relectura KO no es un fallo de actualización: los
        // precios están grabados. Se declara la relectura fallida (con las
        // posiciones de entrada como último dato conocido) en vez de lanzar
        // un error que sugeriría que no se escribió nada.
        console.error('refreshPortfolioHoldings: escritura OK, relectura fallida:', readError);
        refreshedHoldings = holdings;
        holdingsStale = true;
    }
    return {
        ok: true,
        updated,
        skipped,
        failed,
        holdings: refreshedHoldings,
        holdingsStale,
    };
}

/**
 * «Actualizar todo»: invalida las lecturas cacheadas del usuario y las vuelve a
 * pedir al backend.
 *
 * NO fuerza cotizaciones nuevas. Los precios que devuelve el backend son los
 * últimos que grabó su propio pipeline; provocarlos es
 * `POST /api/portfolio/refresh-market`, que refresca el universo COMPLETO de
 * empresas del tenant (miles de símbolos, 6 en vuelo, 20 s por ticker) y tarda
 * minutos en una petición HTTP síncrona: cablearlo a un botón dejaría al
 * usuario mirando un spinner sin feedback y con el riesgo de que el proxy corte
 * la respuesta a los 15 s de `RESEARCH_TIMEOUTS.GLOBAL_MS`. Lo honesto aquí es
 * invalidar y releer, y decirlo.
 */
export async function updateAllPortfolioPrices(userId: string): Promise<{
    summary: PortfolioSummary;
    scores: PortfolioScores;
}> {
    const canonicalUserId = await resolveUserId(userId);
    // Sin esto, getPortfolioSummary/getPortfolioScores re-servían la caché de 15 s
    // y el botón pintaba exactamente los mismos números de siempre.
    invalidatePortfolioReads(canonicalUserId);
    const [summary, scores] = await Promise.all([
        getPortfolioSummary(canonicalUserId),
        getPortfolioScores(canonicalUserId),
    ]);

    return { summary, scores };
}

/**
 * Dispara la descarga del Flex statement de IBKR (via IBKR_FLEX_TOKEN /
 * IBKR_FLEX_QUERY_ID) y la importación en el research backend.
 */
export async function importFromIBKR(userId: string): Promise<IBKRDownloadImportResult | ImportRejection> {
    const canonicalUserId = await resolveUserId(userId);
    let result: IBKRDownloadImportResult;
    try {
        result = await researchRequest<IBKRDownloadImportResult>('/api/portfolio/import/ibkr', {
            method: 'POST',
        });
    } catch (error) {
        const rejected = importRejection(error);
        if (rejected) return rejected;
        throw error;
    }
    invalidatePortfolioReads(canonicalUserId);
    return result;
}

/**
 * Importa un Flex XML crudo (por si el usuario lo descarga a mano).
 */
export async function importIBKRXml(userId: string, xml: string): Promise<IBKRXmlImportResult | ImportRejection> {
    const canonicalUserId = await resolveUserId(userId);
    let result: IBKRXmlImportResult;
    try {
        result = await researchRequest<IBKRXmlImportResult>('/api/portfolio/import/ibkr/xml', {
            method: 'POST',
            body: jsonBody({ xml }),
        });
    } catch (error) {
        const rejected = importRejection(error);
        if (rejected) return rejected;
        throw error;
    }
    invalidatePortfolioReads(canonicalUserId);
    return result;
}

/**
 * Importa un CSV de actividad de IBKR (symbol, quantity, price, date + action/fees/currency opcionales).
 */
export async function importIBKRCsv(userId: string, csv: string): Promise<IBKRCsvImportResult | ImportRejection> {
    const canonicalUserId = await resolveUserId(userId);
    let result: IBKRCsvImportResult;
    try {
        result = await researchRequest<IBKRCsvImportResult>('/api/portfolio/import/ibkr/csv', {
            method: 'POST',
            body: jsonBody({ csv }),
        });
    } catch (error) {
        const rejected = importRejection(error);
        if (rejected) return rejected;
        throw error;
    }
    invalidatePortfolioReads(canonicalUserId);
    return result;
}

// Tipos generados desde el OpenAPI del backend (response_model en la ruta);
// regenerar con `npx openapi-typescript data-engine/openapi.json`.
// El CSV de IBKR tiene su propio contrato en el backend (no devuelve
// positions_imported ni portfolio_snapshot_id: esos son del Flex XML).
export type IBKRCsvImportResult = components['schemas']['PortfolioIbkrCsvImportOut'];
// /import/ibkr devuelve el importado Flex o la variante not_configured
// (discriminado por status; response_model + exclude_unset en la ruta).
export type IBKRDownloadImportResult = components['schemas']['PortfolioIbkrImportOut'];

export type IBKRXmlImportResult = components['schemas']['PortfolioIbkrXmlImportOut'];

export type PortfolioTearsheetMetrics = components['schemas']['TearsheetMetricsOut'];

export type PortfolioTearsheet = components['schemas']['PortfolioTearsheetOut'];

/**
 * Tearsheet del portfolio (Sharpe, drawdown, win rate) desde los snapshots persistidos.
 * Degrada a null sin historial; nunca lanza por falta de datos.
 */
export async function getPortfolioTearsheet(userId: string): Promise<PortfolioTearsheet | null> {
    const canonicalUserId = await resolveUserId(userId);
    try {
        return await cachedFetch(
            `portfolio:${canonicalUserId}:tearsheet`,
            () => researchRequest<PortfolioTearsheet>('/api/portfolio/tearsheet', { fast: true }),
            15,
        );
    } catch (error) {
        console.error('Error getting portfolio tearsheet:', error);
        return null;
    }
}

// Tipos + fetcher para lib/actions/portfolio.actions.ts

// Tipos generados desde el OpenAPI del backend (response_model en la ruta);
// regenerar con `npx openapi-typescript data-engine/openapi.json`. El tipo
// manuscrito no contemplaba reason_code "valuation_hold" ni intrinsic con
// escenarios null.
export type PortfolioForecastScenario = components['schemas']['ForecastScenarioOut'];

export type PortfolioForecastCoveredScenario = components['schemas']['ForecastCoveredScenarioOut'];

export type PortfolioForecastPosition = components['schemas']['ForecastPositionOut'];

export type PortfolioForecastExcluded = components['schemas']['ForecastExcludedOut'];

export type PortfolioForecast = components['schemas']['PortfolioForecastOut'];

export async function getPortfolioForecast(): Promise<PortfolioForecast> {
  // Sin cache: la prevision depende de la ultima sincronizacion IBKR y de
  // las versiones vigentes de tesis/modelos, que cambian con cada sync.
  return researchRequest<PortfolioForecast>('/api/portfolio/forecast', { fast: true });
}

// Proyección mecánica de dividendos (idea 5 del listado 0-31: mes a mes, con
// retención de origen e IRPF). Toda cifra viene del endpoint determinista
// /api/portfolio/dividends/projection; los null del backend se propagan como
// null (N/D en pantalla), nunca como 0. Tipos generados desde el OpenAPI del
// backend (response_model en las dos rutas); regenerar con
// `npx openapi-typescript data-engine/openapi.json`.

export type DividendProjectionMonth = components['schemas']['DividendProjectionMonthOut'];

export type DividendProjectionFiscalYear = components['schemas']['DividendProjectionFiscalYearOut'];

export type DividendProjectionPosition = components['schemas']['DividendProjectionPositionOut'];

export type DividendProjectionDeclaredFuture = components['schemas']['DividendProjectionDeclaredFutureOut'];

export type PortfolioDividendYields = components['schemas']['PortfolioDividendYieldsOut'];

export type PortfolioDividendProjection = components['schemas']['PortfolioDividendProjectionOut'];

export async function getPortfolioDividendProjection(): Promise<PortfolioDividendProjection> {
  // Sin cache: la proyección depende de la última sincronización IBKR y de
  // los dividendos ingeridos, que cambian con cada sync.
  return researchRequest<PortfolioDividendProjection>('/api/portfolio/dividends/projection', { fast: true });
}

export type PortfolioDataQuality = components['schemas']['PortfolioDataQualityOut'];

export async function getPortfolioDataQuality(userId: string): Promise<PortfolioDataQuality | null> {
    const canonicalUserId = await resolveUserId(userId);
    try {
        return await cachedFetch(`portfolio:${canonicalUserId}:quality`,
            () => researchRequest<PortfolioDataQuality>('/api/portfolio/data-quality', { fast: true }), 15);
    } catch { return null; }
}

/** Sincroniza los dividendos de las posiciones del tenant y relee las lecturas cacheadas. */
export async function syncPortfolioDividends(userId: string): Promise<void> {
    const canonicalUserId = await resolveUserId(userId);
    await researchRequest('/api/portfolio/dividends/sync', { method: 'POST' });
    invalidatePortfolioReads(canonicalUserId);
}
