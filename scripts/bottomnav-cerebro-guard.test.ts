// Guard: el Cerebro es una celda más de la barra inferior, no una franja
// apilada que la pisa; el padding del contenido acompaña la altura real.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const NAV = readFileSync('components/layout/BottomNav.tsx', 'utf8');
const LAYOUT = readFileSync('app/(root)/layout.tsx', 'utf8');

test('cerebro integrado en la rejilla, sin franja apilada', () => {
    assert.ok(NAV.includes('grid-cols-6'), 'la rejilla debe tener 6 celdas');
    assert.ok(!NAV.includes('w-full items-center justify-center gap-2 border-b'), 'franja apilada aún presente');
    assert.ok(NAV.includes("gerarai:open-brain"));
    assert.ok(LAYOUT.includes('pb-[calc(4.5rem+env(safe-area-inset-bottom))]'));
});
