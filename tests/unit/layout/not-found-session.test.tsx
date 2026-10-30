// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * El 404 raíz se renderiza dentro de la respuesta de TODAS las páginas (límite
 * notFound del layout raíz). Si lee la sesión sin Cookie, cada visita anónima a
 * `/`, `/sign-in` o `/metodologia` consulta Mongo, y con Mongo caído la
 * respuesta no termina hasta el timeout de conexión (30 s).
 */
const headerStore = new Map<string, string>();
vi.mock('next/headers', () => ({
    headers: async () => ({ get: (name: string) => headerStore.get(name.toLowerCase()) ?? null }),
}));
const requireAuthenticatedUser = vi.fn();
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser: () => requireAuthenticatedUser() }));
vi.mock('@/app/(root)/layout', () => ({ default: function AuthenticatedLayoutMock() { return null; } }));

import NotFound from '@/app/not-found';
import AuthenticatedLayout from '@/app/(root)/layout';

describe('404 raíz: sesión solo con Cookie', () => {
    beforeEach(() => {
        headerStore.clear();
        requireAuthenticatedUser.mockReset();
        vi.unstubAllEnvs();
    });

    it('sin Cookie no lee la sesión (ni toca Mongo) y sirve el 404 público', async () => {
        requireAuthenticatedUser.mockImplementation(() => new Promise(() => {}));
        const element = await NotFound();
        expect(requireAuthenticatedUser).not.toHaveBeenCalled();
        expect(element.type).not.toBe(AuthenticatedLayout);
    });

    it('con Cookie y sesión válida usa el layout autenticado', async () => {
        headerStore.set('cookie', 'better-auth.session_token=abc');
        requireAuthenticatedUser.mockResolvedValue({ id: 'u1' });
        const element = await NotFound();
        expect(requireAuthenticatedUser).toHaveBeenCalledTimes(1);
        expect(element.type).toBe(AuthenticatedLayout);
    });

    it('con Cookie pero sesión inválida o DB caída sigue siendo el 404 público', async () => {
        headerStore.set('cookie', 'better-auth.session_token=viejo');
        requireAuthenticatedUser.mockRejectedValue(new Error('MongoDB connection is required at runtime'));
        const element = await NotFound();
        expect(element.type).not.toBe(AuthenticatedLayout);
    });

    it('el bypass de e2e conserva su usuario sintético sin Cookie', async () => {
        vi.stubEnv('E2E_AUTH_BYPASS', '1');
        vi.stubEnv('APP_ENV', 'test');
        vi.stubEnv('NODE_ENV', 'test');
        requireAuthenticatedUser.mockResolvedValue({ id: 'e2e-browser-user' });
        const element = await NotFound();
        expect(element.type).toBe(AuthenticatedLayout);
    });
});
