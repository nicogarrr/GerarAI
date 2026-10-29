import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/actions/corporate-actions.actions', () => ({
    applyCorporateAction: vi.fn(),
    getCorporateActions: vi.fn(async () => []),
}));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import CorporateActionsView from '@/components/corporate-actions/CorporateActionsView';
import type { DataRecord } from '@/components/data/RecordViews';

const dividend = (id: number, source: string): DataRecord => ({
    id,
    ticker: 'ASTS',
    action_type: 'dividend',
    amount_per_share: 0.5,
    currency: 'USD',
    pay_date: '2026-11-15',
    effective_date: '2026-10-30',
    source,
    declared: true,
});

describe('CorporateActionsView', () => {
    it('no pinta el proveedor en crudo; conserva el matiz de ajuste por splits', () => {
        render(<CorporateActionsView initialActions={[dividend(1, 'yahoo_finance')]} />);
        expect(document.body.textContent).not.toContain('yahoo_finance');
        expect(document.body.textContent).not.toContain('fuente');
        expect(screen.getAllByText(/ajustado por splits/).length).toBeGreaterThan(0);
    });
    it('pagina la lista (25 eventos por página)', () => {
        const many = Array.from({ length: 30 }, (_, i) => ({ id: i + 1, ticker: `T${i + 1}`, action_type: 'split', effective_date: '2026-10-01', ratio: 2 }));
        render(<CorporateActionsView initialActions={many} />);
        expect(screen.getAllByRole('navigation', { name: 'Paginación de eventos' }).length).toBe(2);
        expect(screen.queryByText('T26')).not.toBeInTheDocument();
    });
});
