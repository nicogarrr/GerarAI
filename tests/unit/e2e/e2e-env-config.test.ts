import { readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

import { DEFAULT_E2E_REDIS_URL, e2eUiBackendPort, e2eUiDatabasePath } from '../../../e2e/fixtures/e2e-env';

/**
 * Los e2e deben poder correr fuera del layout de CI (otra máquina, otro puerto,
 * otra BD): backend, BD y python salen de e2e/fixtures/e2e-env.ts, no de
 * literales repetidos en cada spec (la medición del 30-oct tuvo 19 rojos de
 * entorno por eso).
 */
const root = path.resolve(__dirname, '../../..');

function tsFiles(dir: string): string[] {
    return readdirSync(dir).flatMap((name) => {
        const full = path.join(dir, name);
        if (statSync(full).isDirectory()) return tsFiles(full);
        return /\.(ts|mts|mjs)$/.test(name) ? [full] : [];
    });
}

const files = [...tsFiles(path.join(root, 'e2e')), path.join(root, 'playwright.config.ts')].filter(
    (file) => !file.endsWith(path.join('e2e', 'fixtures', 'e2e-env.ts')),
);

describe('e2e configurables por entorno', () => {
    it.each([
        ['backend :8100 fijo', /127\.0\.0\.1:8100/],
        ['ruta de la BD e2e fija', /cavaai_ui_e2e\.db["'`]/],
        ['python3 del sistema fijo', /execFileSync\(\s*["']python3?["']/],
        ['capturas en /downloads (no existe fuera de CI)', /["'`]\/downloads\//],
    ])('ningún spec usa %s', (_label, pattern) => {
        const offenders = files.filter((file) => pattern.test(readFileSync(file, 'utf8'))).map((file) => path.relative(root, file));
        expect(offenders).toEqual([]);
    });

    it('la BD sale de E2E_UI_DATABASE_URL, relativa a data-engine como la lee el backend', () => {
        expect(e2eUiDatabasePath('sqlite:///./cavaai_ui_e2e.db', '/repo')).toBe('/repo/data-engine/cavaai_ui_e2e.db');
        expect(e2eUiDatabasePath('sqlite:////tmp/e2e/ui.db', '/repo')).toBe('/tmp/e2e/ui.db');
        expect(() => e2eUiDatabasePath('postgresql://x/y', '/repo')).toThrow(/sqlite/);
    });

    it('los backends e2e reciben REDIS_URL de E2E_REDIS_URL (por defecto el Redis de servicio de CI)', () => {
        const config = readFileSync(path.join(root, 'playwright.config.ts'), 'utf8');
        const backends = config.split(/command:\s*`\$\{pythonBin\} -m uvicorn/).slice(1);
        expect(backends).toHaveLength(2);
        for (const block of backends) expect(block.split('url:')[0]).toMatch(/REDIS_URL:\s*E2E_REDIS_URL/);
        expect(DEFAULT_E2E_REDIS_URL).toBe('redis://localhost:6379/0');
    });

    it('el puerto del backend sale de E2E_UI_BACKEND_URL', () => {
        expect(e2eUiBackendPort('http://127.0.0.1:8981')).toBe('8981');
        expect(e2eUiBackendPort('http://127.0.0.1:8100')).toBe('8100');
    });
});
