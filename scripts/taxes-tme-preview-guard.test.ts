import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// Las cadenas visibles viven en el diccionario i18n (carril C); los
// componentes las referencian por clave. El guard verifica ambos extremos.
const esTaxes = JSON.parse(readFileSync('lib/i18n/messages/es/taxes.json', 'utf8'));

test('TME manual: campo vacío, cálculo explícito y vista previa sin guardar', () => {
    const src = readFileSync('components/taxes/TmePreviewForm.tsx', 'utf8');
    assert.match(src, /useState\(''\)/);
    // El parser es locale-aware (carril C): el input usa el locale activo.
    assert.match(src, /parseLocalizedNumber\(input, locale\)/);
    assert.match(src, /percent === null \|\| percent < 0 \|\| percent > 100/);
    assert.match(src, /previewTaxFiling\(year, percent\)/);
    assert.match(src, /taxes\.tme\.note/);
    assert.match(esTaxes.tme.note, /No se guarda ni sustituye tu declaración/);
    assert.match(esTaxes.tme.note, /base liquidable del ahorro/);
    assert.match(esTaxes.tme.note, /no el de la base general/);
});

test('Casillas por venta: 10 por página y remount al cambiar de página', () => {
    const src = readFileSync('components/taxes/FilingSections.tsx', 'utf8');
    assert.match(src, /rows\.slice\(current \* 10, \(current \+ 1\) \* 10\)/);
    assert.match(src, /RecordList key=\{current\}/);
    assert.match(src, /casillas\.available !== true/);
});

test('La exportación usa el informe mostrado, no el informe inicial viejo', () => {
    const src = readFileSync('components/taxes/TaxesView.tsx', 'utf8');
    assert.match(src, /downloadTaxSummary\(initialHoldings, report, year, ti\)/);
    assert.match(src, /onPreview=\{\(fresh\) => setOverride\(\{ year, report: fresh \}\)\}/);
});

test('0597: sin datos nunca se pinta como 0', () => {
    const src = readFileSync('components/taxes/FilingSections.tsx', 'utf8');
    assert.match(src, /taxes\.filing\.row0597NoData/);
    assert.equal(esTaxes.filing.row0597NoData, 'Sin datos: retenciones españolas incompletas');
});
