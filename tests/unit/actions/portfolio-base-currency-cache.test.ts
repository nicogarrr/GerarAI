import { beforeEach, describe, expect, it, vi } from 'vitest';

const { researchRequest, requireAuthenticatedUser } = vi.hoisted(() => ({
    researchRequest: vi.fn(),
    requireAuthenticatedUser: vi.fn(),
}));
vi.mock('next/cache', () => ({ revalidatePath: vi.fn() }));
vi.mock('@/lib/research/client', () => ({ researchRequest }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser }));

import { requestCache } from '@/lib/cache/requestCache';
import { savePortfolioBaseCurrency } from '@/lib/actions/portfolio-settings.actions';

// Suite E2E de flujos (28-oct-2026): tras cambiar la divisa base a USD, la
// cartera seguía en EUR (lecturas cacheadas 15 s en memoria del servidor).
describe('savePortfolioBaseCurrency', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        requestCache.clear();
        requireAuthenticatedUser.mockResolvedValue({ id: 'user-1' });
        researchRequest.mockResolvedValue({ base_currency: 'USD' });
    });

    it('la siguiente lectura de la cartera ya sale en la divisa nueva', async () => {
        const eur = vi.fn(async () => ({ base_currency: 'EUR', total_value: 100 }));
        await requestCache.get('portfolio:user-1:summary', eur, 15);
        await requestCache.get('portfolio:user-1:positions', eur, 15);

        await savePortfolioBaseCurrency('USD');

        const usd = vi.fn(async () => ({ base_currency: 'USD', total_value: 108 }));
        expect(await requestCache.get('portfolio:user-1:summary', usd, 15)).toEqual({ base_currency: 'USD', total_value: 108 });
        expect(await requestCache.get('portfolio:user-1:positions', usd, 15)).toEqual({ base_currency: 'USD', total_value: 108 });
        expect(usd).toHaveBeenCalledTimes(2);
    });

    it('no toca la caché de otro usuario', async () => {
        const other = vi.fn(async () => ({ base_currency: 'EUR' }));
        await requestCache.get('portfolio:user-2:summary', other, 15);
        await savePortfolioBaseCurrency('USD');
        await requestCache.get('portfolio:user-2:summary', other, 15);
        expect(other).toHaveBeenCalledTimes(1);
    });
});
