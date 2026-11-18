/**
 * Auditoría 18-nov-2026: segundo lote de texto de lectura a 11 px, por debajo
 * del suelo de la casa (text-xs / 12 px, guard legible-text-guard de la
 * auditoría 11-nov). Sube a text-xs:
 *
 * - temas: notas, razones, atribución, enlaces y pie de ThemeFlow y
 *   ThemeFundamentals (procedencia y cortes de datos: veracidad legible).
 * - macro-calendar: tag de tipo de documento 8-K.
 * - knowledge: etiqueta de sección (antes 11 px en móvil y text-xs en
 *   escritorio; ahora text-xs en ambos).
 * - ownership/MostBought: aviso ámbar del elemento.
 * - research/AnalystReportView: razón EBITDA N/D, razón de celda, fuente,
 *   alcance de consenso y fórmula (la variante móvil ya estaba en text-xs;
 *   se iguala la de escritorio).
 * - watchlist: leyenda de capitalización, notas de rango y P/E N/D, etiquetas
 *   de columna solo móvil (xl:hidden) y marcador «· derivada».
 *
 * Quedan fuera los marcadores tipográficos (sup «*» de watchlist:727).
 * La etiqueta «Precio» subió a text-xs cuando #5852 quedó sustituido por
 * #5884 (mergeado): el guard queda endurecido a 0 ocurrencias.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

const ROOT = join(__dirname, '..', '..', '..');

function src(path: string): string {
    return readFileSync(join(ROOT, path), 'utf8');
}

const FILES_SIN_11PX = [
    'app/(root)/temas/_components/ThemeFlow.tsx',
    'app/(root)/temas/_components/ThemeFundamentals.tsx',
    'app/(root)/macro-calendar/page.tsx',
    'app/(root)/knowledge/page.tsx',
    'app/(root)/ownership/_components/MostBought.tsx',
    'components/research/AnalystReportView.tsx',
];

describe('texto legible lote 11 px: nada de lectura bajo 12 px', () => {
    it.each(FILES_SIN_11PX)('%s no tiene texto a 11 px', (path) => {
        expect(src(path)).not.toContain('text-[11px]');
    });

    it('watchlist no conserva ninguna ocurrencia a 11 px', () => {
        const s = src('app/(root)/watchlist/page.tsx');
        const occurrences = s.match(/text-\[11px\]/g) ?? [];
        expect(occurrences).toHaveLength(0);
    });

    it('watchlist: la etiqueta de columna «Precio» (xl:hidden) va a 12 px', () => {
        const s = src('app/(root)/watchlist/page.tsx');
        expect(s).toContain('text-xs font-normal text-gray-500 xl:hidden">{t(\'watchlist.page.sort.price\')}');
    });

    it('knowledge etiqueta de sección a text-xs sin variante sm redundante', () => {
        const s = src('app/(root)/knowledge/page.tsx');
        expect(s).toContain('text-xs font-semibold uppercase leading-tight tracking-wide text-gray-500');
        expect(s).not.toContain('sm:text-xs');
    });

    it('macro-calendar sube el tag 8-K a text-xs', () => {
        expect(src('app/(root)/macro-calendar/page.tsx')).toContain('rounded bg-gray-800 px-1.5 py-0.5 text-xs text-gray-300');
    });

    it('AnalystReportView iguala fuente y alcance de consenso a text-xs', () => {
        const s = src('components/research/AnalystReportView.tsx');
        expect(s).toContain("'block text-xs text-gray-500'");
        const reachLine = s.split('\n').find((line) => line.includes('consensus-base-rate-reach')) ?? '';
        expect(reachLine).toContain('text-xs');
    });

    it('watchlist mantiene el sup «*» a 10 px como marcador tipográfico', () => {
        expect(src('app/(root)/watchlist/page.tsx')).toContain('ml-0.5 font-sans text-[10px] text-gray-500');
    });
});
