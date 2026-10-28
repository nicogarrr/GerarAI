import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock('@/lib/actions/plan.actions', () => ({ saveInvestmentPlan: vi.fn() }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import PlanSetupDialog from '@/components/plan/PlanSetupDialog';

const plan = {
    monthly_contribution: 300.5,
    start_date: '2026-01-10',
    horizon_years: 25,
    target_allocations: [
        { kind: 'ticker', label: 'AAPL', target_pct: 66.67, band_pct: 5 },
        { kind: 'sector', label: 'Tecnología', target_pct: 33.33, band_pct: 2.5 },
    ],
};

describe('PlanSetupDialog precarga', () => {
    it('precarga importes y porcentajes fraccionados en gramática es-ES', () => {
        render(<PlanSetupDialog initial={plan} />);
        fireEvent.click(screen.getByRole('button', { name: /configurar plan/i }));
        const monthly = screen.getByLabelText(/aportación mensual/i) as HTMLInputElement;
        expect(monthly.value).toBe('300,5');
        const inputs = screen.getAllByPlaceholderText('%') as HTMLInputElement[];
        expect(inputs.map((i) => i.value)).toEqual(['66,67', '33,33']);
        const bands = screen.getAllByPlaceholderText('Banda') as HTMLInputElement[];
        expect(bands.map((i) => i.value)).toEqual(['5', '2,5']);
    });
});
