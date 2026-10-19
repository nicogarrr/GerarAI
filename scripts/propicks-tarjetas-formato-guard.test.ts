// Guard: las tarjetas de Selección IA no mezclan formatos (73.2 vs 17,5 %)
// y el nombre de empresa pasa por formatCompanyName (casing SEC crudo no).
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const SRC = readFileSync('components/proPicks/EnhancedProPicksContent.tsx', 'utf8');

test('scores y nombre de empresa usan los formatos compartidos', () => {
    assert.ok(SRC.includes('formatNumber(display.value'), 'score de categoría sin formatNumber');
    assert.ok(SRC.includes('formatNumber(pick.score'), 'puntuación general sin formatNumber');
    assert.ok(SRC.includes('formatCompanyName(pick.company)'), 'nombre de empresa sin formatCompanyName');
    assert.ok(!SRC.includes('{display.value}</div>'), 'score crudo con punto decimal');
});
