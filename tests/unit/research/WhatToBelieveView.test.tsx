import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { WhatToBelieveSkeleton, WhatToBelieveView } from '@/components/research/WhatToBelieveView';
import { LocaleProvider } from '@/lib/i18n/client';
import type { WhatToBelieve } from '@/lib/research/what-to-believe';

const ok = {
  ticker: 'PLTR', status: 'ok', reason_code: null, reason: null, engine: 'standard_dcf', currency: 'USD',
  current_price: 175.4, base_value: 108.78, wacc_used: 0.085, terminal_growth: 0.03,
  implied_wacc_price: { status: 'ok', target_price: 175.4, wacc: 0.0661, direction: null, bounds: [0.0325, 0.25] },
  implied_wacc_consensus: { status: 'ok', target_price: 223.68, wacc: 0.059, direction: null, bounds: [0.0325, 0.25] },
  consensus_price: 223.68, consensus_source: 'Yahoo Finance',
  implied_growth: { status: 'ok', required_revenue_growth: 0.52, current_revenue_growth: 0.329, method: 'reverse_dcf_stage1_growth' },
  exit_multiple: { multiple: 25, metric: 'terminal_year_fcf', value_per_share: 134.59, gordon_value_per_share: 108.78, implied_multiple_for_price: 34.9 },
} as WhatToBelieve;

const es = (ui: React.ReactNode) => render(<LocaleProvider locale="es">{ui}</LocaleProvider>);
const en = (ui: React.ReactNode) => render(<LocaleProvider locale="en">{ui}</LocaleProvider>);

describe('WhatToBelieveView', () => {
  it('says the WACC the price needs vs the one we use, the consensus, the growth and the exit-multiple contrast', () => {
    es(<WhatToBelieveView data={ok} />);
    expect(screen.getByText('Qué hace falta creer')).toBeInTheDocument();
    const wacc = screen.getByTestId('what-to-believe-wacc');
    expect(wacc).toHaveTextContent('hace falta un WACC del 6,6');
    expect(wacc).toHaveTextContent('usamos 8,5');
    expect(wacc).toHaveTextContent('175,40');
    expect(screen.getByTestId('what-to-believe-consensus')).toHaveTextContent('5,9');
    expect(screen.getByTestId('what-to-believe-growth')).toHaveTextContent('52,0');
    const exit = screen.getByTestId('what-to-believe-exit');
    expect(exit).toHaveTextContent('25x');
    expect(exit).toHaveTextContent('134,59');
    expect(exit).toHaveTextContent('108,78');
    expect(screen.getByTestId('what-to-believe-exit-implied')).toHaveTextContent('35x');
  });

  it('renders in English', () => {
    en(<WhatToBelieveView data={ok} />);
    expect(screen.getByText('What you need to believe')).toBeInTheDocument();
    expect(screen.getByTestId('what-to-believe-wacc')).toHaveTextContent('To justify $175.40 you need a WACC of 6.6% (we use 8.5%)');
  });

  it('out of range says so instead of a number', () => {
    const data = { ...ok, implied_wacc_price: { status: 'out_of_range', target_price: 175.4, wacc: null, direction: 'below_min', bounds: [0.0325, 0.25] }, implied_wacc_consensus: null } as WhatToBelieve;
    es(<WhatToBelieveView data={data} />);
    expect(screen.getByTestId('what-to-believe-wacc')).toHaveTextContent('por debajo del 3,3');
    expect(screen.queryByTestId('what-to-believe-consensus')).not.toBeInTheDocument();
  });

  it('no aplica with the translated reason', () => {
    const na = { ticker: 'JPM', status: 'not_applicable', reason_code: 'engine_not_dcf', reason: 'x' } as WhatToBelieve;
    es(<WhatToBelieveView data={na} />);
    expect(screen.getByTestId('what-to-believe-na')).toHaveTextContent('No aplica: el método de valoración');
    expect(screen.queryByTestId('what-to-believe-wacc')).not.toBeInTheDocument();
  });

  it('unavailable and loading states', () => {
    const { unmount } = es(<WhatToBelieveView data={null} />);
    expect(screen.getByTestId('what-to-believe-unavailable')).toBeInTheDocument();
    unmount();
    es(<WhatToBelieveSkeleton />);
    expect(screen.getByTestId('what-to-believe-loading')).toHaveAttribute('aria-busy', 'true');
  });
});
