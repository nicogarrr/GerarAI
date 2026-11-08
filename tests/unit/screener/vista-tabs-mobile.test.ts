import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

// Guardia de regresión: a 390 px las pestañas de vistas del screener
// (Empresas/Subidas/Bajadas/Activas/Régimen) desbordaban 140 px con scroll
// oculto y la 4ª salía cortada ("Acti…"). El patrón del repo para esto es
// flex-wrap + diana táctil de 44 px (ver LiveMarketsPanel, fix del 21-oct).
const SOURCE = readFileSync('app/(root)/screener/page.tsx', 'utf8');

describe('pestañas de vistas del screener en móvil', () => {
    it('el nav envuelve en vez de cortar con scroll oculto', () => {
        const nav = SOURCE.match(/<nav aria-label=\{t\('screener\.vistasAria'\)\} className="([^"]+)"/);
        expect(nav, 'nav de vistas encontrado').toBeTruthy();
        expect(nav![1]).toContain('flex-wrap');
        expect(nav![1]).not.toContain('flex-nowrap');
        expect(nav![1]).not.toContain('overflow-x-auto');
    });

    it('cada pestaña es una diana táctil de 44 px', () => {
        const vistasBlock = SOURCE.slice(SOURCE.indexOf('screener.vistasAria'), SOURCE.indexOf('</nav>', SOURCE.indexOf('screener.vistasAria')));
        expect(vistasBlock).toContain('min-h-11');
        expect(vistasBlock).not.toContain('min-h-[36px]');
    });
});
