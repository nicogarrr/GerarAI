import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

/**
 * Guard: el importe del feed insider no puede desbordar a 390px (medido
 * 2026-10-31: con la rejilla estrecha de la antigua tarjeta móvil, un
 * importe con NBSP de Intl es-ES a partir de ~100M$ desbordaba su celda de
 * 103px). Contrato desde 2026-11-14: tabla responsiva ÚNICA (una fila por
 * operación); en móvil cada celda es un bloque a todo lo ancho, así que la
 * celda estrecha que medimos ya no puede existir. El guard pinea ambos
 * extremos: la fila única en bloques y la ausencia de la rejilla estrecha.
 */

test('feed insider: una fila por operación, celdas a todo lo ancho en móvil', () => {
    const src = readFileSync('components/insider/InsiderFeed.tsx', 'utf8');
    assert.ok(
        src.includes('md:table-cell'),
        'celdas de la fila única: bloque a todo lo ancho en móvil, celda de tabla en md+',
    );
    assert.ok(
        !src.includes('hidden overflow-x-auto md:block'),
        'sin segundo árbol de escritorio: una sola tabla responsiva',
    );
    assert.ok(
        !src.includes('grid grid-cols-2 gap-2 text-sm sm:grid-cols-3'),
        'sin la rejilla estrecha de la antigua tarjeta (origen del desborde medido)',
    );
    assert.ok(
        !src.includes('grid grid-cols-1 gap-3 md:hidden'),
        'sin segundo árbol móvil: una sola tabla responsiva',
    );
});
