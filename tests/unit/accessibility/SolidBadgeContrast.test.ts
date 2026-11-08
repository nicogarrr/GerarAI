import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'path';

import { describe, expect, it } from 'vitest';

// Contraste de insignias sólidas (WCAG 2.2 SC 1.4.3, texto < 18 px pide 4,5:1).
// Regresión medida con la fórmula WCAG sobre los hex del tema
// (app/globals.css @theme) y la escala por defecto de Tailwind:
// - ProPicks: nota «A/B/C…» en blanco sobre bg-green-500 (2,28:1),
//   bg-teal-500 (3,74:1 con el #0d9488 del tema) y bg-yellow-500 (2,15:1);
//   insignia «joya» en blanco sobre gradiente teal-500->emerald-500.
//   Tinta gray-900 (#0a0a0b): 5,29-9,21:1. Aprueba.
// Blanco sí aprueba sobre sólidos oscuros (bg-red-600 = 4,83:1), así que la
// regla solo cubre los tonos claros 300-500.

const ROOTS = ['components', 'app'];
const TSX: string[] = [];
function walk(dir: string) {
    for (const entry of readdirSync(dir)) {
        const p = join(dir, entry);
        if (statSync(p).isDirectory()) walk(p);
        else if (p.endsWith('.tsx')) TSX.push(p);
    }
}
for (const root of ROOTS) walk(root);

// Fondo sólido claro: bg- o parada de gradiente from-/via-/to- en tono
// 300-500, sin alfa `/xx` (el alfa ya lo aclara sobre el fondo oscuro).
// Chequeos simples (includes + regex acotada): una sola regex con
// cuantificadores perezosos anidados sufría backtracking catastrófico.
const BRIGHT_SOLID =
    /(?:^|\s)(?:bg|from|via|to)-(?:green|teal|yellow|amber|orange|emerald|lime|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|red)-(?:300|400|500)(?![\d/])/;

describe('insignias sólidas: tinta con contraste AA', () => {
    it('ningún texto blanco sobre fondo sólido claro (300-500) en componentes ni páginas', () => {
        const offenders: string[] = [];
        for (const file of TSX) {
            const src = readFileSync(file, 'utf8');
            // Por bloques de className: el emparejamiento debe darse en la
            // misma cadena de clases, no en cualquier punto del archivo.
            for (const match of src.matchAll(/className=(?:"([^"]*)"|'([^']*)'|\{`([^`]*)`\})/g)) {
                const classes = match[1] ?? match[2] ?? match[3] ?? '';
                if (classes.includes('text-white') && BRIGHT_SOLID.test(classes)) {
                    offenders.push(`${file}: ${classes.slice(0, 120)}`);
                }
            }
        }
        expect(offenders).toEqual([]);
    });

    it('las notas de ProPicks usan tinta gray-900 sobre el sólido', () => {
        const src = readFileSync('components/proPicks/EnhancedProPicksContent.tsx', 'utf8');
        const grade = src.match(/const getGradeColor[\s\S]*?\};/);
        expect(grade).not.toBeNull();
        expect(grade![0]).not.toContain('text-white');
        for (const bg of ['bg-green-500', 'bg-teal-500', 'bg-yellow-500']) {
            expect(grade![0]).toContain(`${bg} text-gray-900`);
        }
    });
});
