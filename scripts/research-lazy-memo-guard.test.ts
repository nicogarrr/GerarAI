/**
 * Guard de bundle: las piezas interactivas bajo el pliegue de la ficha
 * /research/[ticker] (formularios del memorando, debate, subida de documentos
 * y cuerpo del popover de alerta) cargan diferidas con next/dynamic a través
 * de una frontera cliente (dynamic() en un server component no saca el chunk
 * del bundle inicial). Si vuelven a imports estáticos, el JS inicial de la
 * ficha recupera varios KB gz y este guard lo pilla.
 * Ejecución: node --experimental-strip-types --test scripts/research-lazy-memo-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const memo = readFileSync('components/research/ThesisMemo.tsx', 'utf8');
const lazy = readFileSync('components/research/LazyMemoControls.tsx', 'utf8');
const lazyUpload = readFileSync('components/forms/FileUploadInputLazy.tsx', 'utf8');
const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
const alertButton = readFileSync('components/research/QuickAlertButton.tsx', 'utf8');
const alertBody = readFileSync('components/research/QuickAlertPopoverBody.tsx', 'utf8');

describe('research ficha: islas del memorando diferidas', () => {
    it('ThesisMemo consume las versiones perezosas, sin imports estáticos de las islas', () => {
        assert.ok(memo.includes("from '@/components/research/LazyMemoControls'"), 'el memo debe usar la frontera perezosa');
        for (const view of ['ThesisHumanInputForm', 'ThesisInvalidationRulesForm', 'ThesisDebatePanel']) {
            assert.ok(!memo.includes(`import ${view} from`), `${view} no debe tener import estático en ThesisMemo`);
            assert.ok(lazy.includes(`dynamic(() => import('@/components/research/${view}')`), `${view} debe cargar con dynamic() en LazyMemoControls`);
        }
    });

    it('el paginador del memorando se queda eager (es contenido SSR, no isla)', () => {
        assert.ok(memo.includes("import ThesisMarkdownPager from '@/components/research/ThesisMarkdownPager'"), 'el paginador mantiene import estático');
    });

    it('las islas diferidas declaran un fallback con role=status', () => {
        assert.ok(lazy.includes('role="status"'), 'el fallback anuncia la carga');
    });
});

describe('research ficha: subida de documentos diferida', () => {
    it('la ficha usa la versión perezosa de FileUploadInput (solo vista de documentos)', () => {
        assert.ok(page.includes("from '@/components/forms/FileUploadInputLazy'"), 'la ficha debe usar la frontera perezosa');
        assert.ok(!/^import\s*\{\s*FileUploadInput\s*\}/m.test(page), 'FileUploadInput no debe tener import estático en la ficha');
        assert.ok(lazyUpload.includes("dynamic(() => import('@/components/forms/FileUploadInput')"), 'FileUploadInputLazy debe cargar con dynamic()');
    });
});

describe('research ficha: popover de alerta diferido', () => {
    it('el cuerpo del popover carga con dynamic() desde el botón', () => {
        assert.ok(alertButton.includes("import('./QuickAlertPopoverBody')"), 'el cuerpo debe ser un import dinámico');
        assert.ok(!alertButton.includes('createAlertResult'), 'la acción de crear vive en el cuerpo, no en el botón');
    });

    it('el chunk se precarga al rozar el gatillo y queda montado tras abrir', () => {
        assert.ok(alertButton.includes('onPointerDown'), 'precarga en pointerdown');
        assert.ok(alertButton.includes('onFocus'), 'precarga en focus');
        assert.ok(alertButton.includes('openedOnce'), 'el botón recuerda la primera apertura');
    });

    it('el cuerpo conserva el control anti-clic antes de hidratar', () => {
        assert.ok(alertBody.includes('disabled={busy || !hydrated}'), 'el envío sigue bloqueado antes de hidratar');
    });
});
