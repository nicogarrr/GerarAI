/**
 * Guard de bundle: el diálogo «Generar entregable» de /research carga
 * diferido (next/dynamic) para que el buscador de tickers, los selects y el
 * visor markdown no viajen en el bundle inicial del índice de research.
 * Ejecución: node --experimental-strip-types --test scripts/research-index-lazy-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const button = readFileSync('components/work-products/WorkProductButton.tsx', 'utf8');
const dialog = readFileSync('components/work-products/WorkProductDialog.tsx', 'utf8');

describe('research índice: diálogo de entregable diferido', () => {
    it('el contenido del diálogo carga con dynamic() desde el botón', () => {
        assert.ok(button.includes("import('./WorkProductDialog')"), 'el diálogo debe ser un import dinámico');
        assert.ok(!button.includes('TickerSearchInput'), 'el buscador vive en el diálogo, no en el botón');
        assert.ok(!button.includes('generateWorkProduct'), 'la acción vive en el diálogo, no en el botón');
    });

    it('el chunk se precarga al rozar el gatillo y queda montado tras abrir', () => {
        assert.ok(button.includes('onPointerDown'), 'precarga en pointerdown');
        assert.ok(button.includes('onFocus'), 'precarga en focus');
        assert.ok(button.includes('openedOnce'), 'el botón recuerda la primera apertura');
    });

    it('el diálogo conserva el visor markdown diferido y la etiqueta siempre visible', () => {
        assert.ok(dialog.includes("dynamic(() => import('@/components/research/ThesisMarkdown')"), 'el visor markdown sigue diferido');
        assert.ok(dialog.includes("<span>{loading ? 'Generando...' : 'Generar documento'}</span>"), 'la etiqueta no desaparece con el spinner');
    });
});
