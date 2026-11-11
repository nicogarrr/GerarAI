import { expect, it, vi } from 'vitest';
const m = vi.hoisted(() => ({ targets: vi.fn(), history: vi.fn() }));
vi.mock('@/lib/research/analyst-targets', () => ({ getAnalystTargets: m.targets }));
vi.mock('@/lib/research/analyst-history', () => ({ getAnalystHistory: m.history }));
import { readAnalystHistory, readAnalystTargets } from '@/lib/actions/analyst-panels.actions';
it('delegates each requested panel unchanged to its existing authenticated source', async () => {
    m.targets.mockResolvedValue({ symbol: 'AAPL' }); m.history.mockResolvedValue(null);
    expect(await readAnalystTargets('AAPL')).toEqual({ symbol: 'AAPL' });
    expect(await readAnalystHistory('MSFT')).toBeNull();
    expect(m.targets).toHaveBeenCalledWith('AAPL'); expect(m.history).toHaveBeenCalledWith('MSFT');
});
