import { readFileSync } from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';

// Bugs vistos por Nico en prod (31-oct-2026):
// 1. Watchlist: chip «1X DCA ·» con el separador colgando (DcaLevelBadge).
// 2. Inicio: chip «2X DCA (provisional)» tapando el importe en las filas de
//    pesos a 390px (la columna flex-1 se encogía bajo el mínimo del chip).
test('guard: DcaLevelBadge no pinta el separador «·» sin texto detrás', () => {
  const src = readFileSync('components/watchlist/DcaLevelBadge.tsx', 'utf8');
  assert.ok(
    !/>\s*·\s*<\//.test(src) && !/">·<\//.test(src),
    'DcaLevelBadge vuelve a tener un «·» colgando tras el nivel',
  );
});

test('guard: el importe de la fila de pesos envuelve junto al símbolo (PersonalizedOverview)', () => {
  const src = readFileSync('components/PersonalizedOverview.tsx', 'utf8');
  assert.ok(
    src.includes('flex flex-wrap items-center justify-between gap-x-3 gap-y-1'),
    'falta la fila símbolo+importe que envuelve (el chip vuelve a poder tapar el importe)',
  );
  assert.ok(
    !src.includes('ml-auto text-right font-mono text-gray-300'),
    'el importe volvió a ser hermano ml-auto de la columna del chip (solape a 390px)',
  );
});
