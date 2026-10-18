/**
 * QA /research «Generar entregable»: el diálogo volcaba el JSON crudo
 * (snake_case, inglés) y el botón perdía su texto mientras generaba
 * (barra teal vacía). El resultado se renderiza como documento legible
 * (markdown del backend, en español) y el botón conserva su etiqueta.
 * Ejecución: node --experimental-strip-types --test scripts/work-product-document-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const COMPONENT = 'components/work-products/WorkProductButton.tsx';
const SERVICE = 'data-engine/app/services/work_product_service.py';

describe('el entregable se muestra como documento legible', () => {
    it('el diálogo renderiza el markdown, nunca el JSON crudo', () => {
        const source = readFileSync(COMPONENT, 'utf8');
        assert.ok(!source.includes('JSON.stringify(result'), 'desaparece el volcado JSON del resultado');
        assert.match(source, /<ThesisMarkdown content=\{result\.markdown\} \/>/, 'se renderiza el documento markdown');
    });

    it('el backend genera el documento en español y sin reprs de Python', () => {
        const service = readFileSync(SERVICE, 'utf8');
        assert.match(service, /Datos a fecha de:/, 'cabecera de fecha en español');
        assert.match(service, /"## Fuentes"/, 'sección de fuentes en español');
        assert.ok(!service.includes('(str(payload))'), 'nunca se vuelca str(payload) en el documento');
        assert.match(service, /"one_page_memo": "Memo de una página"/, 'títulos de producto en español');
    });
});

describe('el botón conserva su texto mientras genera', () => {
    it('la etiqueta es un nodo propio, siempre presente', () => {
        const source = readFileSync(COMPONENT, 'utf8');
        assert.match(source, /<span>\{loading \? 'Generando\.\.\.' : 'Generar documento'\}<\/span>/, 'la etiqueta no desaparece con el spinner');
        assert.match(source, /bg-teal-600 text-white/, 'contraste explícito en todos los estados');
    });
});
