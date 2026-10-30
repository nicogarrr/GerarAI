import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }) }));
vi.mock('@/lib/actions/taxes.actions', () => ({
    regenerateTaxReport: vi.fn(), getTaxReport: vi.fn(), getTaxHoldings: vi.fn(), previewTaxFiling: vi.fn(),
}));
vi.mock('sonner', () => ({ toast: { success: vi.fn() } }));
vi.mock('@/lib/toast', () => ({ showErrorToast: vi.fn() }));
import TaxesView from '@/components/taxes/TaxesView';

/**
 * Usuario nuevo: el informe fiscal de un ejercicio sin operaciones salía como
 * un informe completo a cero, sin decir por qué ni qué hacer. Ahora lo explica
 * y ofrece registrar operaciones o conectar IBKR.
 */
const emptyReport = {
    summary: { fiscal_year: 2026, base_currency: 'EUR', total_dividends_base: 0, total_realized_gain_base: 0, dividend_count: 0 },
    dividends: [], realized: [], misc: [],
    generated_at: '2026-10-30T02:00:00Z',
};

function view(report: Record<string, unknown>, holdings: Record<string, unknown>[] = []) {
    return render(<TaxesView initialHoldings={holdings} initialReport={report} initialThresholds720={null}
        initialFile720={null} year={2026} />);
}

describe('TaxesView: ejercicio sin actividad', () => {
    it('explica el informe a cero y ofrece el siguiente paso', () => {
        view(emptyReport);
        expect(screen.getByTestId('empty-tax-year')).toHaveTextContent('Aún no hay compras, ventas ni dividendos en 2026');
        expect(screen.getByRole('link', { name: 'Añadir inversión' })).toHaveAttribute('href', '/portfolio?anadir=1');
        expect(screen.getByRole('link', { name: 'Conectar IBKR' })).toHaveAttribute('href', '/settings');
    });

    it('con dividendos, ventas o posiciones no muestra el aviso', () => {
        const { unmount } = view({ ...emptyReport, dividends: [{ ticker: 'KO', amount: 10 }] });
        expect(screen.queryByTestId('empty-tax-year')).not.toBeInTheDocument();
        unmount();
        view(emptyReport, [{ ticker: 'KO', quantity: 1 }]);
        expect(screen.queryByTestId('empty-tax-year')).not.toBeInTheDocument();
    });

    it('un informe sin listas (formato antiguo) no se da por vacío', () => {
        view({ summary: emptyReport.summary, generated_at: emptyReport.generated_at });
        expect(screen.queryByTestId('empty-tax-year')).not.toBeInTheDocument();
    });
});
