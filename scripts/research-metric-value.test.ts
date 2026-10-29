import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
// @ts-expect-error node needs the explicit extension.
import { formatResearchMetric } from '../lib/research/metric-value.ts';
test('financial facts retain their declared currency and share-count basis', () => {
 assert.equal(formatResearchMetric('148401000000','USD'),'148,4 mil M\u00a0US$');
 assert.equal(formatResearchMetric('89800000000','CAD'),'89,80 mil M\u00a0CAD');
 assert.equal(formatResearchMetric('1023670000000','CNY'),'1.023,67 mil M\u00a0CNY');
 assert.match(formatResearchMetric('19240000000','shares'), /acciones$/);
 assert.ok(!formatResearchMetric('19240000000','shares').includes('ADS'));
 assert.equal(formatResearchMetric('1.25','USD/share'),'1,25\u00a0US$/acción');
 assert.equal(formatResearchMetric(null,'USD'),'N/D');
 assert.equal(formatResearchMetric('NaN','USD'),'N/D');
 const src=readFileSync('app/(root)/research/[ticker]/page.tsx','utf8');
 assert.ok(src.includes('return formatResearchMetric(parsed, unit)'));
});
test('quote header formats every currency in es-ES, never the listing currency swapped', () => {
 const src=readFileSync('components/research/CompanyHeaderQuote.tsx','utf8');
 // Nico (29-oct-2026): el USD ya no va en inglés.
 assert.ok(!src.includes("'en-US'"));
 assert.ok(src.includes('return formatMoney(value, currency'));
 assert.ok(src.includes('headerMoney(quote!.price, currency)'));
});

test('formulas cannot invent USD and per-share figures retain cents', () => {
 assert.equal(formatResearchMetric(250.75, 'USD/share'), '250,75\u00a0US$/acción');
 assert.equal(formatResearchMetric(343.46, 'USD'), '343,46\u00a0US$');
 assert.equal(formatResearchMetric(250.75, 'EUR/share'), '250,75\u00a0€/acción');
 assert.equal(formatResearchMetric(148.4, 'USD_millions'), '148,4');
 const src=readFileSync('app/(root)/research/[ticker]/page.tsx','utf8');
 assert.ok(src.includes("metricValue(formula.value, formula.unit ?? '')"));
 assert.ok(!src.includes("metricValue(formula.value, 'USD')"));
});
