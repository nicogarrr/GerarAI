import { beforeEach, describe, expect, it, vi } from 'vitest';

const { researchRequest } = vi.hoisted(() => ({ researchRequest: vi.fn(async (_path: string, _init?: unknown) => ({})) }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser: vi.fn(async () => ({ id: 'u1' })) }));
vi.mock('@/lib/research/client', () => ({ researchRequest, jsonBody: (b: unknown) => JSON.stringify(b) }));

import { setPushPreference, type PushEventType } from '@/lib/actions/push.actions';

beforeEach(() => vi.clearAllMocks());

describe('setPushPreference: el tipo de aviso viene del cliente', () => {
    it('un tipo conocido llega a su ruta', async () => {
        await setPushPreference('earnings', true);
        expect(researchRequest).toHaveBeenCalledTimes(1);
        expect(researchRequest.mock.calls[0][0]).toBe('/api/alerts/push/preferences/earnings');
    });

    it('un tipo inventado con «..» no compone otra ruta del backend', async () => {
        await expect(setPushPreference('../../../portfolio/holdings/1' as PushEventType, true)).rejects.toThrow();
        expect(researchRequest).not.toHaveBeenCalled();
    });
});
