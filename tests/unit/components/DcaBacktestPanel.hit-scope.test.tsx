import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ load: vi.fn() }));
vi.mock('@/lib/actions/dca-signals.actions', () => ({ getDcaBacktest: mocks.load }));

import DcaBacktestPanel from '@/components/proPicks/DcaBacktestPanel';

const plan = (key: string) => ({
    key, label: key, invested: 1200, deployed: 1200, cash_left: 0, shares: 10, avg_cost: 120, final_value: 1500,
    multiple: 1.25, irr: 0.1, max_drawdown: -0.2, worst_unrealized: -0.1, buys: 12, irr_vs_plain: 0, value_vs_plain: 0,
});

describe('backtest DCA: la tabla de aciertos dice su alcance', () => {
    it('con «Desde» acotado, no presume de «histórico completo»', async () => {
        mocks.load.mockResolvedValue({ error: null, data: {
            symbol: 'UBER', available: true, currency: 'USD', currency_label: 'USD', params_version: 'v1',
            first_signal: '2024-01', last_signal: '2024-12', first_buy: '2024-02-01', last_buy: '2025-01-02',
            valued_at_period: '2025-01', valued_at_date: '2025-01-31', valued_month_complete: true, final_price: 150,
            months: 12, base_amount: 100, plans: [plan('plain'), plan('levels'), plan('fixed_budget')], levels: [],
            disclaimer: 'Histórico.',
            hit_rates: { symbol: 'UBER', available: true, reason: null, months_completed: 12, first_period: '2024-01',
                last_period: '2024-12', horizons: [1], params_version: 'v1', evaluated_at: null, disclaimer: 'Solo histórico.',
                rows: [{ key: '1x', label: '1X', levels: [1], color: '#FFFFFF', signal_months: 12,
                    cells: [{ horizon_months: 1, months: 12, pct_higher: 0.5, avg_return: 0.01 }] }] },
        } });
        render(<DcaBacktestPanel />);
        fireEvent.submit(screen.getByTestId('dca-backtest').querySelector('form')!);
        await waitFor(() => expect(screen.getByTestId('dca-hit-rates')).toBeInTheDocument());
        expect(screen.getByTestId('dca-hit-rates')).toHaveTextContent('solo el rango elegido');
        expect(screen.getByTestId('dca-hit-rates')).not.toHaveTextContent('histórico completo');
    });
});
