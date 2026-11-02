import { describe, expect, it, vi } from 'vitest';

const request = vi.fn();
vi.mock('next/cache', () => ({ revalidatePath: vi.fn() }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser: vi.fn().mockResolvedValue({}) }));
vi.mock('@/lib/research/client', () => ({ researchRequest: (...a: unknown[]) => request(...a), jsonBody: JSON.stringify }));
import { AppError } from '@/lib/types/errors';
import { getDcaHitRatesState, getDcaHitRates } from '@/lib/actions/dca-signals.actions';

describe('getDcaHitRatesState', () => {
  it('404 -> not_evaluated', async () => {
    request.mockRejectedValue(new AppError('Ticker sin señal DCA evaluada (añádelo a watchlist o cartera)', 'RESEARCH_API_ERROR', 404));
    expect(await getDcaHitRatesState('AAPL')).toEqual({ status: 'not_evaluated' });
    expect(await getDcaHitRates('AAPL')).toBeNull();
  });
  it('404 genérico, timeout y auth -> unavailable', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    for (const err of [
      new AppError('404 Not Found', 'RESEARCH_API_ERROR', 404),
      Object.assign(new Error('x'), { statusCode: 404 }),
      new AppError('timeout', 'EXTERNAL_API_ERROR', 502),
      new AppError('No autenticado', 'AUTH', 401),
    ]) {
      request.mockRejectedValue(err);
      expect(await getDcaHitRatesState('AAPL')).toEqual({ status: 'unavailable' });
    }
  });
  it('otro error -> unavailable', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    request.mockRejectedValue(Object.assign(new Error('x'), { statusCode: 502 }));
    expect(await getDcaHitRatesState('AAPL')).toEqual({ status: 'unavailable' });
  });
  it('recién añadido (preparing) -> preparing, sin tarjeta', async () => {
    request.mockResolvedValue({ symbol: 'AAPL', available: false, preparing: true });
    expect(await getDcaHitRatesState('AAPL')).toEqual({ status: 'preparing' });
    expect(await getDcaHitRates('AAPL')).toBeNull();
  });
  it('dato -> ok', async () => {
    request.mockResolvedValue({ available: true });
    expect(await getDcaHitRatesState('AAPL')).toEqual({ status: 'ok', data: { available: true } });
    expect(await getDcaHitRates('AAPL')).toEqual({ available: true });
  });
});
