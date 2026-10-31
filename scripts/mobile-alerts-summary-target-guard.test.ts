import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import assert from 'node:assert/strict';

// El <summary> "Ver original" de las alertas activadas es un control táctil:
// en móvil debe reservar 44px reales de altura (WCAG 2.5.5) y puede volver a
// 40px en escritorio.
test('guard móvil: área táctil del summary "Ver original" (AlertsManager)', () => {
  const source = readFileSync('components/alerts/AlertsManager.tsx', 'utf8');
  const match = source.match(/<summary\s+className="([^"]+)"/);
  assert.ok(match, 'no se encontró el <summary> con className');
  const classes = match[1];
  assert.ok(
    /\bmin-h-11\b/.test(classes) && /\bsm:min-h-10\b/.test(classes),
    `<summary> sin min-h-11 móvil + sm:min-h-10: ${classes}`,
  );
});
