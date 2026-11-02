import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { LocaleProvider } from '@/lib/i18n/client';

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
        fiscal_year: 2025, base_currency: 'EUR', total_dividends_base: 0, total_realized_gain_base: 0,
        method: 'fifo', manual_review: false,
        zero_cost_buys: [{ ticker: 'SPIN', date: '2025-03-01', quantity: 5, label: 'Coste 0 (regalo / spin-off): revisar' }],
    },
    generated_at: '2026-01-02T10:00:00Z',
};

describe('TaxesView compras a coste 0', () => {
    beforeEach(() => vi.clearAllMocks());

    it('lista la compra a precio 0 con la etiqueta de revisión', () => {
        render(<TaxesView initialHoldings={[]} initialReport={report} initialThresholds720={null}
            initialFile720={null} year={2025} />);
        expect(screen.getByText('Compras a coste 0')).toBeInTheDocument();
        expect(document.body.textContent).toContain('SPIN 2025-03-01 · Coste 0 (regalo / spin-off): revisar');
    });

    // Con English, la etiqueta que manda el backend («Coste 0 … revisar») y el
    // aviso orientativo del informe seguían en castellano dentro del resumen.
    it('en inglés la etiqueta y el aviso del resumen salen en inglés', () => {
        const en = { ...report, summary: { ...report.summary, fiscal_disclaimer: 'Informe orientativo, no apto para declarar sin la validación de un asesor fiscal: wash-sale según procedimiento del Manual AEAT 2025 (art. 33.5.f LIRPF, proporcionalidad y FIFO); sin ISIN/cotización ni cobertura multibróker verificadas.' } };
        render(<LocaleProvider locale="en"><TaxesView initialHoldings={[]} initialReport={en} initialThresholds720={null}
            initialFile720={null} year={2025} /></LocaleProvider>);
        const text = document.body.textContent ?? '';
        expect(text).toContain('SPIN 2025-03-01 · Cost 0 (gift / spin-off): review');
        expect(text).toContain('Indicative report, not fit for filing');
        expect(text).not.toContain('revisar');
        expect(text).not.toContain('Informe orientativo');
    });
});
