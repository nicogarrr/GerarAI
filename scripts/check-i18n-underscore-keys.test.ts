/**
 * Guard del propio check-i18n: las claves con guion bajo se comprueban igual
 * que las camelCase.
 *
 * Por qué: la forma de clave del checker era `[A-Za-z0-9]` por segmento, así que
 * `t('area.exit_multiple')` con typo no se detectaba y una clave con guion
 * bajo que llegaba a t() por un mapa tipado se contaba como huérfana NUEVA
 * (fallo falso); r5-tesis2 tuvo que renombrar dos claves a camelCase para
 * pasar el gate. Tampoco se miraba `t("…")` con comillas dobles.
 *
 * Cada caso monta un repo mínimo en un directorio temporal y ejecuta el
 * checker real con ese directorio como raíz (usa process.cwd()).
 *
 * Ejecución: node --experimental-strip-types --test scripts/check-i18n-underscore-keys.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

const CHECKER = resolve('scripts/check-i18n.mjs');

const ES = { ok_key: 'Hola', viaMap: { exit_multiple: 'Múltiplo de salida' } };
const EN = { ok_key: 'Hello', viaMap: { exit_multiple: 'Exit multiple' } };

function runFixture(page: string): { status: number | null; out: string } {
    const root = mkdtempSync(join(tmpdir(), 'check-i18n-'));
    try {
        for (const dir of ['app', 'components', 'hooks', 'lib/i18n/messages/es', 'lib/i18n/messages/en', 'scripts']) {
            mkdirSync(join(root, dir), { recursive: true });
        }
        writeFileSync(join(root, 'lib/i18n/messages/es/demo.json'), JSON.stringify(ES));
        writeFileSync(join(root, 'lib/i18n/messages/en/demo.json'), JSON.stringify(EN));
        writeFileSync(join(root, 'scripts/i18n-hardcoded-baseline.json'), '{}\n');
        writeFileSync(join(root, 'app/page.tsx'), page);
        const r = spawnSync(process.execPath, [CHECKER], { cwd: root, encoding: 'utf8' });
        return { status: r.status, out: `${r.stdout}\n${r.stderr}` };
    } finally {
        rmSync(root, { recursive: true, force: true });
    }
}

const MAP_USE = "const KEYS = { exit: 'demo.viaMap.exit_multiple' } as const;\nexport const b = t(KEYS.exit);\n";

describe('check-i18n: claves con guion bajo', () => {
    it('una clave con guion bajo usada por un mapa tipado NO es huérfana', () => {
        const r = runFixture(`export const a = t('demo.ok_key');\n${MAP_USE}`);
        assert.equal(r.status, 0, r.out);
        assert.match(r.out, /i18n ok:/);
    });

    it('un typo en una clave con guion bajo dentro de t() falla como clave inexistente', () => {
        const r = runFixture(`export const a = t('demo.ok_key');\nexport const c = t('demo.okk_key');\n${MAP_USE}`);
        assert.notEqual(r.status, 0, r.out);
        assert.match(r.out, /clave\(s\) de t\(\) que no existen[\s\S]*demo\.okk_key/);
    });

    it('t("…") con comillas dobles también se comprueba', () => {
        const r = runFixture(`export const a = t("demo.ok_key");\nexport const c = t("demo.viaMap.exit_multipel");\n${MAP_USE}`);
        assert.notEqual(r.status, 0, r.out);
        assert.match(r.out, /clave\(s\) de t\(\) que no existen[\s\S]*demo\.viaMap\.exit_multipel/);
        assert.doesNotMatch(r.out, /sin uso NUEVA[\s\S]*demo\.ok_key/);
    });
});
