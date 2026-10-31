import assert from 'node:assert';
import { readFileSync } from 'node:fs';
import test from 'node:test';

/**
 * Guard: EmptyState (compartido por todas las pantallas) debe romper tokens
 * largos sin espacios. Sin break-words, pegar una URL como término de
 * búsqueda («Sin coincidencias para «https://…»») desbordaba la página 81px
 * a 390px (medido 2026-10-31: scrollWidth 471 vs 390).
 */

test('EmptyState rompe tokens largos (título y descripción)', () => {
    const src = readFileSync('components/ui/empty-state.tsx', 'utf8');
    const title = src.slice(src.indexOf('React.createElement('), src.indexOf('{description}'));
    assert.ok(title.includes("cn('break-words text-base font-semibold"), 'título con break-words');
    assert.ok(src.includes('max-w-xl break-words text-sm text-gray-500'), 'descripción con break-words');
});
