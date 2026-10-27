import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const getDcaHitRates = vi.fn();
vi.mock('@/lib/actions/dca-signals.actions', () => ({ getDcaHitRates: (s: string) => getDcaHitRates(s) }));
vi.mock('@/components/watchlist/DcaHitRatesCard', () => ({ default: () => <div data-testid="card" /> }));
import { DcaHitRatesSection } from '@/components/research/DcaHitRatesSection';

describe('DcaHitRatesSection', () => {
  it('muestra un estado explícito (no queda vacío) cuando no hay dato', async () => {
    getDcaHitRates.mockResolvedValue(null);
    render(await DcaHitRatesSection({ ticker: 'AAPL' }));
    expect(screen.getByTestId('dca-hit-rates-empty')).toHaveTextContent('Sin histórico de señales DCA');
    expect(screen.queryByTestId('card')).not.toBeInTheDocument();
  });
  it('con dato renderiza la tarjeta', async () => {
    getDcaHitRates.mockResolvedValue({ available: true });
    render(await DcaHitRatesSection({ ticker: 'AAPL' }));
    expect(screen.getByTestId('card')).toBeInTheDocument();
    expect(screen.queryByTestId('dca-hit-rates-empty')).not.toBeInTheDocument();
  });
});
