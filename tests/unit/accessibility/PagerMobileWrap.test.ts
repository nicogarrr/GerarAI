/**
 * Auditoría 18-nov-2026 (P24, medido en prod a 320 px): el paginador Pager
 * (compartido por RecordViews, ChangesFeed, ExpectationsList, DocumentsList
 * y PagedInsiderCompanies) desbordaba 17 px por la derecha
 * (document.documentElement.scrollWidth = 337; el botón «Siguiente» acababa
 * en x=337). Causa: fila flex sin wrap con dos botones min-h-11 px-4 y el
 * texto «Página 1 de 5 · 127 Registros» irrompible (whitespace-nowrap).
 *
 * Fix: el texto pasa a su propia línea en móvil (order-first w-full,
 * min-w-0) y la fila admite wrap; desde sm se conserva la fila única.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

const ROOT = join(__dirname, '..', '..', '..');

describe('Pager: la fila de paginación no desborda a 320 px', () => {
    const source = readFileSync(join(ROOT, 'components/research/Pager.tsx'), 'utf8');

    it('el nav admite wrap y el texto ocupa su propia línea en móvil', () => {
        expect(source).toContain('flex flex-wrap items-center justify-between gap-x-3 gap-y-2');
        expect(source).toContain('order-first w-full min-w-0 text-center text-xs text-gray-400 sm:order-none sm:w-auto');
    });

    it('la fila rígida anterior no vuelve', () => {
        expect(source).not.toContain('mt-4 flex items-center justify-between gap-3');
    });

    it('los botones conservan el tap target de la casa (min-h-11, ritmo denso en sm)', () => {
        expect(source).toContain('min-h-11');
        expect(source).toContain('sm:min-h-9');
    });
});
