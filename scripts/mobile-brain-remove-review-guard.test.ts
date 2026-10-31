import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

/**
 * Guard: el × de quitar la revisión en el panel del Cerebro reserva un
 * área táctil real de 44x44px en móvil (revisión del piloto, 2026-10-31:
 * un pseudo-elemento por encima invadiría los chips vecinos). En sm+
 * vuelve al tamaño compacto (sm:min-h-0 sm:min-w-0).
 */

test('× quitar revisión del Cerebro con área real 44px en móvil', () => {
    const src = readFileSync('components/brain/GlobalBrainPanel.tsx', 'utf8');
    const i = src.indexOf('removeReviewAria');
    assert.ok(i >= 0, 'botón quitar revisión existe');
    const btn = src.slice(i, src.indexOf('</button>', i));
    assert.ok(btn.includes('min-h-11 min-w-11'), '× con área real 44px');
    assert.ok(btn.includes('sm:min-h-0 sm:min-w-0'), '× compacto en sm+');
    assert.ok(!btn.includes('before:'), 'sin pseudo-elemento que invada vecinos');
});
