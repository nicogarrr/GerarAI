import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { test } from 'node:test';
test('salud de datos conserva ruta pero no está en catálogo de navegación', () => {
  const nav = readFileSync('lib/constants.ts', 'utf8');
  assert.ok(!nav.includes("href: '/research/data-health'"));
  assert.ok(existsSync('app/(root)/research/data-health/page.tsx'));
});
