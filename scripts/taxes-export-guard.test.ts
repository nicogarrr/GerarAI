/**
 * Guard: la exportación «Exportar resumen» de /taxes no puede truncar datos.
 *
 * downloadTaxSummary serializaba con formatRecordValue/describeValue,
 * formateadores de PANTALLA pensados para celdas con clamp: tope de 6
 * entradas («+16 más»: el summary perdía 16 de 22 campos fiscales, entre
 * ellos net_taxable_base y los flags de revisión) y tope de 400 caracteres
 * (la sección filing cortaba a mitad de palabra y loss_compensation nunca
 * llegaba al CSV). La exportación usa ahora csvFullValue, mismo formato
 * «clave: valor · …» sin topes.
 *
 * Ejecución: node --experimental-strip-types --test scripts/taxes-export-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const view = readFileSync('components/taxes/TaxesView.tsx', 'utf8');
const exportBlock = view.match(/function downloadTaxSummary[\s\S]*?\n}/);
assert.ok(exportBlock, 'downloadTaxSummary no encontrado');

describe('exportación fiscal completa', () => {
    it('downloadTaxSummary no usa el formateador de pantalla que trunca', () => {
        assert.doesNotMatch(exportBlock[0], /formatRecordValue/);
    });
    it('serializa con un serializer completo sin topes de entradas ni caracteres', () => {
        assert.match(view, /function csvFullValue/);
        assert.match(exportBlock[0], /csvFullValue\(value\)/);
        assert.match(exportBlock[0], /csvFullValue\(holding\[header\]\)/);
        const serializer = view.match(/function csvFullValue[\s\S]*?\n}/);
        assert.ok(serializer, 'csvFullValue no encontrado');
        assert.doesNotMatch(serializer[0], /más|MAX_VALUE|slice\(0, MAX/);
    });
    it('mantiene el escaping CSV y los mismos sentinelas de la UI', () => {
        assert.match(view, /value\.replaceAll\('"', '""'\)/);
        const serializer = view.match(/function csvFullValue[\s\S]*?\n}/);
        assert.match(serializer![0], /return '—'/);
        assert.match(serializer![0], /value \? 'Sí' : 'No'/);
    });
});
