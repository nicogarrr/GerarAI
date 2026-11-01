/**
 * Guarda F148: «Avisar de nuevas coincidencias» al guardar un filtro debe ser
 * opt-in real: desmarcado por defecto. Premarcarlo activaba avisos
 * involuntarios al guardar una consulta.
 *
 * Ejecución: node --experimental-strip-types --test scripts/screener-alert-optin-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');
const src = readFileSync(join(root, 'app/(root)/screeners/page.tsx'), 'utf8') + JSON.stringify(JSON.parse(readFileSync(join(root, 'lib/i18n/messages/es/screener.json'), 'utf8')).screens);

describe('screener alert opt-in guard (F148)', () => {
    it('el checkbox alerts_enabled NO viene premarcado', () => {
        const line = src.split('\n').find((l) => l.includes('alerts_enabled'));
        assert.ok(line, 'debe existir el checkbox alerts_enabled');
        assert.ok(!line.includes('defaultChecked'), 'opt-in premarcado: guardar un filtro activaría avisos involuntarios');
        assert.ok(!line.includes('checked'), 'sin checked controlado por defecto');
    });
});
