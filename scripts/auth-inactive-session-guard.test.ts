/**
 * Guard: una sesión de cuenta inactiva (pending/rejected) no produce un bucle
 * de redirects entre el shell de auth y el panel.
 *
 * Caso real: cuenta aprobada que después se rechaza conserva su sesión viva
 * (el rechazo no revoca sesiones; solo bloquea el sign-in nuevo). Sin este
 * contrato: /inicio → 403 → /sign-in → (auth)/layout ve sesión → /inicio → …
 * hasta ERR_TOO_MANY_REDIRECTS, sin poder ni cerrar sesión.
 *
 * Ejecución: node --experimental-strip-types --test scripts/auth-inactive-session-guard.test.ts
 * (lo descubre run-guards.mjs por glob).
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const authLayout = readFileSync('app/(auth)/layout.tsx', 'utf8');
const rootLayout = readFileSync('app/(root)/layout.tsx', 'utf8');

describe('cuenta inactiva con sesión viva: sin bucle de redirects', () => {
    it('el shell de auth solo redirige a /inicio si la cuenta está activa', () => {
        assert.match(authLayout, /import \{ isAccountActive \} from "@\/lib\/auth\/account-approval"/);
        assert.match(authLayout, /session\?\.user && isAccountActive\(accountStatus\)/);
    });
    it('el panel enruta pending/rejected a la pantalla de estado, no a /sign-in', () => {
        assert.match(rootLayout, /error\.code === ACCOUNT_PENDING_CODE \|\| error\.code === ACCOUNT_REJECTED_CODE/);
        assert.match(rootLayout, /cuentaPendienteHref\(error\.code === ACCOUNT_REJECTED_CODE \? 'rechazada' : 'pendiente'\)/);
    });
    it('isAccountActive rechaza pending y rejected (contrato puro)', async () => {
        // @ts-expect-error TS5097: node --experimental-strip-types exige la extensión.
        const { isAccountActive } = await import('../lib/auth/account-approval.ts');
        assert.equal(isAccountActive('rejected'), false);
        assert.equal(isAccountActive('pending'), false);
        assert.equal(isAccountActive('approved'), true);
        assert.equal(isAccountActive(undefined), true); // cuentas abuelas sin campo
    });
});
