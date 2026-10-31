import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

/**
 * Guard: el × de quitar la revisión en el panel del Cerebro tiene área
 * táctil de 44px (medido con elementFromPoint a 390px, 2026-10-31).
 * La caja real es 10x16px; el pseudo-elemento invisible la amplía a
 * 44+ en las cuatro direcciones (convención de la casa para chips).
 */

test('× quitar revisión del Cerebro con área táctil invisible 44px', () => {
    const src = readFileSync('components/brain/GlobalBrainPanel.tsx', 'utf8');
    const i = src.indexOf('removeReviewAria');
    assert.ok(i >= 0, 'botón quitar revisión existe');
    const btn = src.slice(i, src.indexOf('</button>', i));
    assert.ok(btn.includes('before:absolute'), '× con pseudo-elemento de área');
    assert.ok(btn.includes('before:-inset-x-5'), 'área horizontal ≥44px');
    assert.ok(btn.includes('before:-inset-y-4'), 'área vertical ≥44px');
});
