'use server';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { getResearchCompanyBasics } from '@/lib/actions/market-workspace.actions';
import { getCandles } from '@/lib/actions/finnhub.actions';
import { quoteSymbolFor } from '@/lib/market/quote-symbol';
import { chartRequestWindow, intradayWindow, isChartRange } from '@/lib/market/chart-ranges';
import { e2eMarketFixture, isE2EMarketFixtureEnabled } from '@/lib/e2e-market-fixture';
import { normalizeChartCandles, type CompanyChartBar } from '@/lib/market/normalize-chart';
export type { CompanyChartBar } from '@/lib/market/normalize-chart';
export type CompanyChartHistory = { bars: CompanyChartBar[]; source: string | null; resolution: 'D' | '60'; currency: string | null };

export async function getCompanyChartHistory(ticker: string, range: string): Promise<CompanyChartHistory> {
    await requireAuthenticatedUser();
    if (!isChartRange(range) || !/^[A-Z0-9.^-]{1,24}$/.test(ticker)) throw new Error('Rango o empresa no válido');
    if (isE2EMarketFixtureEnabled(process.env, ticker)) {
        const seed = e2eMarketFixture(ticker);
        if (range === '1D' || range === '5D') {
            const bars = Array.from({ length: 35 }, (_, i) => ({ date: new Date(Date.UTC(2026, 8, 5 + Math.floor(i / 7))).toISOString().slice(0, 10), timestamp: Date.UTC(2026, 8, 5 + Math.floor(i / 7), 13 + i % 7) / 1000, open: 330 + i, high: 333 + i, low: 329 + i, close: 331 + i, volume: 1000 + i }));
            return { bars: intradayWindow(bars, range), source: 'Fixture local', resolution: '60', currency: seed.currency };
        }
        return { bars: seed.history, source: 'Fixture local', resolution: 'D', currency: seed.currency };
    }
    const window = chartRequestWindow(range, Date.now() / 1000);
    const empty: CompanyChartHistory = { bars: [], source: null, resolution: window.resolution, currency: null };
    const company = await getResearchCompanyBasics(ticker);
    const symbol = quoteSymbolFor(company, ticker);
    if (!symbol) return empty; // Never read a same-ticker listing from the wrong exchange.
    const candles = await getCandles(symbol, window.from, window.to, window.resolution, 900);
    if (candles.s !== 'ok') return empty;
    const bars = normalizeChartCandles(candles, window);
    return { bars: range === '1D' || range === '5D' ? intradayWindow(bars, range) : bars, source: candles.source ?? null, resolution: window.resolution, currency: candles.currency ?? null };
}
