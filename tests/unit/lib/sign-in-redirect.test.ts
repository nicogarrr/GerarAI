// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';

const headerStore = new Map<string, string>();

vi.mock('next/headers', () => ({
    headers: async () => ({ get: (name: string) => headerStore.get(name.toLowerCase()) ?? null }),
}));

vi.mock('next/navigation', () => ({
    redirect: (url: string) => {
        throw new Error(`REDIRECT:${url}`);
    },
}));

import { REQUESTED_PATH_HEADER, signInPathFor } from '@/lib/auth/safe-redirect';
import { redirectToSignIn } from '@/lib/auth/sign-in-redirect';

describe('signInPathFor', () => {
    it('conserva la ruta pedida en ?next=', () => {
        expect(signInPathFor('/research/ASTS?tab=tesis')).toBe('/sign-in?next=%2Fresearch%2FASTS%3Ftab%3Dtesis');
    });

    it('sin ruta útil o externa, /sign-in a secas', () => {
        for (const value of [null, undefined, '', '/inicio', '//evil.example', 'https://evil.example', '/sign-in']) {
            expect(signInPathFor(value)).toBe('/sign-in');
        }
    });
});

describe('redirectToSignIn (sesión caducada en layout o página)', () => {
    beforeEach(() => headerStore.clear());

    it('redirige con ?next= a la ruta que anotó el middleware', async () => {
        headerStore.set(REQUESTED_PATH_HEADER, '/watchlist?orden=dca');
        await expect(redirectToSignIn()).rejects.toThrow('REDIRECT:/sign-in?next=%2Fwatchlist%3Forden%3Ddca');
    });

    it('sin cabecera, /sign-in a secas', async () => {
        await expect(redirectToSignIn()).rejects.toThrow(/^REDIRECT:\/sign-in$/);
    });

    it('una cabecera con destino externo no abre una redirección abierta', async () => {
        headerStore.set(REQUESTED_PATH_HEADER, '//evil.example/x');
        await expect(redirectToSignIn()).rejects.toThrow(/^REDIRECT:\/sign-in$/);
    });
});
