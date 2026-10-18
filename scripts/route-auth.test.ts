import assert from 'node:assert/strict';
import test from 'node:test';

// @ts-expect-error TS5097: la extension explicita la exige node --experimental-strip-types.
import { withAuthErrors } from '../lib/auth/route-auth.ts';
// @ts-expect-error TS5097: la extension explicita la exige node --experimental-strip-types.
import { AuthenticationError } from '../lib/types/errors.ts';

test('AuthenticationError -> 401 JSON sin cache', async () => {
    const handler = withAuthErrors(async () => {
        throw new AuthenticationError('User not authenticated');
    });
    const response = await handler();
    assert.equal(response.status, 401);
    assert.equal(response.headers.get('cache-control'), 'no-store');
    assert.deepEqual(await response.json(), { error: 'No autenticado' });
});

test('otros errores se propagan y las respuestas OK pasan tal cual', async () => {
    await assert.rejects(
        () =>
            withAuthErrors(async () => {
                throw new Error('boom');
            })(),
        /boom/,
    );
    const ok = await withAuthErrors(async (x: number) => Response.json({ x }))(7);
    assert.equal(ok.status, 200);
    assert.deepEqual(await ok.json(), { x: 7 });
});
