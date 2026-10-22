/** node --experimental-strip-types --test scripts/auth-session-boundary.test.ts */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { register } from 'node:module';
register('./auth-session-boundary.loader.mjs', import.meta.url);
// @ts-expect-error TS5097: node strip-types needs the real source extension.
const { signInWithEmail, signUpWithEmail, verifyTwoFactorTotp } = await import('../lib/actions/auth.actions.ts');

const credentials = { email: 'synthetic@example.com', password: 'synthetic-password-only' };
const privateResponse = {
    token: 'synthetic-session-canary',
    user: { id: 'synthetic-user', email: credentials.email },
};
const authGlobal = globalThis as typeof globalThis & { __authBoundaryTestAuth: unknown };

test('successful authentication actions never serialize session tokens or user objects', async () => {
    const inputs: unknown[] = [];
    const reply = async (input: unknown) => { inputs.push(input); return privateResponse; };
    authGlobal.__authBoundaryTestAuth = { api: { signInEmail: reply, signUpEmail: reply, verifyTOTP: reply } };
    const results = [
        await signInWithEmail(credentials),
        await signUpWithEmail({ ...credentials, fullName: 'Synthetic', country: 'ES', investmentGoals: 'Growth', riskTolerance: 'Medium', preferredIndustry: 'Technology' }),
        await verifyTwoFactorTotp({ ...credentials, totpCode: '123456' }),
    ];
    assert.equal(inputs.length, 3);
    for (const result of results) {
        assert.deepEqual(result, { success: true });
        assert.ok(!JSON.stringify(result).includes(privateResponse.token));
    }
});

test('pending two-factor sign-in is not converted to a successful session', async () => {
    authGlobal.__authBoundaryTestAuth = { api: { signInEmail: async () => ({ twoFactorRedirect: true, ...privateResponse }) } };
    assert.deepEqual(await signInWithEmail(credentials), { success: false, twoFactorRequired: true });
});
