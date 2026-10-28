/**
 * Superficie única de error en el buscador global (hallazgo designer,
 * 2026-10-21): un fallo de búsqueda o de carga de populares mostraba A LA
 * VEZ el indicador inline (role="alert" dentro de la paleta) y un toast.
 * La superficie correcta es la inline - es donde está la atención, ya dice
 * «Inténtalo de nuevo» y reintentar es seguir escribiendo. Los toasts se
 * reservan a mutaciones (convención alerts-load-error-guard).
 * Ejecución: node --experimental-strip-types --test scripts/search-error-single-surface-guard.test.ts
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync('components/SearchCommand.tsx', 'utf8') + readFileSync('components/SearchCommandDialog.tsx', 'utf8');

void test('los fallos de carga del buscador no disparan toast (superficie única inline)', () => {
    assert.doesNotMatch(source, /showErrorToast/, 'el error de búsqueda ya se muestra inline; el toast duplicaba');
});

void test('el estado de error inline se conserva en las dos vías de fallo', () => {
    // Vía 1: excepción en la búsqueda; vía 2: fallo al cargar populares.
    // Ambas deben seguir activando el indicador (F215: error != lista vacía).
    const activaciones = source.match(/setSearchError\(true\)/g) ?? [];
    assert.ok(activaciones.length >= 2, `setSearchError(true) aparece ${activaciones.length} veces, esperadas >= 2`);
    assert.ok(source.includes("result.status === 'error'"), 'el fallo de proveedor sin excepción también se señala');
});

void test('la superficie inline sigue siendo un role="alert" con copy de reintento', () => {
    assert.match(source, /role="alert"/);
    assert.match(source, /No se pudo completar la búsqueda\. Inténtalo de nuevo\./);
});
