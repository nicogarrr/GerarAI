import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (p: string) => readFileSync(p, 'utf8');
const flowEs = JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8')).flow;

test('news table keeps five decision columns and a contextual disclosure', () => {
  const src = (read('app/(root)/research/news/page.tsx') + read('components/research/NewsEventsFlow.tsx'));
  const columns: Array<[string, string]> = [['colTicker', 'Ticker'], ['colDate', 'Fecha'], ['colHeadline', 'Titular'], ['colMateriality', 'Materialidad'], ['colStatus', 'Estado y detalle']];
  for (const [key, literal] of columns) {
    assert.match(src, new RegExp(`scope="col">\\{t\\('research\\.flow\\.${key}'\\)\\}</th>`));
    assert.equal(flowEs[key], literal, `ES ${key} == literal histórico`);
  }
  assert.doesNotMatch(src, /scope="col">Peso al evaluar|scope="col">Impacto|scope="col">¿Actualizar\?/);
  assert.match(src, /summary=\{t\('research\.flow\.viewContext'\)\}/);
  assert.equal(flowEs.viewContext, 'Ver contexto');
});

test('desktop portfolio and watchlist keep destructive action within symbol menu', () => {
  const portfolio = read('components/portfolio/PortfolioHoldings.tsx');
  const watchlist = read('app/(root)/watchlist/page.tsx');
  assert.doesNotMatch(portfolio, /<TableHead[^>]*>Fiscal<\/TableHead>|<TableHead[^>]*>Acciones<\/TableHead>/);
  assert.doesNotMatch(watchlist, /<TableHead[^>]*>Acciones<\/TableHead>/);
  // i18n: la etiqueta del menú vive en messages/<locale>/portfolio.json.
  assert.match(portfolio, /<summary[^>]*>\{ti\('portfolio\.holdings\.options'\)\}<\/summary>/);
  const portfolioEs = JSON.parse(readFileSync('lib/i18n/messages/es/portfolio.json', 'utf8'));
  assert.equal(portfolioEs.holdings.options, 'Opciones');
  assert.match(portfolio, /setConfirmSymbol\(holding\.symbol\)/, 'la acción destructiva abre la confirmación');
  assert.match(portfolio, /onConfirm=\{\(\) => \{ if \(confirmSymbol\) handleDelete\(confirmSymbol\); \}\}/, 'la mutación solo corre al confirmar');
  assert.match(watchlist, /<summary[^>]*Opciones/);
  assert.match(watchlist, /<WatchlistRemoveButton symbol=\{stock.symbol\}/);
});

test('volume belongs to most-active movers only and screener has units', () => {
  const movers = (read('components/market/MoversTable.tsx') + read('app/(root)/screener/page.tsx'));
  assert.match(movers, /showVolume \? <th/);
  assert.match(movers, /caption=\{caption\} tickerSets=\{tickerSets\} showVolume=\{vista === 'activas'\}/);
  const screener = read('app/(root)/screener/page.tsx');
  assert.match(screener, /formatMarketCapUsd\(value\)/);
  assert.match(screener, /screenerMarketCap\(r.marketCap\)/);
});

test('decisional fields removed from columns stay reachable in row detail (auditoria SERIE 1)', () => {
  const news = (read('app/(root)/research/news/page.tsx') + read('components/research/NewsEventsFlow.tsx'));
  // El expander "Ver contexto" conserva tier, impacto y peso con etiqueta; nunca desaparecen.
  for (const [key, literal] of [['ctxTier', 'Tier de fuente: '], ['ctxImpact', 'Impacto: '], ['ctxWeight', 'Peso en cartera: ']]) {
    assert.match(news, new RegExp(`<dt className="inline font-medium">\\{t\\('research\\.flow\\.${key}'\\)\\}</dt>`));
    assert.equal(flowEs[key], literal, `ES ${key} == literal histórico`);
  }
  assert.match(news, /etiquetaTierFuente\(event\.source_tier, locale\)/);
  assert.match(news, /etiquetaDireccionImpacto\(event\.impact_direction, locale\)/);
  assert.match(news, /formatPercent\(event\.portfolio_weight/);

  const portfolio = read('components/portfolio/PortfolioHoldings.tsx');
  // fiscalBucket/holdingDays/firstBuyDate fuera de columnas, pero accesibles en tarjeta móvil y menú Opciones.
  assert.match(portfolio, /holding\.fiscalBucket === 'largo_plazo'/);
  assert.match(portfolio, /holding\.holdingDays !== null/);
  assert.match(portfolio, /portfolio\.holdings\.sincePrefix/, 'fecha de entrada vía i18n');
  const portfolioEs2 = JSON.parse(readFileSync('lib/i18n/messages/es/portfolio.json', 'utf8'));
  assert.match(portfolioEs2.holdings.sincePrefix, /^En cartera desde: /);
  assert.equal(portfolioEs2.holdings.fiscalNoHistory, 'Sin historial de compra registrado');
  assert.match(portfolio, /portfolio\.holdings\.fiscalNoHistory/);
});


test('noticias conserva columna Materialidad sin leyenda explicativa', () => {
  const source = readFileSync('components/research/NewsEventsFlow.tsx', 'utf8');
  assert.match(source, /scope="col">\{t\('research\.flow\.colMateriality'\)\}<\/th>/);
  assert.equal(flowEs.colMateriality, 'Materialidad');
  assert.doesNotMatch(source, /Materialidad: puntuación del evento/);
});
