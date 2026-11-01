import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';

const h = vi.hoisted(() => ({
    del: vi.fn(), refreshPrices: vi.fn(), routerRefresh: vi.fn(),
    success: vi.fn(), error: vi.fn(), info: vi.fn(), showError: vi.fn(),
}));
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: h.routerRefresh }) }));
vi.mock('@/lib/actions/portfolio.actions', () => ({ deleteHolding: h.del, refreshPortfolioHoldings: h.refreshPrices }));
vi.mock('sonner', () => ({ toast: { success: h.success, error: h.error, info: h.info } }));
vi.mock('@/lib/toast', () => ({ showErrorToast: h.showError }));
vi.mock('@/components/calendar/CompanyLogo', () => ({ CompanyLogo: () => null }));
vi.mock('@/components/common/TrackedAnalysisStatus', () => ({ TrackedAnalysisStatus: () => null }));
vi.mock('@/components/common/ExtendedHoursLine', () => ({ default: () => null }));
vi.mock('@/components/common/AnalystTargetLine', () => ({ default: () => null }));
vi.mock('@/components/portfolio/HoldingSignals', () => ({
    DcaLevelChip: () => null, FairValueLine: () => null, useHoldingSignals: () => null,
}));
vi.mock('@/components/portfolio/ImportIBKRButton', () => ({ default: () => <span>import-ibkr</span> }));
vi.mock('@/components/portfolio/ImportImageButton', () => ({ default: () => <span>import-image</span> }));
vi.mock('@/components/portfolio/AddTransactionButton', () => ({ default: () => <span>add-tx</span> }));
import PortfolioHoldings, { sortHoldings } from '@/components/portfolio/PortfolioHoldings';

function holding(over: Record<string, unknown> = {}) {
    return {
        symbol: 'AAPL', quantity: 10, avgPrice: 100, currentPrice: 120, valuationHold: null,
        value: 1200, cost: 1000, gain: 200, gainPercent: 20, nativeCurrency: 'EUR', baseCurrency: 'EUR',
        fxMissing: false, nativeGain: null, nativeCost: null, valueMissing: false,
        firstBuyDate: '2024-01-15', holdingDays: 400, fiscalBucket: 'largo_plazo', ...over,
    } as any;
}
const desktop = () => within(screen.getByRole('table'));

const order = () => desktop().getAllByRole('row').slice(1).map((row) => row.querySelector('td')?.textContent ?? '');
const rows = [
    holding({ symbol: 'BIG', value: 5000, gainPercent: 5 }),
    holding({ symbol: 'LOSER', value: 800, gainPercent: -30 }),
    holding({ symbol: 'WINNER', value: 1200, gainPercent: 80 }),
    holding({ symbol: 'NOFX', value: 0, gainPercent: 0, fxMissing: true }),
];

describe('Posiciones: ordenar', () => {
    it('por defecto mayor valor; sin valor conocido al final', () => {
        render(<PortfolioHoldings holdings={rows} userId="u" />);
        const symbols = order();
        expect(symbols.findIndex((s) => s.includes('BIG'))).toBeLessThan(symbols.findIndex((s) => s.includes('WINNER')));
        expect(symbols[symbols.length - 1]).toContain('NOFX');
    });

    it('peor rentabilidad primero al elegirlo (móvil y escritorio comparten orden)', () => {
        render(<PortfolioHoldings holdings={rows} userId="u" />);
        fireEvent.change(screen.getByLabelText('Ordenar por'), { target: { value: 'worst' } });
        const symbols = order();
        expect(symbols[0]).toContain('LOSER');
        expect(symbols[symbols.length - 1]).toContain('NOFX');
    });

    it('una G/P desconocida no se cuenta como 0 %', () => {
        expect(sortHoldings(rows, 'best').map((h) => h.symbol)).toEqual(['WINNER', 'BIG', 'LOSER', 'NOFX']);
        expect(sortHoldings(rows, 'symbol').map((h) => h.symbol)).toEqual(['BIG', 'LOSER', 'NOFX', 'WINNER']);
    });

    it('con una sola posición no hay selector', () => {
        render(<PortfolioHoldings holdings={[holding()]} userId="u" />);
        expect(screen.queryByLabelText('Ordenar por')).not.toBeInTheDocument();
    });
});

describe('sortHoldings: G/P desconocida va al final, no como 0 %', () => {
    it('sin coste (G/P N/D en la fila) no se mezcla con las reales', () => {
        const list = [
            holding({ symbol: 'UP', gainPercent: 10 }),
            holding({ symbol: 'NOCOST', cost: 0, gain: 0, gainPercent: 0, avgPrice: 0 }),
            holding({ symbol: 'DOWN', gainPercent: -10 }),
            holding({ symbol: 'NOQUOTE', quoteMissing: true, gainPercent: 0 }),
        ];
        expect(sortHoldings(list, 'best').map((x) => x.symbol)).toEqual(['UP', 'DOWN', 'NOCOST', 'NOQUOTE']);
        expect(sortHoldings(list, 'worst').map((x) => x.symbol)).toEqual(['DOWN', 'UP', 'NOCOST', 'NOQUOTE']);
    });
});
