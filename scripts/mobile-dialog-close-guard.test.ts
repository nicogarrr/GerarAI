import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

/**
 * Guard: el botón de cierre de TODOS los diálogos (ui/Dialog) era solo el
 * icono X de 16 px (16x16 de objetivo táctil a 390 px, 31-oct-2026). El
 * ::before lo amplía a ~44 px sin mover el icono ni cambiar nada visible.
 */

test('el cierre de los diálogos tiene área táctil de 44 px sin cambiar lo visible', () => {
    const src = readFileSync('components/ui/dialog.tsx', 'utf8');
    // El botón de cierre es la ocurrencia que lleva la posición absoluta (la
    // primera data-slot="dialog-close" es el wrapper DialogClose sin clases).
    const anchor = src.indexOf("absolute top-4 right-4");
    assert.ok(anchor > 0, 'botón de cierre presente');
    const close = src.slice(Math.max(0, anchor - 400), anchor + 700);
    assert.ok(close.includes("before:absolute before:-inset-3.5 before:content-['']"), 'cierre sin área táctil ampliada');
    assert.ok(close.includes("absolute top-4 right-4"), 'posición del cierre conservada');
});
