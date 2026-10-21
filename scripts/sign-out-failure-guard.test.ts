/**
 * Cerrar sesión: si signOut falla no se navega a /sign-in como si hubiera
 * funcionado (la sesión seguiría viva). Se avisa en castellano y se queda.
 * Ejecución: node --experimental-strip-types --test scripts/sign-out-failure-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const dropdown = readFileSync(join(root, 'components/UserDropdown.tsx'), 'utf8');
const actions = readFileSync(join(root, 'lib/actions/auth.actions.ts'), 'utf8');

describe('cerrar sesión', () => {
    it('no navega a /sign-in si signOut falla', () => {
        const fn = dropdown.slice(dropdown.indexOf('handleSignOut'), dropdown.indexOf('return (', dropdown.indexOf('handleSignOut')));
        const failAt = fn.indexOf('!result.success');
        const pushAt = fn.indexOf('router.push("/sign-in")');
        assert.ok(failAt > -1 && pushAt > failAt, 'comprueba el resultado antes de navegar');
        assert.match(fn, /toast\.error\('No se pudo cerrar la sesión'/);
    });
    it('el error de signOut está en castellano', () => {
        assert.ok(!actions.includes('Unable to sign out'));
    });
});
