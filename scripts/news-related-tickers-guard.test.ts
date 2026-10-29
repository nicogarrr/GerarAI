import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { relatedTickerView } from '../lib/news-related-tickers.ts';

// Tira de tickers relacionados (pedido de Nico 19-oct-2026): cierres datados,
// variacion solo si es medible, nada en vivo ni inventado, sin fetch de cliente.

const here = dirname(fileURLToPath(import.meta.url));
const source = (rel: string) => readFileSync(join(here, '..', rel), 'utf8');

void test('variacion medible: signo, color y cierre datado', () => {
  const view = relatedTickerView({ ticker: 'VOD', name: 'Vodafone Group Plc', currency: 'USD', price: 15.955, date: '2026-10-16', change_pct: -0.96 });
  assert.equal(view.tone, 'down');
  assert.match(view.changeText, /0,96/);
  assert.match(view.priceText, /15,9[56]\u00a0US\$/);
  assert.match(view.title, /cierre 2026-10-16/);
  assert.equal(view.href, '/research/VOD');
});

void test('sin cierre o sin variacion consecutiva: N/D, nunca 0 %', () => {
  const noPrice = relatedTickerView({ ticker: 'XYZ', price: null, date: null, change_pct: null });
  assert.equal(noPrice.priceText, 'N/D');
  assert.equal(noPrice.changeText, 'N/D');
  assert.equal(noPrice.tone, 'none');
  const noChange = relatedTickerView({ ticker: 'DTE', currency: 'EUR', price: 30, date: '2026-10-15', change_pct: null });
  assert.equal(noChange.changeText, 'N/D');
  assert.notEqual(noChange.priceText, 'N/D');
  assert.equal(noChange.dateText, '15/10', 'cierre no comparable: fecha corta visible');
});

void test('divisa no ISO (GBX) se muestra tal cual, sin convertir ni usar USD', () => {
  const view = relatedTickerView({ ticker: 'CGEO.L', currency: 'GBX', price: 4255, date: '2026-10-16', change_pct: -0.82 });
  assert.match(view.priceText, /GBX$/);
  assert.ok(!view.priceText.includes('$'));
});

void test('la tira no hace fetch de cliente y no prefetch de enlaces', () => {
  const strip = source('components/research/RelatedTickersStrip.tsx');
  assert.ok(!strip.includes('fetch('), 'sin fetch de cliente (CPU Vercel)');
  assert.ok(!strip.includes('setInterval'), 'sin polling');
  assert.ok(strip.includes('prefetch={false}'), 'sin prefetch de enlaces');
  const headline = source('components/research/NewsHeadline.tsx');
  assert.ok(headline.includes('RelatedTickersStrip'), 'NewsHeadline pinta la tira');
});

void test('el backend usa solo cierres oficiales y evidencia explicita', () => {
  const service = source('data-engine/app/services/news_related_tickers.py');
  assert.ok(service.includes('OFFICIAL_CLOSE_SOURCES'));
  assert.ok(service.includes('common_sessions'));
  assert.ok(!service.includes('httpx') && !service.includes('requests'), 'sin red');
});

void test('ETF: peso del ETF segun holdings, sin precio ni variacion inventados', () => {
  const v = relatedTickerView({ ticker: 'NASA', name: 'Tema Space Innovators ETF', kind: 'etf', weight_pct: 5.5, holdings_as_of: '2026-10-16', price: null, date: null, change_pct: null });
  assert.equal(v.isEtf, true);
  assert.equal(v.priceText, '5,5 % del ETF');
  assert.equal(v.changeText, '');
  assert.equal(v.href, '');
  assert.ok(v.title.includes('2026-10-16'));
});
