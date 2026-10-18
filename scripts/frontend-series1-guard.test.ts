import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (p: string) => readFileSync(p, 'utf8');

test('news table keeps five decision columns and a contextual disclosure', () => {
  const src = (read('app/(root)/research/news/page.tsx') + read('components/research/NewsEventsFlow.tsx'));
  for (const column of ['Ticker', 'Fecha', 'Titular', 'Materialidad', 'Estado y detalle']) assert.match(src, new RegExp(`scope="col">${column}`));
  assert.doesNotMatch(src, /scope="col">Peso al evaluar|scope="col">Impacto|scope="col">¿Actualizar\?/);
  assert.match(src, /Ver contexto/);
});

test('desktop portfolio and watchlist keep destructive action within symbol menu', () => {
  const portfolio = read('components/portfolio/PortfolioHoldings.tsx');
  const watchlist = read('app/(root)/watchlist/page.tsx');
  assert.doesNotMatch(portfolio, /<TableHead[^>]*>Fiscal<\/TableHead>|<TableHead[^>]*>Acciones<\/TableHead>/);
  assert.doesNotMatch(watchlist, /<TableHead[^>]*>Acciones<\/TableHead>/);
  assert.match(portfolio, /<summary[^>]*Opciones/);
  assert.match(portfolio, /handleDelete\(holding.symbol\)/);
  assert.match(watchlist, /<summary[^>]*Opciones/);
  assert.match(watchlist, /<WatchlistRemoveButton symbol=\{stock.symbol\}/);
});

test('volume belongs to most-active movers only and screener has units', () => {
  const movers = read('app/(root)/movers/page.tsx');
  assert.match(movers, /showVolume \? <th/);
  assert.match(movers, /caption="Mayor volumen" tickerSets=\{tickerSets\} showVolume/);
  const screener = read('app/(root)/screener/page.tsx');
  assert.match(screener, /formatMarketCapUsd\(value\)/);
  assert.match(screener, /screenerMarketCap\(r.marketCap\)/);
});

test('decisional fields removed from columns stay reachable in row detail (auditoria SERIE 1)', () => {
  const news = (read('app/(root)/research/news/page.tsx') + read('components/research/NewsEventsFlow.tsx'));
  // El expander "Ver contexto" conserva tier, impacto y peso con etiqueta; nunca desaparecen.
  for (const row of ['Tier de fuente', 'Impacto', 'Peso en cartera']) assert.match(news, new RegExp(`<dt className="inline font-medium">${row}: `));
  assert.match(news, /etiquetaTierFuente\(event\.source_tier\)/);
  assert.match(news, /etiquetaDireccionImpacto\(event\.impact_direction\)/);
  assert.match(news, /formatPercent\(event\.portfolio_weight/);

  const portfolio = read('components/portfolio/PortfolioHoldings.tsx');
  // fiscalBucket/holdingDays/firstBuyDate fuera de columnas, pero accesibles en tarjeta móvil y menú Opciones.
  assert.match(portfolio, /holding\.fiscalBucket === 'largo_plazo'/);
  assert.match(portfolio, /holding\.holdingDays !== null/);
  assert.match(portfolio, /En cartera desde: \{holding\.firstBuyDate \?\? NA\}/);
  assert.match(portfolio, /Sin historial de compra registrado/);
});


test('noticias conserva columna Materialidad sin leyenda explicativa', () => {
  const source = readFileSync('components/research/NewsEventsFlow.tsx', 'utf8');
  assert.match(source, /scope="col">Materialidad/);
  assert.doesNotMatch(source, /Materialidad: puntuación del evento/);
});
