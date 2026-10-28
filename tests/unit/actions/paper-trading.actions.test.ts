import { beforeEach, describe, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock('@/lib/research/client', () => ({ researchRequest: mocks.request }));
import { getCompanyPaperTrades } from '@/lib/actions/paper-trading.actions';
import { AppError } from '@/lib/types/errors';

describe('Company paper trades action', () => {
    beforeEach(() => { mocks.request.mockReset(); });
    it('asks the backend only for this ticker, encoded', async () => {
        mocks.request.mockResolvedValue([{ id: 1, ticker: 'BRK.B' }]);
        expect(await getCompanyPaperTrades('BRK.B')).toEqual({ trades: [{ id: 1, ticker: 'BRK.B' }] });
        expect(mocks.request).toHaveBeenCalledWith('/api/paper-trading/proposals?ticker=BRK.B&limit=20');
        await getCompanyPaperTrades('A&B');
        expect(mocks.request).toHaveBeenLastCalledWith('/api/paper-trading/proposals?ticker=A%26B&limit=20');
    });
    it('reports a provider failure as an error, never as an empty book', async () => {
        mocks.request.mockRejectedValue(new AppError('caído', 'RESEARCH_API_ERROR', 502));
        expect(await getCompanyPaperTrades('TEST')).toEqual({ trades: [], error: 'No se pudieron cargar las operaciones simuladas.' });
    });
    it('does not hide an authentication failure', async () => {
        mocks.request.mockRejectedValue(new AppError('sin sesión', 'UNAUTHORIZED', 401));
        await expect(getCompanyPaperTrades('TEST')).rejects.toThrow('sin sesión');
    });
});
