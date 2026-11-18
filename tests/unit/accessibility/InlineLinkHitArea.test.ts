import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

// Zona táctil de los enlaces inline (auditoría móvil 18-nov-2026 sobre prod,
// viewport 390x844): en /watchlist había 169 objetivos <44 px (152 enlaces de
// evidencia «métrica: valor» a SEC a 14 px en ValuationSummaryGrid y 16
// tickers a 20 px en New13fSection), en /temas 23 (gastadores del flujo a
// 16 px y enlace del cuello a 14 px) y en /screener 10 (nombre de empresa a
// 20 px; el ticker ya era min-h-[44px]).
//
// Dos patrones según el paso de la lista:
// - Paso >= ~36 px o tarjeta acolchada: pseudo-elemento before:-inset-3.5
//   (48/44 px efectivos sin tocar el layout), el mismo de DcaLevelBadge y
//   NewsSection.
// - Paso denso (<28 px): 44 px solaparía la fila vecina; se agranda la fila
//   real a 32 px (min-h-8) o el padding propio (-my-1.5/py-1.5): >=24 px de
//   WCAG 2.5.8 sin solapes.

const src = (p: string) => readFileSync(p, 'utf8');

describe('zona táctil de enlaces inline', () => {
    it('los tickers de nuevas posiciones 13F de la watchlist llegan a 32 px sin cambiar el ritmo', () => {
        const s = src('components/watchlist/New13fSection.tsx');
        expect(s).toContain('className="-my-1.5 shrink-0 py-1.5 font-mono text-sm font-bold text-gray-200"');
    });

    it('el nombre de empresa del screener amplía su zona con el pseudo-elemento (mismo destino que el ticker)', () => {
        const s = src('app/(root)/screener/page.tsx');
        expect(s).toMatch(/text-gray-300 before:absolute before:-inset-3\.5/);
    });

    it('los enlaces del flujo de /temas (gastadores y cuello) amplían su zona con el pseudo-elemento', () => {
        expect(src('app/(root)/temas/_components/ThemeFlow.tsx')).toMatch(/text-teal-300 before:absolute before:-inset-3\.5/);
        expect(src('app/(root)/temas/page.tsx')).toMatch(/text-teal-300 underline before:absolute before:-inset-3\.5/);
    });

    it('los tickers de exposición del flujo de /temas son chips reales de 44 px, SIN pseudo-expansión (Auditoría 18-nov: el halo -inset-x-1.5 solapaba 5,33 px entre tickers seguidos)', () => {
        const s = src('app/(root)/temas/_components/ThemeFlow.tsx');
        // Mismo patrón que HoldingsLines de la propia página: caja real
        // min-h-11 min-w-11, separador fuera del enlace, nada que solapar.
        const chips = s.match(/className="inline-flex min-h-11 min-w-11 items-center justify-center font-semibold text-teal-300 hover:text-teal-200"/g) ?? [];
        expect(chips).toHaveLength(2);
        // Ni la clase antigua sin expandir ni NINGÚN inset horizontal en este archivo.
        expect(s).not.toContain('className="font-semibold text-teal-300 hover:text-teal-200"');
        expect(s).not.toContain('-inset-x-1.5');
        expect(s).not.toContain('before:inset-x-0');
    });

    it('el enlace SEDI del feed insider (14 px en prod) amplía su zona inline a 34 px', () => {
        // Medido en prod: 21 px libres hasta el enlace de importe y sin solape
        // en x, así que la expansión -inset-y-2.5/-x-1.5 no toca a nadie.
        expect(src('components/insider/InsiderFeed.tsx')).toContain(
            "className=\"relative underline before:absolute before:-inset-x-1.5 before:-inset-y-2.5 before:content-[''] hover:text-teal-300\"",
        );
    });

    it('los cobradores del flujo de /temas amplían su zona con el pseudo-elemento (20 px medidos en prod, 18-nov)', () => {
        const s = src('app/(root)/temas/_components/ThemeFlow.tsx');
        expect(s).toMatch(/relative text-sm font-semibold text-teal-300 before:absolute before:-inset-3\.5/);
        expect(s).not.toContain('className="text-sm font-semibold text-teal-300 hover:text-teal-200"');
    });

    it('cada evidencia de valoración enlaza a su fuente con la fila entera a 32 px, sin solapar vecinas', () => {
        const s = src('components/research/ValuationSummaryGrid.tsx');
        expect(s).toContain('className="-mx-1 flex min-h-8 w-full items-center rounded px-1 underline"');
        // El caso sin URL de fuente mantiene el mismo ritmo de fila (no interactivo).
        expect(s).toContain('className="flex min-h-8 items-center"');
        // Nada de pseudo-expansión en esta lista densa: solaparía la fila vecina.
        expect(s).not.toContain('underline before:-inset');
    });
});
