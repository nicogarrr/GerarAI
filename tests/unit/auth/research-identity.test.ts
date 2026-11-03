import { createHmac } from 'node:crypto';

import { beforeEach, describe, expect, it, vi } from 'vitest';

const m = vi.hoisted(() => ({
    requireUser: vi.fn(),
}));

vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser: m.requireUser }));

import { researchIdentityHeaders } from '@/lib/auth/research-identity';

const SECRET = 's'.repeat(32);

describe('researchIdentityHeaders: correo firmado', () => {
    beforeEach(() => {
        vi.resetAllMocks();
        process.env.RESEARCH_AUTH_SECRET = SECRET;
    });

    it('firma el correo de la sesion ligado a la identidad y al nonce', async () => {
        m.requireUser.mockResolvedValue({ id: 'user-1', email: '  Propio@Example.com ', name: 'N' });
        const headers = await researchIdentityHeaders({ method: 'GET', path: '/api/alerts/email-preferences' });
        expect(headers['X-CavaAI-Email']).toBe('propio@example.com');
        const expected = createHmac('sha256', SECRET)
            .update(
                `user-1:user-1:${headers['X-CavaAI-Timestamp']}:${headers['X-CavaAI-Nonce']}:email:propio@example.com`,
            )
            .digest('hex');
        expect(headers['X-CavaAI-Email-Signature']).toBe(expected);
        // La firma principal no cambia de formato: el motor la sigue verificando igual.
        const main = createHmac('sha256', SECRET)
            .update(
                `user-1:user-1:${headers['X-CavaAI-Timestamp']}:${headers['X-CavaAI-Nonce']}:GET:/api/alerts/email-preferences:${createHmac('sha256', 'x').update('').digest('hex')}`,
            )
            .digest('hex');
        expect(headers['X-CavaAI-Signature']).toHaveLength(64);
        expect(headers['X-CavaAI-Signature']).not.toBe(main);
    });

    it('sin correo en la sesion no envia las cabeceras de email', async () => {
        m.requireUser.mockResolvedValue({ id: 'user-1', email: null, name: 'N' });
        const headers = await researchIdentityHeaders({ method: 'GET', path: '/api/alerts' });
        expect('X-CavaAI-Email' in headers).toBe(false);
        expect('X-CavaAI-Email-Signature' in headers).toBe(false);
    });
});
