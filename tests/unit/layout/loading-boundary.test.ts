import { existsSync, readdirSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { describe, expect, it } from 'vitest';

const ROOT = 'app/(root)';

function pages(dir: string): string[] {
    return readdirSync(dir).flatMap((name) => {
        const path = join(dir, name);
        if (statSync(path).isDirectory()) return pages(path);
        return name === 'page.tsx' ? [path] : [];
    });
}

/** ¿Hay un loading.tsx en la carpeta de la página o en alguna superior hasta app/(root)? */
function hasLoadingBoundary(page: string): boolean {
    let dir = dirname(page);
    for (;;) {
        if (existsSync(join(dir, 'loading.tsx'))) return true;
        if (dir === ROOT || !dir.startsWith(ROOT)) return false;
        dir = dirname(dir);
    }
}

// UX 30-oct: ~40 pantallas autenticadas (Fiscalidad, Plan, Inversores,
// Calendario, Alertas, Ajustes…) leían del backend en el servidor sin
// ninguna frontera de carga: al tocar el menú no pasaba nada visible hasta
// que llegaba la página entera.
describe('área autenticada: toda pantalla tiene frontera de carga', () => {
    it('cada page.tsx de app/(root) tiene un loading.tsx propio o heredado', () => {
        const missing = pages(ROOT).filter((page) => !hasLoadingBoundary(page));
        expect(missing).toEqual([]);
    });

    it('el esqueleto genérico se anuncia a lectores de pantalla y no inventa datos', async () => {
        const { readFileSync } = await import('node:fs');
        const source = readFileSync(join(ROOT, 'loading.tsx'), 'utf8');
        expect(source).toContain('role="status"');
        expect(source).toContain('aria-busy="true"');
        expect(source).toContain('aria-hidden="true"');
    });
});
