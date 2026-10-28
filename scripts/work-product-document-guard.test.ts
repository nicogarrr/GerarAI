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

const COMPONENT = 'components/work-products/WorkProductDialog.tsx';
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
        assert.doesNotMatch(source, /bg-teal-600/, 'sin override de primario: usa el Button por defecto');
    });
});

describe('formato de moneda del memo (regla de Nico)', () => {
    it('USD en escala inglesa y no USD conserva su divisa', () => {
        const service = readFileSync(SERVICE, 'utf8');
        assert.match(service, /def _format_usd\(/, 'USD en escala inglesa ($343.46, $5.16T, $394B)');
        assert.match(service, /1e12, "T"[\s\S]*?1e9, "B"[\s\S]*?1e6, "M"/, 'escala T/B/M');
        assert.match(service, /currency == "USD"[\s\S]{0,120}_format_usd/, 'solo USD usa escala inglesa');
        assert.match(service, /formatted = _format\(value\)[\s\S]{0,80}\{formatted\} \{currency\}/, 'no USD conserva su divisa');
    });

    it('porcentajes es-ES con coma', () => {
        const service = readFileSync(SERVICE, 'utf8');
        assert.match(service, /def _format_pct\([\s\S]*?replace\("\.", ","\)[\s\S]*?" %"/, 'porcentaje con coma decimal');
    });
});
