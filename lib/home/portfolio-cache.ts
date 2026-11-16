import type { PortfolioSummary } from '@/lib/actions/portfolio.actions';

export type CachedPortfolio = { summary: PortfolioSummary; fetchedAt: string };

const keyFor = (userId: string) => `gerarai:home-portfolio:${userId}`;

export function readCachedPortfolio(userId: string): CachedPortfolio | null {
    try {
        const raw = window.localStorage.getItem(keyFor(userId));
        if (!raw) return null;
        const parsed = JSON.parse(raw) as CachedPortfolio;
        // Forma mínima exigible: sin objeto de resumen ni fecha, no se usa.
        if (!parsed || typeof parsed !== 'object' || !parsed.summary || typeof parsed.fetchedAt !== 'string') return null;
        if (!Number.isFinite(Date.parse(parsed.fetchedAt))) return null;
        const finite = (value: unknown) => typeof value === 'number' && Number.isFinite(value);
        const summary = parsed.summary;
        if (![summary.totalValue, summary.totalCost, summary.totalGain, summary.totalGainPercent,
            summary.equityValue, summary.cash].every(finite) || !Array.isArray(summary.holdings)) return null;
        for (const holding of summary.holdings) {
            if (!holding || typeof holding !== 'object' || typeof holding.symbol !== 'string' || !holding.symbol.trim()) return null;
            if (![holding.quantity, holding.avgPrice, holding.value, holding.cost, holding.gain, holding.gainPercent].every(finite)) return null;
            if (holding.currentPrice !== null && !finite(holding.currentPrice)) return null;
            if (typeof holding.nativeCurrency !== 'string' || typeof holding.baseCurrency !== 'string') return null;
            if (typeof holding.fxMissing !== 'boolean' || typeof holding.valueMissing !== 'boolean') return null;
        }
        return parsed;
    } catch {
        // localStorage lleno/corrupto o modo privado: sin caché, fetch normal.
        return null;
    }
}

export function writeCachedPortfolio(userId: string, summary: PortfolioSummary): void {
    try {
        const entry: CachedPortfolio = { summary, fetchedAt: new Date().toISOString() };
        window.localStorage.setItem(keyFor(userId), JSON.stringify(entry));
    } catch {
        // Sin espacio o sin storage: no pasa nada, la próxima carga irá a red.
    }
}
