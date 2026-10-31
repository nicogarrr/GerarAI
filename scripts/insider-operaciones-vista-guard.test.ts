/**
 * Guard: la vista de operaciones insider (cartera + watchlist) muestra el
 * agregado con su periodo y lo no verificable a la vista (Nico, 2026-10-19).
 *
 * Contrato: la tabla por empresa tiene Insider | Rol | Ventas | Compras |
 * Ops | Última con importes USD (convención en-US), acciones en es-ES,
 * periodo visible por empresa, y las salvedades del backend (códigos
 * excluidos, importes sin imputar, empresas sin Form 4 persistido) escritas
 * en la interfaz: nada de ceros que parezcan dato. La página solo la monta
 * sin ticker (junto al feed), con fetch independiente del feed.
 *
 * Ejecutar: node --experimental-strip-types --test scripts/insider-operaciones-vista-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const vista = readFileSync('components/insider/InsiderOperationsView.tsx', 'utf8');
// Las cadenas visibles viven en el diccionario i18n (carril C); el
// componente las referencia por clave. El guard verifica ambos extremos.
const esOps = JSON.parse(readFileSync('lib/i18n/messages/es/insider.json', 'utf8')).operations;
const pagina = readFileSync('app/(root)/insider/page.tsx', 'utf8');
const acciones = readFileSync('lib/actions/insider.actions.ts', 'utf8');

describe('Insider operaciones: vista del agregado por empresa', () => {
  it('tabla de referencia con las columnas pedidas y formato honesto', () => {
    for (const [clave, columna] of [
      ['colInsider', 'Insider'],
      ['colRole', 'Rol'],
      ['colSales', 'Ventas'],
      ['colBuys', 'Compras'],
      ['colOps', 'Ops'],
      ['colLast', 'Última'],
    ] as const) {
      assert.ok(vista.includes(`insider.operations.${clave}`), `falta la referencia ${clave}`);
      assert.equal(esOps[clave], columna, `etiqueta es de ${clave}`);
    }
    assert.match(vista, /formatPrice\([^,]+, 'USD'/, 'importes USD con el formateador común (es-ES)');
    assert.match(vista, /formatNumber\(side\.shares/, 'acciones en es-ES, como los importes de la línea');
    assert.match(vista, /formatMarketCapUsd\(/, 'totales con formato compacto USD');
    assert.match(vista, /insiderRole\(row\.role, row\.officer_title\)/, 'el cargo pasa por insiderRole');
    assert.match(vista, /insiderName\(row\.insider\)/, 'el nombre SEC pasa por insiderName');
  });

  it('periodo y no verificable, visibles', () => {
    assert.match(vista, /periodText\(t, f, company\.period\)/, 'el periodo de cada empresa se muestra');
    assert.ok(vista.includes('companies_without_data'), 'las empresas sin Form 4 se declaran');
    assert.ok(vista.includes('excluded_codes'), 'los códigos excluidos (concesiones/ejercicios) se declaran');
    assert.ok(vista.includes('rows_without_value'), 'los importes no imputados se declaran');
    assert.ok(vista.includes('rows_without_date'), 'las filas sin fecha se declaran');
    assert.ok(vista.includes('amended_filings'), 'las enmiendas 4/A no enlazables se declaran');
    assert.ok(vista.includes('insider.operations.footAmended'), 'la vista usa el aviso de enmiendas');
    assert.ok(esOps.footAmended.includes('doble conteo'), 'el aviso de enmiendas advierte el posible doble conteo de 4/A');
    assert.ok(vista.includes('insider.operations.avgNa'), 'la vista usa la marca de precio medio parcial');
    assert.ok(esOps.avgNa.includes('precio medio N/D'), 'el precio medio parcial no se muestra como dato');
    assert.ok(!vista.includes('n/d') && !JSON.stringify(esOps).includes('n/d'), 'la convención del repo es N/D mayúscula');
    assert.ok(vista.includes('minMark(totals.sell)'), 'el total vendido mínimo se marca en la cifra');
    assert.ok(vista.includes('minMark(totals.buy)'), 'el total comprado mínimo se marca en la cifra');
    assert.ok(vista.includes('avgText(t, f, row.sell)') && vista.includes('avgText(t, f, row.buy)'), 'móvil declara el medio N/D igual que desktop');
    assert.ok(vista.includes('insider.operations.withoutData'), 'la vista declara las empresas sin Form 4');
    assert.match(esOps.withoutData, /No es «sin actividad»: es lo que el monitor aún no ha guardado/);
    assert.match(vista, /status !== 'ok'/, 'estado de error honesto');
  });

  it('la página la monta sin ticker, con fetch independiente del feed', () => {
    assert.match(pagina, /getInsiderOperations\(365\)/, 'la página pide el agregado anual');
    assert.match(pagina, /<InsiderOperationsView days=\{365\} result=\{operations\} \/>/);
    assert.match(acciones, /\/api\/insider\/operations\?days=/, 'la acción llama al endpoint nuevo');
  });
});
