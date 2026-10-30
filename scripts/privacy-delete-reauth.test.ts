import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

// @ts-expect-error TS5097: node strip-types needs the source extension.
const { createDeleteReauthToken, verifyDeleteReauthToken, DELETE_REAUTH_TTL_MS } = await import('../lib/auth/delete-reauth.ts');
// @ts-expect-error TS5097: node strip-types needs the source extension.
const { deleteAuthAccountResidue } = await import('../lib/better-auth/account-residue.ts');

const SECRET = 'synthetic-delete-reauth-secret-32-chars';

test('reauth token is bound to user, secret and short expiry', () => {
    const now = Date.UTC(2026, 9, 26, 12, 0, 0);
    const token = createDeleteReauthToken('user-1', SECRET, now);
    assert.equal(verifyDeleteReauthToken(token, 'user-1', SECRET, now), true);
    assert.equal(verifyDeleteReauthToken(token, 'user-2', SECRET, now), false);
    assert.equal(verifyDeleteReauthToken(token, 'user-1', `${SECRET}x`, now), false);
    assert.equal(verifyDeleteReauthToken(`${token}x`, 'user-1', SECRET, now), false);
    assert.equal(verifyDeleteReauthToken(token, 'user-1', SECRET, now + DELETE_REAUTH_TTL_MS + 1), false);
    assert.equal(verifyDeleteReauthToken(null, 'user-1', SECRET, now), false);
});

test('auth residue cleanup removes twoFactor and pending verifications', async () => {
    const calls: Array<[string, Record<string, unknown>]> = [];
    const db = {
        collection(name: string) {
            return {
                async deleteMany(filter: Record<string, unknown>) {
                    calls.push([name, filter]);
                    return { deletedCount: 1 };
                },
            };
        },
    };
    await deleteAuthAccountResidue(db, { id: 'user-1', email: 'ana+test@example.com' });
    assert.deepEqual(calls.map(([name]) => name), ['twoFactor', 'verification']);
    assert.deepEqual(calls[0][1], { userId: 'user-1' });
    const or = calls[1][1].$or as Record<string, unknown>[];
    assert.deepEqual(or[0], { value: 'user-1' });
    const identifier = or[1].identifier as Record<string, string>;
    assert.equal(identifier.$options, 'i');
    const regex = new RegExp(identifier.$regex, 'i');
    assert.equal(regex.test('ana+test@example.com'), true);
});

test('privacy auth paths go through the rate-limited HTTP pipeline', () => {
    const password = readFileSync('lib/actions/password.actions.ts', 'utf8');
    const privacy = readFileSync('lib/actions/privacy.actions.ts', 'utf8');
    const auth = readFileSync('lib/better-auth/auth.ts', 'utf8');
    assert.doesNotMatch(password, /auth\.api\.(requestPasswordReset|resetPassword|changePassword)\b/);
    assert.doesNotMatch(privacy, /auth\.api\.(verifyPassword|deleteUser)\b/);
    assert.match(password, /callAuthEndpoint\('\/request-password-reset'/);
    assert.match(password, /callAuthEndpoint\('\/reset-password'/);
    assert.match(password, /callAuthEndpoint\('\/change-password'/);
    assert.match(privacy, /callAuthEndpoint\('\/verify-password'/);
    assert.match(privacy, /callAuthEndpoint\(\s*'\/delete-user'/);
    assert.match(privacy, /createDeleteReauthToken/);
    assert.match(auth, /beforeDelete/);
    assert.match(auth, /afterDelete/);
    assert.match(auth, /deleteAuthAccountResidue/);
    assert.match(auth, /verifyDeleteReauthToken/);
    const rateLimit = readFileSync('lib/better-auth/rate-limit.ts', 'utf8');
    assert.match(rateLimit, /'\/delete-user': \{ window: 60, max: 3 \}/);
});
