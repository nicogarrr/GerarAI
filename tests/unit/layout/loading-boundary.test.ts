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

    // Desde «share accessible route loading shell» (b8472dd34) el aviso
    // role="status", aria-busy y el aria-hidden del esqueleto viven en
    // LoadingShell; el esqueleto genérico tiene que seguir usándolo.
    it('el esqueleto genérico se anuncia a lectores de pantalla y no inventa datos', async () => {
        const { readFileSync } = await import('node:fs');
        const source = readFileSync(join(ROOT, 'loading.tsx'), 'utf8');
        expect(source).toContain('<LoadingShell');
        expect(source).toContain("label={ti('common.states.loading')}");

        const { createElement } = await import('react');
        const { render, screen } = await import('@testing-library/react');
        const { LoadingShell } = await import('@/components/ui/loading-shell');
        const { container } = render(createElement(LoadingShell, { label: 'Cargando…', className: 'x', children: createElement('p', null, 'esqueleto') }));
        expect(screen.getByRole('status')).toHaveTextContent('Cargando…');
        expect(container.querySelector('main')).toHaveAttribute('aria-busy', 'true');
        expect(screen.getByText('esqueleto').parentElement).toHaveAttribute('aria-hidden', 'true');
    });
});
