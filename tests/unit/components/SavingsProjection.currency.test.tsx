import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
const getPlan = vi.fn();
const getSavingsProjection = vi.fn();
vi.mock('@/lib/actions/plan.actions', () => ({ getPlan: (...args: unknown[]) => getPlan(...args), getSavingsProjection: (...args: unknown[]) => getSavingsProjection(...args) }));
vi.mock('@/components/plan/PlanSetupDialog', () => ({ default: ({ triggerLabel }: { triggerLabel: string }) => <button>{triggerLabel}</button> }));
vi.mock('next/link', () => ({ default: ({ children, href }: { children: React.ReactNode; href: string }) => <a href={href}>{children}</a> }));
import SavingsProjection from '@/components/portfolio/SavingsProjection';

describe('SavingsProjection: divisa del plan fuera de la lista habitual', () => {
    it('un plan en DKK muestra DKK elegida, no «Elige divisa»', async () => {
        getPlan.mockResolvedValue({ plan_exists: true, monthly_contribution: 2000 });
        getSavingsProjection.mockResolvedValue({ plan_exists: true, preview: false, monthly_contribution: 2000, currency: 'DKK',
            horizon_years: 20, initial_capital: 0, portfolio_included: false, status: 'ok', scenarios: [], assumptions: [] });
        render(<SavingsProjection />);
        const select = screen.getByLabelText('Divisa de la aportación') as HTMLSelectElement;
        await waitFor(() => expect(getSavingsProjection).toHaveBeenCalled());
        await waitFor(() => expect(select.value).toBe('DKK'));
        expect(Array.from(select.options).map((o) => o.value)).toContain('DKK');
    });
});
