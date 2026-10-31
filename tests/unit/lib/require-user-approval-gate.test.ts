import { beforeEach, describe, expect, it, vi } from 'vitest';

const { getAuth, getSession } = vi.hoisted(() => ({ getAuth: vi.fn(), getSession: vi.fn() }));
vi.mock('@/lib/better-auth/auth', () => ({ getAuth }));
vi.mock('next/headers', () => ({ headers: vi.fn(async () => new Headers()) }));

// vi.resetModules recarga errors.ts por caso: las clases cambian de identidad,
// así que se compara por name/code, no por instanceof.
type AppErrorLike = { name: string; code: string; statusCode: number };

// React cache() memoriza por modulo: modulo fresco por caso para aislar sesiones.
async function loadGate() {
    vi.resetModules();
    const mod = await import('@/lib/auth/require-user');
    return mod.requireAuthenticatedUser;
}

beforeEach(() => {
    vi.clearAllMocks();
    delete process.env.E2E_AUTH_BYPASS;
    getAuth.mockResolvedValue({ api: { getSession } });
});

describe('requireAuthenticatedUser: gate central de aprobación', () => {
    it('sin sesión: AuthenticationError como siempre', async () => {
        getSession.mockResolvedValue(null);
        const requireAuthenticatedUser = await loadGate();
        await expect(requireAuthenticatedUser()).rejects.toMatchObject({ name: 'AuthenticationError' });
    });

    it('cuenta pending con sesión: 403 con código estable ACCOUNT_PENDING', async () => {
        getSession.mockResolvedValue({ user: { id: 'u1', email: 'p@e.co', accountStatus: 'pending' } });
        const requireAuthenticatedUser = await loadGate();
        const error = (await requireAuthenticatedUser().catch((e: unknown) => e)) as AppErrorLike;
        expect(error.name).toBe('AppError');
        expect(error.code).toBe('ACCOUNT_PENDING');
        expect(error.statusCode).toBe(403);
    });

    it('cuenta rejected con sesión: 403 con código estable ACCOUNT_REJECTED', async () => {
        getSession.mockResolvedValue({ user: { id: 'u1', email: 'r@e.co', accountStatus: 'rejected' } });
        const requireAuthenticatedUser = await loadGate();
        const error = (await requireAuthenticatedUser().catch((e: unknown) => e)) as AppErrorLike;
        expect(error.code).toBe('ACCOUNT_REJECTED');
        expect(error.statusCode).toBe(403);
    });

    it('cuenta approved pasa', async () => {
        getSession.mockResolvedValue({ user: { id: 'u1', email: 'a@e.co', accountStatus: 'approved' } });
        const requireAuthenticatedUser = await loadGate();
        await expect(requireAuthenticatedUser()).resolves.toEqual({ id: 'u1', email: 'a@e.co', name: undefined });
    });

    it('cuenta sin el campo (abuela, anterior a la función) pasa', async () => {
        getSession.mockResolvedValue({ user: { id: 'u1', email: 'abuela@e.co' } });
        const requireAuthenticatedUser = await loadGate();
        await expect(requireAuthenticatedUser()).resolves.toEqual({ id: 'u1', email: 'abuela@e.co', name: undefined });
    });
});
