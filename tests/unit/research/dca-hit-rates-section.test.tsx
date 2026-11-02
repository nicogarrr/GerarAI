import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const getState = vi.fn();
vi.mock('@/lib/actions/dca-signals.actions', () => ({ getDcaHitRatesState: (s: string) => getState(s) }));
// Server component traducido con getT(): sin cookie el locale es «es».
vi.mock('next/headers', () => ({ cookies: async () => ({ get: () => undefined }) }));
vi.mock('@/components/watchlist/DcaHitRatesCard', () => ({ default: () => <div data-testid="card" /> }));
vi.mock('@/components/research/DcaPreparingRefresh', () => ({ default: () => <span data-testid="refresh" /> }));
import { DcaHitRatesSection } from '@/components/research/DcaHitRatesSection';

describe('DcaHitRatesSection', () => {
  it('ticker sin señal evaluada: lo dice, sin tarjeta', async () => {
    getState.mockResolvedValue({ status: 'not_evaluated' });
    render(await DcaHitRatesSection({ ticker: 'AAPL' }));
    expect(screen.getByTestId('dca-hit-rates-not-evaluated')).toHaveTextContent('aún no tiene señal DCA evaluada');
    expect(screen.queryByTestId('card')).not.toBeInTheDocument();
  });
  it('servicio no consultable: no afirma que no haya histórico', async () => {
    getState.mockResolvedValue({ status: 'unavailable' });
    render(await DcaHitRatesSection({ ticker: 'AAPL' }));
    const el = screen.getByTestId('dca-hit-rates-unavailable');
    expect(el).toHaveTextContent('Histórico no disponible');
    expect(el).not.toHaveTextContent('aún no tiene');
  });
  it('recién añadido: dice «preparando» y se refresca solo, sin el aviso de «sin señal»', async () => {
    getState.mockResolvedValue({ status: 'preparing' });
    render(await DcaHitRatesSection({ ticker: 'AAPL' }));
    const el = screen.getByTestId('dca-hit-rates-preparing');
    expect(el).toHaveTextContent('Preparando la señal DCA');
    expect(el).not.toHaveTextContent('aún no tiene');
    expect(screen.getByTestId('refresh')).toBeInTheDocument();
    expect(screen.queryByTestId('card')).not.toBeInTheDocument();
  });
  it('con dato renderiza la tarjeta', async () => {
    getState.mockResolvedValue({ status: 'ok', data: { available: true } });
    render(await DcaHitRatesSection({ ticker: 'AAPL' }));
    expect(screen.getByTestId('card')).toBeInTheDocument();
  });
});
