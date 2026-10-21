/**
 * Al pasar de credenciales al paso 2FA, React reutilizaba el <input> del email
 * para el código (mismo tipo y posición) y el campo "Código de autenticación"
 * aparecía relleno con el email (visto en prod, 21 oct). Cada paso lleva su `key`.
 * Ejecución: node --experimental-strip-types --test scripts/sign-in-step-keys-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const page = readFileSync(join(root, 'app/(auth)/sign-in/page.tsx'), 'utf8');

describe('sign-in: pasos con key propia', () => {
    it('credenciales y 2FA no comparten nodos DOM', () => {
        assert.match(page, /<React\.Fragment key="two-factor">/);
        assert.match(page, /<React\.Fragment key="credentials">/);
    });
});
