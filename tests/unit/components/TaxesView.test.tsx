import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

const { push, refresh, regen, getReport, getHoldings, toastSuccess, showError } = vi.hoisted(() => ({
    push: vi.fn(), refresh: vi.fn(), regen: vi.fn(), getReport: vi.fn(), getHoldings: vi.fn(),
    toastSuccess: vi.fn(), showError: vi.fn(),
}));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, refresh }) }));
vi.mock('@/lib/actions/taxes.actions', () => ({
    regenerateTaxReport: regen, getTaxReport: getReport, getTaxHoldings: getHoldings, previewTaxFiling: vi.fn(),
}));
vi.mock('sonner', () => ({ toast: { success: toastSuccess } }));
vi.mock('@/lib/toast', () => ({ showErrorToast: showError }));
import TaxesView from '@/components/taxes/TaxesView';

const report = {
    summary: {
        fiscal_year: 2025, base_currency: 'EUR', total_dividends_base: 1234.5, total_realized_gain_base: null,
        method: 'fifo', over_sell: ['ABC'], missing_fx: ['USD'], unattributed_tickers: ['UNATTRIBUTED:XYZ'],
        wash_sale_rule: 'es-irpf-2m', manual_review: false,
    },
    generated_at: '2026-01-02T10:00:00Z',
};

function view(props: Partial<React.ComponentProps<typeof TaxesView>> = {}) {
    return render(<TaxesView initialHoldings={[]} initialReport={report} initialThresholds720={null}
        initialFile720={null} year={2025} {...props} />);
}

describe('TaxesView informe', () => {
    beforeEach(() => vi.clearAllMocks());

    it('importes null son N/D con la causa, no 0', () => {
        view();
        expect(screen.getByText(/N\/D \(ventas sin compras que las cubran: ABC y faltan tipos de cambio\)/)).toBeInTheDocument();
    });

    it('formatea dividendos en EUR y el metodo FIFO, y humaniza tickers sin atribuir', () => {
        view();
        expect(document.body.textContent).toMatch(/1\.?234,50/);
        expect(screen.getByText('FIFO')).toBeInTheDocument();
        expect(screen.getByText('Sin atribuir: XYZ')).toBeInTheDocument();
        expect(screen.getByText('IRPF español: no recomprar en 2 meses')).toBeInTheDocument();
    });

    it('el criterio FX de valores se etiqueta y traduce (no id en crudo)', () => {
        view({
            initialReport: {
                summary: { fiscal_year: 2025, base_currency: 'EUR', securities_fx_criterion: 'dgt_native_gain_sale_date_v1' },
                generated_at: '2026-01-02T10:00:00Z',
            },
        });
        expect(screen.getByText('Criterio FX en valores')).toBeInTheDocument();
        expect(screen.getByText(/Ganancia en divisa del valor, convertida a EUR al cambio de la fecha de venta/)).toBeInTheDocument();
        expect(document.body.textContent).not.toContain('dgt_native_gain_sale_date_v1');
    });

    it('un criterio FX desconocido cae al valor crudo sin romper la vista', () => {
        view({
            initialReport: {
                summary: { fiscal_year: 2025, base_currency: 'EUR', securities_fx_criterion: 'criterio_futuro_v2' },
                generated_at: '2026-01-02T10:00:00Z',
            },
        });
        expect(screen.getByText('Criterio FX en valores')).toBeInTheDocument();
        expect(screen.getByText('criterio_futuro_v2')).toBeInTheDocument();
    });

    it('sin informe muestra el mensaje vacio', () => {
        view({ initialReport: null });
        expect(screen.queryByText('FIFO')).not.toBeInTheDocument();
        expect(screen.queryByText(/Dividendos brutos/)).not.toBeInTheDocument();
    });

    it('cambiar el ejercicio navega al ano pedido; valor no entero se ignora', () => {
        view();
        const select = screen.getByLabelText(/ejercicio|año/i) as HTMLSelectElement;
        const option = Array.from(select.options).find((o) => o.value !== '2025')!;
        fireEvent.change(select, { target: { value: option.value } });
        expect(push).toHaveBeenCalledWith(`/taxes?year=${option.value}`);
    });

    it('regenerar recarga el informe fresco y avisa', async () => {
        regen.mockResolvedValue({});
        getReport.mockResolvedValue({ summary: { fiscal_year: 2025, total_dividends_base: 999, base_currency: 'EUR' } });
        view();
        fireEvent.click(screen.getByRole('button', { name: /regenerar/i }));
        await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith('Informe fiscal 2025 regenerado'));
        expect(regen).toHaveBeenCalledWith(2025);
        expect(document.body.textContent).toMatch(/999,00/);
    });

    it('regenerar sin informe fresco hace router.refresh', async () => {
        regen.mockResolvedValue({});
        getReport.mockRejectedValue(new Error('x'));
        view();
        fireEvent.click(screen.getByRole('button', { name: /regenerar/i }));
        await waitFor(() => expect(refresh).toHaveBeenCalled());
    });

    it('regenerar con error muestra toast de error y no de exito', async () => {
        regen.mockRejectedValue(new Error('fallo'));
        view();
        fireEvent.click(screen.getByRole('button', { name: /regenerar/i }));
        await waitFor(() => expect(showError).toHaveBeenCalled());
        expect(toastSuccess).not.toHaveBeenCalled();
    });
});

describe('TaxesView posiciones y exportacion', () => {
    beforeEach(() => vi.clearAllMocks());
    const holdings = Array.from({ length: 12 }, (_, i) => ({
        ticker: `T${String(i).padStart(2, '0')}`, quantity: 6.0572, cost_basis: 100, market_value: 120, unrealized_pnl: 20, currency: 'USD',
    }));

    it('pagina de 10 en 10', () => {
        view({ initialHoldings: holdings });
        expect(screen.getByText(/1 \/ 2 · 12 posiciones/)).toBeInTheDocument();
        expect(screen.getAllByText('T00').length).toBeGreaterThan(0);
        expect(screen.queryAllByText('T11')).toHaveLength(0);
        fireEvent.click(screen.getByRole('button', { name: 'Siguiente' }));
        expect(screen.getAllByText('T11').length).toBeGreaterThan(0);
        expect(screen.getByText(/2 \/ 2/)).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Anterior' }));
        expect(screen.getAllByText('T00').length).toBeGreaterThan(0);
    });

    it('cantidades fraccionadas con coma espanola', () => {
        view({ initialHoldings: holdings.slice(0, 1) });
        expect(screen.getAllByText('6,0572').length).toBeGreaterThan(0);
        expect(screen.queryAllByText('6.0572')).toHaveLength(0);
    });

    it('sin posiciones ni informe el boton exportar esta desactivado', () => {
        view({ initialReport: null });
        expect(screen.getByRole('button', { name: /Exportar resumen/ })).toBeDisabled();
    });

    it('el CSV exportado neutraliza formulas y duplica comillas', async () => {
        let blob: Blob | null = null;
        (URL as any).createObjectURL = vi.fn((b: Blob) => { blob = b; return 'blob:x'; });
        (URL as any).revokeObjectURL = vi.fn();
        vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
        view({ initialHoldings: [{ ticker: '=HYPERLINK("x")', cost_basis: -10, currency: 'EUR' }] });
        fireEvent.click(screen.getByRole('button', { name: /Exportar resumen/ }));
        const text = await new Promise<string>((res) => { const r = new FileReader(); r.onload = () => res(r.result as string); r.readAsText(blob!); });
        expect(text.startsWith('informe_fiscal,2025')).toBe(true);
        expect(text).toContain(`"'=HYPERLINK(""x"")"`);
        expect(text).toContain('"-10"');
        expect(text).not.toContain(`"'-10"`);
        expect(toastSuccess).toHaveBeenCalledWith('Resumen fiscal 2025 exportado');
    });
});
