/**
 * Cerrar sesión: si signOut falla (resultado o excepción) no se navega a
 * /sign-in; se avisa en castellano. Si va bien, se navega y refresca.
 * Ejecución: node --experimental-strip-types --test scripts/sign-out-failure-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
// @ts-expect-error TS5097: la extension explicita la exige node --experimental-strip-types.
import { runSignOut } from '../lib/auth/sign-out-flow.ts';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');

function fakes(signOut: () => Promise<{ success: boolean; error?: string }>) {
    const calls: string[] = [];
    return {
        calls,
        deps: {
            signOut,
            push: (p: string) => calls.push(`push:${p}`),
            refresh: () => calls.push('refresh'),
            notifyError: (t: string, d: string) => calls.push(`error:${t}|${d}`),
        },
    };
}

describe('runSignOut', () => {
    it('éxito: navega a /sign-in y refresca', async () => {
        const f = fakes(async () => ({ success: true }));
        assert.equal(await runSignOut(f.deps), true);
        assert.deepEqual(f.calls, ['push:/sign-in', 'refresh']);
    });
    it('fallo: no navega y avisa con el error', async () => {
        const f = fakes(async () => ({ success: false, error: 'boom' }));
        assert.equal(await runSignOut(f.deps), false);
        assert.deepEqual(f.calls, ['error:No se pudo cerrar la sesión|boom']);
    });
    it('excepción: no navega y avisa', async () => {
        const f = fakes(async () => { throw new Error('network'); });
        assert.equal(await runSignOut(f.deps), false);
        assert.equal(f.calls.length, 1);
        assert.match(f.calls[0], /^error:No se pudo cerrar la sesión/);
    });
    it('el dropdown usa runSignOut y signOut no devuelve inglés', () => {
        assert.match(readFileSync(join(root, 'components/UserDropdown.tsx'), 'utf8'), /runSignOut\(/);
        assert.ok(!readFileSync(join(root, 'lib/actions/auth.actions.ts'), 'utf8').includes('Unable to sign out'));
    });
});
