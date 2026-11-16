import { render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
vi.mock('@/lib/actions/plan.actions', () => ({ getPlan: vi.fn(), getPlanContributions: vi.fn(), getPlanDrift: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
import PlanView from '@/components/plan/PlanView';
import { formatMoney } from '@/lib/format';
it('an empty legacy contribution currency does not crash the Plan page or block other records', () => {
    render(<PlanView
        initialPlan={{ plan_exists: true, monthly_contribution: 300, base_currency: 'EUR' }}
        initialDrift={null}
        initialContributions={[
            { id: 3, date: '2026-01-01', amount: 20, currency: '', note: 'Legacy empty currency' },
            { id: 4, date: '2026-01-02', amount: 30, currency: 'USD', note: 'Valid USD contribution' },
        ]}
    />);
    expect(screen.getAllByText('Legacy empty currency').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Valid USD contribution').length).toBeGreaterThan(0);
    expect(screen.getAllByText('30,00 US$').length).toBeGreaterThan(0);
});

it.each(['', ' ', 'EURO', '12$', '__proto__'])('falls back to EUR for malformed currency %s', currency => {
    expect(formatMoney(20, currency)).toBe(formatMoney(20, 'EUR'));
});
