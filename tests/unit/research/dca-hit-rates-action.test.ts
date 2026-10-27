import { describe, expect, it, vi } from 'vitest';

const request = vi.fn();
vi.mock('next/cache', () => ({ revalidatePath: vi.fn() }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser: vi.fn().mockResolvedValue({}) }));
vi.mock('@/lib/research/client', () => ({ researchRequest: (...a: unknown[]) => request(...a), jsonBody: JSON.stringify }));
import { getDcaHitRatesState, getDcaHitRates } from '@/lib/actions/dca-signals.actions';

describe('getDcaHitRatesState', () => {
  it('404 -> not_evaluated', async () => {
    request.mockRejectedValue(Object.assign(new Error('x'), { statusCode: 404 }));
    expect(await getDcaHitRatesState('AAPL')).toEqual({ status: 'not_evaluated' });
    expect(await getDcaHitRates('AAPL')).toBeNull();
  });
  it('otro error -> unavailable', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    request.mockRejectedValue(Object.assign(new Error('x'), { statusCode: 502 }));
    expect(await getDcaHitRatesState('AAPL')).toEqual({ status: 'unavailable' });
  });
  it('dato -> ok', async () => {
    request.mockResolvedValue({ available: true });
    expect(await getDcaHitRatesState('AAPL')).toEqual({ status: 'ok', data: { available: true } });
    expect(await getDcaHitRates('AAPL')).toEqual({ available: true });
  });
});
