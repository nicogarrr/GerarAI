import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// @ts-expect-error TS5097
import { etiquetaComponenteAtribucion } from '../lib/labels.ts';

const page = readFileSync('app/(root)/portfolio/intelligence/page.tsx', 'utf8');

test('F282: el catálogo cerrado de componentes tiene etiqueta ES', () => {
    const esperadas: Record<string, string> = {
        fundamental_growth: 'Crecimiento fundamental',
        multiple: 'Múltiplo',
        dividends: 'Dividendos',
        buybacks: 'Recompras',
        dilution: 'Dilución',
        fx: 'Divisa',
        sizing: 'Contribución ponderada',
    };
    for (const [key, label] of Object.entries(esperadas)) {
        assert.equal(etiquetaComponenteAtribucion(key), label, key);
    }
});

test('F282: clave desconocida -> se muestra cruda, nunca oculta', () => {
    assert.equal(etiquetaComponenteAtribucion('nuevo_componente'), 'nuevo_componente');
});

test('F282: la cabecera de la tabla ya no pinta la clave cruda', () => {
    assert.match(page, /\{etiquetaComponenteAtribucion\(key(?:, f\.locale)?\)\}/);
    assert.doesNotMatch(page, /key\.replaceAll\('_', ' '\)/);
});

test('F333: las tablas anchas de inteligencia llevan affordance de scroll y contain', () => {
    // La tabla de atribución (min-w-[1050px]) se salía 45px del wrapper sin
    // indicio visual de scroll; el patrón de F176 (scroll-affordance-x +
    // contain) lo deja visible y contenido en las 3 tablas.
    // La regla no es un numero fijo: TODA tabla de la pagina (hoy 3 de
    // inteligencia + 2 de la matriz de riesgo) va dentro de un wrapper con
    // affordance; contar tablas y no wrappers impide que una tabla nueva sin
    // wrapper pase el guard por no actualizar el numero.
    const wrappers = page.match(/scroll-affordance-x mt-4 overflow-x-auto \[contain:layout_paint\]/g) ?? [];
    const tables = page.match(/<table/g) ?? [];
    assert.equal(wrappers.length, tables.length);
    assert.doesNotMatch(page, /className="mt-4 overflow-x-auto"/);
});

test('sizing names the actual weighted-return calculation, never the position weight',()=>{
    const backend=readFileSync('data-engine/app/services/portfolio_intelligence_service.py','utf8');
    assert.match(backend, /"sizing":\s*\(\s*total_return \* weights.get\(company.id, 0\)/);
    assert.notEqual(etiquetaComponenteAtribucion('sizing'), 'Tamaño de posición');
});
