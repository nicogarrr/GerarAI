import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { getDcaBacktest } = vi.hoisted(() => ({ getDcaBacktest: vi.fn() }));
vi.mock('@/lib/actions/dca-signals.actions', () => ({ getDcaBacktest }));
vi.mock('@/components/watchlist/DcaHitRatesCard', () => ({ default: () => null }));

import DcaBacktestPanel, { valuationLabel } from '@/components/proPicks/DcaBacktestPanel';
import { LocaleProvider } from '@/lib/i18n/client';

const plan = (key: string, label: string) => ({
    key, label, invested: 12000, final_value: 15432.1, irr: 0.081, avg_cost: 45.5, max_drawdown: -0.25,
    worst_unrealized: -0.12, cash_left: 0, irr_vs_plain: 0.012, shares_per_money_vs_plain: 0.034, value_vs_plain: -0.02,
});

const data = {
    available: true, symbol: 'UBER', first_signal: '2016-01', last_signal: '2026-09', months: 129,
    valued_at_period: '2026-09', valued_at_date: '2026-09-30', valued_month_complete: true,
    currency: 'USD', currency_label: 'USD', params_version: 'v1',
    plans: [plan('plain', 'Plain'), plan('levels', 'Levels'), plan('fixed_budget', 'Fixed')],
    levels: [{ level: 1, label: '1X', months: 80, color: '#000' }], hit_rates: null, disclaimer: 'x',
};

describe('Backtest DCA en inglés', () => {
    beforeEach(() => getDcaBacktest.mockReset().mockResolvedValue({ data, error: null }));

    it('el formulario, la tabla y las notas salen en inglés con números en formato inglés', async () => {
        render(<LocaleProvider locale="en"><DcaBacktestPanel /></LocaleProvider>);
        expect(screen.getByText('DCA backtest: flat vs tiered')).toBeTruthy();
        expect(screen.getByLabelText('Base contribution')).toBeTruthy();
        fireEvent.submit(screen.getByRole('button', { name: /^Run$/ }).closest('form')!);
        await waitFor(() => expect(screen.getByText('Money contributed')).toBeTruthy());
        expect(screen.getAllByText('12,000.00 USD').length).toBe(3);
        expect(screen.getByText('Annual IRR')).toBeTruthy();
        expect(document.body.textContent).toContain('UBER · signals 2016-01 – 2026-09 (129 months) · valued at the close of 2026-09');
        expect(document.body.textContent).toContain('IRR +1.20 pp vs flat; with the same total money it buys +3.4% shares.');
        expect(document.body.textContent).toContain('1X: 80 months');
        expect(document.body.textContent).not.toMatch(/meses|Dinero aportado|valorado/);
    });

    it('un importe en formato inglés se acepta y uno mal escrito avisa en inglés', async () => {
        render(<LocaleProvider locale="en"><DcaBacktestPanel /></LocaleProvider>);
        const input = screen.getByLabelText('Base contribution');
        fireEvent.change(input, { target: { value: '-5' } });
        fireEvent.submit(screen.getByRole('button', { name: /^Run$/ }).closest('form')!);
        expect(screen.getByRole('alert').textContent).toBe('Enter a base contribution greater than 0.');
        fireEvent.change(input, { target: { value: '1,250.50' } });
        fireEvent.submit(screen.getByRole('button', { name: /^Run$/ }).closest('form')!);
        await waitFor(() => expect(getDcaBacktest).toHaveBeenCalledWith(expect.objectContaining({ base: 1250.5 })));
    });

    it('la etiqueta de valoración en inglés; en español igual', () => {
        const open = { valued_at_period: '2026-10', valued_at_date: '2026-10-29', valued_month_complete: false };
        expect(valuationLabel(open, 'en')).toMatch(/^valued at the latest available close \(Oct 29, 2026, month in progress\)$/);
        expect(valuationLabel({ ...open, valued_month_complete: true })).toBe('valorado al cierre de 2026-10');
    });
});
