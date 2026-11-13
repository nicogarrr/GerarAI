import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ensureSignInAccount } from '../../../e2e/user-flows/sign-in-account';

const account = { email: 'synthetic@example.invalid', password: 'synthetic-test-input', name: 'Synthetic E2E' };
const request = { post: vi.fn() };
const reply = (status: number, payload: unknown) => ({ status: () => status, json: async () => payload });
beforeEach(() => { request.post.mockReset(); });

describe('sign-in synthetic account precondition', () => {
    it.each([200, 201])('sends explicit legal acceptance and verifies the created user (HTTP %s)', async (status) => {
        request.post.mockResolvedValue(reply(status, { user: { id: 'synthetic-id', email: account.email } }));
        await expect(ensureSignInAccount(request, 'http://localhost:3100', account)).resolves.toBeUndefined();
        expect(request.post).toHaveBeenCalledWith('http://localhost:3100/api/auth/sign-up/email', {
            data: { ...account, acceptTerms: true }, headers: { Origin: 'http://localhost:3100' }, failOnStatusCode: false,
        });
    });
    it('allows the documented fixture duplicate', async () => {
        request.post.mockResolvedValue(reply(422, { code: 'USER_ALREADY_EXISTS_USE_ANOTHER_EMAIL' }));
        await expect(ensureSignInAccount(request, 'http://localhost:3100', account)).resolves.toBeUndefined();
    });
    it.each([
        [400, { code: 'LEGAL_ACCEPTANCE_REQUIRED' }],
        [403, { code: 'SIGNUP_NOT_INVITED' }],
        [429, { code: 'USER_ALREADY_EXISTS' }],
        [500, { code: 'USER_ALREADY_EXISTS' }],
        [422, { code: 'UNKNOWN' }],
        [400, { code: 'USER_ALREADY_EXISTS_USE_ANOTHER_EMAIL' }],
        [200, {}],
        [200, { user: { id: 'synthetic-id', email: 'other@example.invalid' } }],
        [200, { user: { email: account.email } }],
    ])('fails at setup rather than later in login for HTTP %s and %j', async (status, payload) => {
        request.post.mockResolvedValue(reply(status, payload));
        await expect(ensureSignInAccount(request, 'http://localhost:3100', account)).rejects.toThrow('E2E sign-in account setup failed');
    });
    it('fails safely for a non-JSON response without exposing its body', async () => {
        request.post.mockResolvedValue({ status: () => 502, json: async () => { throw new Error('synthetic private body'); } });
        await expect(ensureSignInAccount(request, 'http://localhost:3100', account)).rejects.toThrow('HTTP 502');
    });
});
