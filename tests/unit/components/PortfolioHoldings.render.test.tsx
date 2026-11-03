import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';

// Rendimiento de «Posiciones»: cada posición es un componente memoizado.
// Abrir/cancelar «Eliminar» o reordenar no debe volver a pintar las filas
// (antes, con 300 posiciones, cada una de esas acciones repintaba 600
// filas/tarjetas: ~300 ms por clic en el banco).
const h = vi.hoisted(() => ({ logo: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock('@/lib/actions/portfolio.actions', () => ({ deleteHolding: vi.fn(), refreshPortfolioHoldings: vi.fn() }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));
vi.mock('@/lib/toast', () => ({ showErrorToast: vi.fn() }));
vi.mock('@/components/calendar/CompanyLogo', () => ({ CompanyLogo: ({ ticker }: { ticker: string }) => { h.logo(ticker); return null; } }));
vi.mock('@/components/common/TrackedAnalysisStatus', () => ({ TrackedAnalysisStatus: () => null }));
vi.mock('@/components/common/ExtendedHoursLine', () => ({ default: () => null }));
vi.mock('@/components/common/AnalystTargetLine', () => ({ default: () => null }));
vi.mock('@/components/portfolio/HoldingSignals', () => ({
    DcaLevelChip: () => null, FairValueLine: () => null, useHoldingSignals: () => null,
}));
vi.mock('@/components/portfolio/ImportIBKRButton', () => ({ default: () => null }));
vi.mock('@/components/portfolio/ImportImageButton', () => ({ default: () => null }));
vi.mock('@/components/portfolio/AddTransactionButton', () => ({ default: () => null }));
import PortfolioHoldings from '@/components/portfolio/PortfolioHoldings';

const holdings = Array.from({ length: 12 }, (_, i) => ({
    symbol: `S${String(i).padStart(2, '0')}`, quantity: 10, avgPrice: 100, currentPrice: 100 + i * 10, valuationHold: null,
    value: 1000 + i * 100, cost: 1000, gain: i * 100, gainPercent: i * 10, nativeCurrency: 'EUR', baseCurrency: 'EUR',
    fxMissing: false, nativeGain: null, nativeCost: null, valueMissing: false,
    firstBuyDate: '2024-01-15', holdingDays: 400, fiscalBucket: 'largo_plazo',
})) as any[];
const order = () => within(screen.getByRole('table')).getAllByRole('row').slice(1).map((row) => row.querySelector('td')?.textContent ?? '');

describe('Posiciones: render por fila', () => {
    it('abrir y cancelar «Eliminar» no repinta ninguna posición', () => {
        render(<PortfolioHoldings holdings={holdings} userId="u" />);
        // 12 tarjetas móviles + 12 filas de escritorio.
        expect(h.logo).toHaveBeenCalledTimes(24);
        h.logo.mockClear();
        fireEvent.click(screen.getAllByRole('button', { name: /S05/ })[0]);
        fireEvent.click(screen.getByRole('button', { name: 'Cancelar' }));
        expect(screen.queryByRole('button', { name: 'Cancelar' })).not.toBeInTheDocument();
        expect(h.logo).not.toHaveBeenCalled();
    });

    it('reordenar cambia el orden sin repintar las filas', () => {
        render(<PortfolioHoldings holdings={holdings} userId="u" />);
        expect(order()[0]).toContain('S11');
        h.logo.mockClear();
        fireEvent.change(screen.getByRole('combobox'), { target: { value: 'symbol' } });
        expect(order()[0]).toContain('S00');
        expect(order()[11]).toContain('S11');
        expect(h.logo).not.toHaveBeenCalled();
    });
});
