/**
 * Guardas y canarios de honestidad de la proyección de dividendos
 * (idea 5, pieza 12 del listado 0-31).
 *
 * La pestaña pinta cifras del endpoint determinista
 * /api/portfolio/dividends/projection. Las reglas que no pueden regresar:
 *
 *  1. Ausencia no es cero: los null del backend (sin fx, sin retención
 *     verificada, escenario fiscal no disponible) se pintan N/D, nunca 0,00.
 *  2. La etiqueta INFERIDO viaja del payload a la pantalla.
 *  3. Las posiciones excluidas se nombran (subconjunto cubierto), no se
 *     agregan en silencio.
 *  4. La nota de veracidad de los declarados futuros ("según el proveedor,
 *     no verificado contra fuente primaria") llega a la pantalla: INGESTADO
 *     no equivale a confirmación corporativa.
 *  5. La nota fiscal del año explica los N/D (base no EUR, subconjunto...):
 *     nunca se descarta.
 *  6. Cantidades fraccionarias (Numeric(20,6)) e importes por acción muy
 *     pequeños no se redondean a un cero inventado.
 *
 * Ejecución: node --experimental-strip-types --test scripts/portfolio-dividends-honesty.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
// @ts-expect-error TS5097: la extension explicita la exige node --experimental-strip-types.
import { declaredFutureNoteView, fiscalCardRows, fiscalYearNote, formatPositionQuantity } from '../lib/portfolio-dividends-display.ts';
// @ts-expect-error TS5097: la extension explicita la exige node --experimental-strip-types.
import { formatMoney, formatPrice, NA } from '../lib/format.ts';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');
const source = (relativePath: string): string => readFileSync(join(root, relativePath), 'utf8');

describe('proyección de dividendos: ausente no es cero', () => {
  it('la vista usa formatMoney con su fallback N/D, sin ?? 0 en importes', () => {
    const view = source('components/portfolio/PortfolioDividends.tsx');
    assert.ok(view.includes("from '@/lib/format'"), 'formatea con los helpers ligados al locale');
    assert.ok(!/\?\?\s*0(?![\d.])/.test(view), 'un importe ausente no puede volverse 0');
    // i18n: N/D vive en common.na del diccionario.
    assert.ok(view.includes("ti('common.na')"), 'los importes sin cobertura referencian common.na');
    const commonEs = JSON.parse(source('lib/i18n/messages/es/common.json'));
    assert.equal(commonEs.na, 'N/D', 'el N/D es el del diccionario es');
  });

  it('el tipo declara los campos fiscales como number | null', () => {
    const actions = source('lib/actions/portfolio.actions.ts');
    const declared = /export type DividendProjectionFiscalYear = \{[\s\S]*?\n\};/.exec(actions);
    assert.ok(declared, 'debe existir DividendProjectionFiscalYear');
    for (const key of ['gross_base', 'irpf_scenario', 'net_scenario', 'cuota_pendiente_estimada']) {
      assert.ok(
        new RegExp(`${key}: number \\| null;`).test(declared[0]),
        `DividendProjectionFiscalYear debe declarar ${key}: number | null`,
      );
    }
  });

  it('la etiqueta del backend (INFERIDO) se pinta tal cual', () => {
    const view = source('components/portfolio/PortfolioDividends.tsx');
    // La etiqueta INFERIDO ya no se pinta en la UI (decisión del dueño, 17 oct): el payload la conserva.
    assert.equal(view.includes('{projection.label}'), false, 'sin etiqueta «inferido» visible');
    const actions = source('lib/actions/portfolio.actions.ts');
    assert.ok(actions.includes('label: string;'), 'el tipo conserva la etiqueta del backend');
  });

  it('las posiciones excluidas se nombran, no se agregan en silencio', () => {
    const view = source('components/portfolio/PortfolioDividends.tsx');
    assert.ok(view.includes('excluded_tickers'), 'las excluidas del mes/año se listan');
    // i18n: el sufijo vive en messages/es/portfolio.json.
    const divEs = JSON.parse(source('lib/i18n/messages/es/portfolio.json'));
    assert.ok(divEs.dividends.subsetSuffix.includes('sin datos, no cero'), 'la exclusión se explica como ausencia, no como cero');
    assert.ok(view.includes('portfolio.dividends.subsetSuffix'), 'la vista referencia el sufijo');
  });

  it('el aviso INFERIDO y las condiciones fiscales son accesibles desde la vista', () => {
    const view = source('components/portfolio/PortfolioDividends.tsx');
    // La vista no pinta un bloque largo de método: la procedencia INFERIDO
    // y el carácter de escenario van en un aviso breve junto al bruto.
    const divEs2 = JSON.parse(source('lib/i18n/messages/es/portfolio.json'));
    assert.ok(divEs2.dividends.grossInferredNote.includes('INFERIDO: réplica de los dividendos de los últimos 12 meses'), 'aviso INFERIDO visible junto al bruto');
    assert.ok(divEs2.dividends.grossInferredNote.includes('no el neto final'), 'el escenario fiscal se declara como no definitivo junto a las cifras');
    assert.ok(view.includes('portfolio.dividends.grossInferredNote'), 'la vista referencia el aviso');
    assert.equal(view.includes('projection.method'), false, 'el párrafo largo de método ya no se pinta');
    assert.ok(view.includes('projection.fiscal_conditions'), 'las condiciones del escenario son visibles');
    assert.ok(view.includes('projection.sources'), 'las fuentes son enlazables');
  });
});

describe('canarios de render: declarados futuros', () => {
  const BACKEND_NOTE =
    'Declarado con ex_date futura según el proveedor de datos (no verificado contra fuente primaria); no alimenta la réplica.';
  const item = {
    ticker: 'AAPL',
    ex_date: '2026-11-06',
    pay_date: '2026-11-13',
    amount_per_share: 0.26,
    currency: 'USD',
    label: 'INGESTADO',
    source: 'fmp',
    projection_as_of: '2026-10-17',
    note: BACKEND_NOTE,
  };

  it('la nota de veracidad compartida llega a la descripción del panel', () => {
    const view = declaredFutureNoteView([item, { ...item, ticker: 'MSFT', ex_date: '2026-11-10' }]);
    assert.equal(view.sharedNote, BACKEND_NOTE);
    assert.equal(view.sharedAsOf, '2026-10-17');
    assert.ok(view.perItemNotes.every((note) => note === null));
  });

  it('notas distintas caen a cada línea, nunca se pierden', () => {
    const view = declaredFutureNoteView([item, { ...item, ticker: 'MSFT', note: 'Otra nota' }]);
    assert.equal(view.sharedNote, null);
    assert.deepEqual(view.perItemNotes, [BACKEND_NOTE, 'Otra nota']);
  });

  it('un importe por acción diminuto no se pinta como 0,00', () => {
    // USD en es-ES como el resto (Nico 29-oct-2026): «0,000001 US$».
    const rendered = formatPrice(0.000001, 'USD').replace(/\u00a0/g, ' ');
    assert.notEqual(rendered, '0,00 US$');
    assert.ok(rendered.includes('0,000001'), `esperaba decimales reales, salió: ${rendered}`);
    // El componente usa formatPrice (adaptativo), no formatMoney (2 decimales).
    const view = source('components/portfolio/PortfolioDividends.tsx');
    assert.ok(view.includes('formatPrice(item.amount_per_share'), 'amount_per_share usa formato adaptativo');
    assert.equal(formatMoney(0.000001, 'USD').replace(/\u00a0/g, ' '), '0,00 US$', 'formatMoney a 2 decimales sí inventaría el cero (canario del riesgo)');
  });
});

describe('canarios de render: escenario fiscal', () => {
  it('un año sin cobertura fiscal devuelve nulls (N/D), no ceros', () => {
    const yearSinCobertura = {
      gross_base: null,
      irpf_scenario: null,
      source_withheld_foreign: null,
      retencion_a_cuenta_es: null,
      double_tax_deduction: null,
      cuota_pendiente_estimada: null,
      net_scenario: null,
      covered_tickers: [],
      excluded_tickers: ['ULVR'],
      note: 'Sin datos: todas las posiciones con dividendo proyectado este año carecen de fx o de retención verificada (N/D, no cero).',
    };
    const rows = fiscalCardRows(yearSinCobertura);
    assert.ok(rows.length > 0);
    assert.ok(rows.every((row) => row.value === null), 'cada fila ausente es null -> N/D');
    assert.ok(rows.every((row) => formatMoney(row.value, 'EUR') === NA), 'la vista las pinta N/D');
    // Y la nota que explica los N/D no se descarta.
    assert.equal(fiscalYearNote(yearSinCobertura), yearSinCobertura.note);
  });

  it('la nota del año se muestra en la tarjeta', () => {
    const view = source('components/portfolio/PortfolioDividends.tsx');
    assert.ok(view.includes('fiscalYearNote'), 'la tarjeta consume la nota del año');
  });
});

describe('canarios de render: cantidades fraccionarias', () => {
  it('una posición 0,000001 no se pinta como 0', () => {
    const rendered = formatPositionQuantity(0.000001);
    assert.ok(rendered.includes('0,000001'), `esperaba 6 decimales, salió: ${rendered}`);
    assert.notEqual(rendered, '0');
  });

  it('cantidades enteras y mixtas salen legibles en es-ES', () => {
    assert.equal(formatPositionQuantity(300), '300');
    assert.equal(formatPositionQuantity(25.5), '25,5');
    // es-ES no agrupa millares de 4 cifras (RAE/CLDR minimumGroupingDigits=2).
    assert.equal(formatPositionQuantity(1234.123456), '1234,123456');
  });
});
