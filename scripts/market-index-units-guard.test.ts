/**
 * Guard F152 (unidad falsa en índices): un nivel de índice no es dinero.
 * El backend etiqueta cada serie con unit ("index" | "usd") y el front
 * formatea según esa unidad: US$ solo cuando unit === "usd"; índices y
 * series sin unidad conocida van como número plano. Las respuestas legacy
 * sin unit se normalizan por símbolo conocido (marketIndexUnit), nunca
 * asumiendo USD - ese fallback volvía a pintar «US$» en el S&P 500.
 *
 * Dónde vive hoy el contrato: /inicio ya NO pinta índices (duplicaba
 * «Índices y macro» de /screener con la MISMA llamada getMarketIndices y
 * una fuente de datos menos en el landing). El único front que los pinta es
 * /screener, así que el formatting por unidad se exige ahí, y la ausencia de
 * la copia en el inicio se exige en el propio inicio.
 *
 * Ejecucion: node --experimental-strip-types --test scripts/market-index-units-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { marketIndexUnit } from '../lib/marketIndexUnit.ts';

const route = readFileSync('data-engine/app/api/routes/market.py', 'utf8');
const screener = readFileSync('app/(root)/screener/page.tsx', 'utf8');
const overview = readFileSync('components/PersonalizedOverview.tsx', 'utf8');
const actions = readFileSync('lib/actions/market.actions.ts', 'utf8');

describe('market index units guard (F152)', () => {
  it('el backend etiqueta índices como unit "index" y metales/cripto como "usd"', () => {
    assert.match(route, /\{"symbol": "\^GSPC", "name": "S&P 500", "unit": "index"\}/, '^GSPC con unit index');
    assert.match(route, /\{"symbol": "\^IXIC", "name": "Nasdaq Composite", "unit": "index"\}/, '^IXIC con unit index');
    assert.match(route, /\{"symbol": "BTC-USD", "name": "Bitcoin", "unit": "usd"\}/, 'BTC con unit usd');
  });

  it('normalización legacy sin unit: índices → index, BTC → usd, desconocido → null', () => {
    // Payload legacy (caché antigua) sin unit - el caso que reventó el bloqueo.
    assert.equal(marketIndexUnit('^GSPC', undefined), 'index', 'S&P legacy sin unit');
    assert.equal(marketIndexUnit('^IXIC', undefined), 'index', 'Nasdaq legacy sin unit');
    assert.equal(marketIndexUnit('BTC-USD', undefined), 'usd', 'BTC legacy sin unit');
    assert.equal(marketIndexUnit('ACME-XYZ', undefined), null, 'desconocido sin unit no asume USD');
  });

  it('el unit del backend se conserva cuando viene presente', () => {
    assert.equal(marketIndexUnit('^GSPC', 'index'), 'index');
    assert.equal(marketIndexUnit('GC=F', 'usd'), 'usd');
    assert.equal(marketIndexUnit('NUEVO', 'index'), 'index', 'serie nueva con unit explícita');
  });

  it('getMarketIndices normaliza en la frontera y declara el tipo unidad', () => {
    assert.match(actions, /marketIndexUnit\(item\.symbol, item\.unit\)/, 'normalización en la frontera');
    // Tipo único de la unidad para el front (vivía además duplicado como
    // interface local en el inicio, que ya no pinta índices).
    assert.match(actions, /unit\?: 'index' \| 'usd'/, 'el tipo de la unidad se declara una sola vez');
  });

  it('los fronts solo ponen US$ cuando unit === "usd"', () => {
    assert.equal(screener.includes("formatPrice(i.price, 'USD')}"), false, 'sin formato US$ incondicional en screener');
    assert.match(screener, /i\.unit === 'usd'/, 'screener ramifica por usd explícito');
    assert.match(screener, /formatPrice\(i\.price, 'USD'\)/, 'el US$ vive solo en la rama usd');
    assert.match(
      screener,
      /i\.unit === 'usd'\s*\?\s*formatPrice\(i\.price, 'USD'\)\s*:\s*formatNumber\(i\.price/,
      'la rama no-usd va como número plano, nunca como dinero',
    );
  });

  it('el inicio no vuelve a pintar los índices que ya da /screener', () => {
    // Densidad: mismo getMarketIndices, misma tarjeta, una fuente de datos
    // menos en el landing. Si vuelve, el índice vuelve a estar en la home.
    assert.equal(overview.includes('getMarketIndices'), false, '/inicio no debe pedir índices: los pinta /screener');
    assert.equal(overview.includes('unit === \'usd\''), false, 'sin ramificación por unidad en el inicio');
    assert.ok(!overview.includes('Contexto de mercado'), 'la sección duplicada desaparece del inicio');
    // Y /screener sigue siendo la casa de los índices.
    assert.ok(screener.includes('Índices y macro'), '/screener es la casa de los índices');
  });
});
