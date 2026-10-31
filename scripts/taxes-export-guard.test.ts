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
 * Además las celdas pasan por csvExportCell, que neutraliza fórmulas de
 * hoja de cálculo con la convención `_csv_cell` del backend (export.py):
 * un TEXTO que empieza por = + - @ | % (p. ej. un ticker '=HACK', válido
 * bajo el pattern de paper_trading.py) lleva prefijo '; sin el escape,
 * Excel/Sheets interpretarían la celda como fórmula al abrir el CSV. Un
 * NÚMERO negativo (-10) queda intacto: las hojas ya lo parsean como
 * número; una cadena '-10' sí se neutraliza (isinstance str del backend).
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
        assert.match(exportBlock[0], /csvExportCell\(value, tFn\)/);
        assert.match(exportBlock[0], /csvExportCell\(holding\[header\], tFn\)/);
        const cell = view.match(/function csvExportCell[\s\S]*?\n}/);
        assert.ok(cell, 'csvExportCell no encontrado');
        assert.match(cell[0], /csvFullValue\(value, tFn\)/);
        const serializer = view.match(/function csvFullValue[\s\S]*?\n}/);
        assert.ok(serializer, 'csvFullValue no encontrado');
        assert.doesNotMatch(serializer[0], /más|MAX_VALUE|slice\(0, MAX/);
    });
    it('neutraliza fórmulas solo en texto original, con la convención del backend', () => {
        const cell = view.match(/function csvExportCell[\s\S]*?\n}/);
        assert.ok(cell, 'csvExportCell no encontrado');
        // prefijo ' ante = + - @ | % (mismo alfabeto que _csv_cell de export.py)
        assert.match(cell[0], /\^\[=\+\\-@\|%\]/);
        assert.match(cell[0], /`'\$\{text\}`/);
        // preservación de tipo: solo si el valor ORIGINAL es string;
        // un number -10 nunca se convierte en texto "'-10"
        assert.match(cell[0], /typeof value === 'string'/);
    });
    it('mantiene el escaping CSV y los mismos sentinelas de la UI', () => {
        assert.match(view, /value\.replaceAll\('"', '""'\)/);
        const serializer = view.match(/function csvFullValue[\s\S]*?\n}/);
        assert.match(serializer![0], /return '—'/);
        assert.match(serializer![0], /value \? tFn\('taxes\.values\.yes'\) : tFn\('taxes\.values\.no'\)/);
        // Los sentinelas visibles viven en el diccionario i18n (carril C).
        const esTaxes = JSON.parse(readFileSync('lib/i18n/messages/es/taxes.json', 'utf8'));
        assert.equal(esTaxes.values.yes, 'Sí');
        assert.equal(esTaxes.values.no, 'No');
    });
});
