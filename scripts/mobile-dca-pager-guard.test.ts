import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

/**
 * Guard: el pager del histórico DCA nunca solapa el texto con los botones
 * (medido a 390px, 2026-10-31). Con grid-cols-2 y el estado en col-span-2
 * row-start-1 (por debajo de los botones), un histórico largo («2.391-2.400
 * de 2.400 · Página 240 de 240») solapaba 74px sobre Anterior y 83px sobre
 * Siguiente. La pista propia (auto 1fr auto) deja el texto envolver sin
 * invadir los botones; el caso típico sigue en una fila.
 */

test('pager DCA: estado en su propia pista, sin col-span bajo los botones', () => {
    const src = readFileSync('components/watchlist/DcaAlertSettingsList.tsx', 'utf8');
    assert.ok(src.includes('grid-cols-[auto_1fr_auto]'), 'nav con pista propia para el estado');
    const nav = src.slice(src.indexOf('Paginación del histórico DCA'), src.indexOf('</nav>'));
    assert.ok(!nav.includes('col-span-2 row-start-1'), 'sin col-span-2 row-start-1 en el estado');
    assert.ok(nav.includes('min-w-0 text-center'), 'estado con min-w-0 para envolver');
});
