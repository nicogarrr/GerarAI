import { beforeEach, describe, expect, it, vi } from 'vitest';

const request = vi.fn();
vi.mock('@/lib/research/client', () => ({ researchRequest: (...args: unknown[]) => request(...args) }));
import { getNewsPreparing } from '@/lib/research/news-preparing';

describe('getNewsPreparing', () => {
  beforeEach(() => { request.mockReset(); });

  it('pregunta al motor por el ticker y devuelve su respuesta', async () => {
    request.mockResolvedValue({ symbol: 'BRK.B', preparing: true });
    await expect(getNewsPreparing('BRK.B')).resolves.toBe(true);
    expect(request.mock.calls[0][0]).toBe('/api/watchlist/news-preparing/BRK.B');
  });

  it('un fallo del motor nunca deja la ficha en «preparando»', async () => {
    request.mockRejectedValue(new Error('caído'));
    await expect(getNewsPreparing('ZZZ1')).resolves.toBe(false);
    request.mockResolvedValue(null);
    await expect(getNewsPreparing('ZZZ2')).resolves.toBe(false);
  });
});
