/**
 * F392: si falla la consulta de 2FA, la página de seguridad no debe mostrar
 * "2FA desactivado" (estado falso); debe mostrar un estado "no disponible".
 * Ejecución: node --experimental-strip-types --test scripts/two-factor-unavailable-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
// El aviso vive en es/security.json: solo se añade la sección de la página.
const page = readFileSync(join(root, 'app/(root)/security/page.tsx'), 'utf8')
    + JSON.stringify(JSON.parse(readFileSync(join(root, 'lib/i18n/messages/es/security.json'), 'utf8')).page);

describe('página de seguridad: estado de 2FA', () => {
    it('no convierte un fallo de consulta en "desactivado"', () => {
        assert.ok(!page.includes('status.success ? Boolean(status.enabled) : false'));
        assert.match(page, /two-factor-unavailable/);
        assert.match(page, /No se pudo comprobar/);
    });
});
