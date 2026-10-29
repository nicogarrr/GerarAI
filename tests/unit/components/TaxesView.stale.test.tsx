import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

const { push, refresh, regen, getReport, toastSuccess } = vi.hoisted(() => ({
    push: vi.fn(), refresh: vi.fn(), regen: vi.fn(), getReport: vi.fn(), toastSuccess: vi.fn(),
}));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, refresh }) }));
vi.mock('@/lib/actions/taxes.actions', () => ({
    regenerateTaxReport: regen, getTaxReport: getReport, getTaxHoldings: vi.fn(), previewTaxFiling: vi.fn(),
}));
vi.mock('sonner', () => ({ toast: { success: toastSuccess } }));
vi.mock('@/lib/toast', () => ({ showErrorToast: vi.fn() }));
import TaxesView from '@/components/taxes/TaxesView';

const CURRENT = 'dgt_native_gain_sale_date_v1';
const summary = { fiscal_year: 2025, base_currency: 'EUR', total_dividends_base: 10 };
const staleReport = (reason: string, stored: string | null) => ({
    summary, generated_at: '2026-01-02T10:00:00Z', persisted: true,
    versioning: {
        persisted: true, stale: true, regenerate_recommended: true,
        outdated: [{ marker: 'securities_fx_criterion', stored, current: CURRENT, reason }],
    },
});
const freshReport = {
    summary: { ...summary, securities_fx_criterion: CURRENT }, generated_at: '2026-10-28T10:00:00Z', persisted: true,
    versioning: { persisted: true, stale: false, regenerate_recommended: false, outdated: [] },
};

function view(initialReport: Record<string, unknown> | null) {
    return render(<TaxesView initialHoldings={[]} initialReport={initialReport} initialThresholds720={null}
        initialFile720={null} year={2025} />);
}

describe('TaxesView aviso de informe desactualizado', () => {
    beforeEach(() => vi.clearAllMocks());

    it('informe sin criterio registrado: avisa de que no está al día', () => {
        view(staleReport('criterio_no_registrado', null));
        const notice = screen.getByRole('status');
        expect(notice).toHaveTextContent(/se guardó antes de registrar el criterio de cálculo/);
        expect(notice).toHaveTextContent(/no lo tomes como actualizado/);
    });

    it('informe con criterio anterior: texto distinto', () => {
        view(staleReport('criterio_anterior', 'dos_tramos_v0'));
        expect(screen.getByRole('status')).toHaveTextContent(/criterio de cálculo anterior al vigente/);
    });

    it('informe al día, sin versioning o con versioning inválido: sin aviso', () => {
        const { unmount } = view(freshReport);
        expect(screen.queryByRole('status')).not.toBeInTheDocument();
        unmount();
        const { unmount: u2 } = view({ summary, generated_at: '2026-01-02T10:00:00Z' });
        expect(screen.queryByRole('status')).not.toBeInTheDocument();
        u2();
        const { unmount: u3 } = view({ summary, versioning: 'raro' });
        expect(screen.queryByRole('status')).not.toBeInTheDocument();
        u3();
        const { unmount: u4 } = view({ summary, versioning: { stale: 'true' } });
        expect(screen.queryByRole('status')).not.toBeInTheDocument();
        u4();
        view(null);
        expect(screen.queryByRole('status')).not.toBeInTheDocument();
    });

    it('«Regenerar ahora» regenera y el aviso desaparece cuando el informe nuevo viene al día', async () => {
        regen.mockResolvedValue({});
        getReport.mockResolvedValue(freshReport);
        view(staleReport('criterio_no_registrado', null));
        fireEvent.click(screen.getByRole('button', { name: 'Regenerar ahora' }));
        await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument());
        expect(regen).toHaveBeenCalledWith(2025);
        expect(toastSuccess).toHaveBeenCalledWith('Informe fiscal 2025 regenerado');
    });

    it('si tras regenerar el informe sigue viejo, el aviso se mantiene', async () => {
        regen.mockResolvedValue({});
        getReport.mockResolvedValue(staleReport('criterio_anterior', 'x'));
        view(staleReport('criterio_no_registrado', null));
        fireEvent.click(screen.getByRole('button', { name: 'Regenerar ahora' }));
        await waitFor(() => expect(regen).toHaveBeenCalled());
        await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/anterior al vigente/));
    });
});
