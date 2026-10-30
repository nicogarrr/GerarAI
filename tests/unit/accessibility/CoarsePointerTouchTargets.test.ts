import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const src = (p: string) => readFileSync(p, 'utf8');

// Objetivos tactiles en movil (>= 44 px). Medido en Pixel 7 sobre main:
// el <summary> «Fechas, caja por divisa e historial» de Cartera medía 20 px de
// alto y el «Ver todo» del calendario de Inicio 20 px.
describe('objetivos tactiles con puntero grueso', () => {
    it('los <summary> sin padding propio crecen a 44 px solo en movil', () => {
        const css = src('app/globals.css');
        const block = css.match(/@media \(pointer: coarse\) \{\s*summary \{([^}]*)\}/);
        expect(block, 'falta la regla de summary para puntero grueso').not.toBeNull();
        expect(block![1]).toContain('padding-block: 0.75rem');
        // En la capa base: un py-*/min-h-* del componente (capa utilities) sigue mandando.
        const base = css.indexOf('@layer base');
        const rule = css.indexOf('@media (pointer: coarse)');
        expect(base).toBeGreaterThan(-1);
        expect(rule).toBeGreaterThan(base);
        expect(css.slice(base, rule)).not.toMatch(/@layer utilities/);
    });

    it('el «Ver todo» del calendario de Inicio tiene 44 px de alto', () => {
        expect(src('components/calendar/EarningsDayStrip.tsx')).toMatch(/href="\/calendar\/resultados" className="inline-flex min-h-11 items-center/);
    });

    it('el foco no queda tapado por la barra inferior fija en movil (WCAG 2.4.11)', () => {
        const css = src('app/globals.css');
        expect(css).toMatch(/@media \(max-width: 47\.99rem\) \{\s*html:has\(nav\[data-bottom-nav\]\) \{\s*scroll-padding-bottom: calc\(4\.5rem \+ env\(safe-area-inset-bottom\)\);/);
        const nav = src('components/layout/BottomNav.tsx');
        expect(nav).toContain('data-bottom-nav');
        // La barra solo existe por debajo de md: el hueco no debe aplicarse en escritorio.
        expect(nav).toContain('md:hidden');
    });
});
