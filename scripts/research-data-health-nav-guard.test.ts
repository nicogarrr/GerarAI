import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

// Decisión de Nico (2026-10-20): /research/data-health se elimina ENTERA
// (diagnóstico interno, no pantalla de producto). El guard ahora fija que la
// ruta no existe y que la navegación sigue sin enlazarla.
test('data-health no existe ni como ruta ni en la navegación', () => {
    const nav = fs.readFileSync('lib/constants.ts', 'utf8');
    assert.ok(!nav.includes("href: '/research/data-health'"));
    assert.ok(!fs.existsSync('app/(root)/research/data-health/page.tsx'));
});
