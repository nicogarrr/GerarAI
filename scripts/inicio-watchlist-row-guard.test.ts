// Guard: las filas de la watchlist de Inicio no llevan icono decorativo de
// tendencia (el % ya da el signo y el color) y el nombre no se recorta a 140px
// en móvil, para que "Georgia Capital PLC" no salga como "Georgia Ca…".
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const SRC = readFileSync('components/PersonalizedOverview.tsx', 'utf8');

test('la fila de watchlist no repite la tendencia en un icono', () => {
    assert.ok(!SRC.includes('TrendingDown'));
    assert.ok(!SRC.includes('TrendingUp'));
});

test('el nombre de la empresa no tiene ancho máximo fijo', () => {
    assert.ok(!SRC.includes('max-w-[140px]'));
});
