import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
// @ts-expect-error node explicit extension
import {exchangeDisplayName} from '../lib/exchangeName.ts';
// @ts-expect-error node explicit extension
import {formatPrice} from '../lib/format.ts';
test('share-class suffix is not a market label',()=>{
 assert.equal(exchangeDisplayName('B'),null);
 assert.equal(exchangeDisplayName('NYSE'),'NYSE');
 assert.equal(exchangeDisplayName('NASDAQ NMS - GLOBAL MARKET'),'NASDAQ');
});
test('saved screener has durable breadcrumb, conditional ranking and real criterion gap',()=>{
 const screen=readFileSync('app/(root)/screeners/[screenId]/page.tsx','utf8');
 assert.ok(screen.includes('result.ranking_formula ? <Badge'));
 assert.ok(screen.includes('flex flex-wrap items-baseline gap-2'));
 assert.ok(readFileSync('components/layout/Breadcrumbs.tsx','utf8').includes('dataset.pageBreadcrumb'));
 assert.ok(readFileSync('components/screeners/ScreenBreadcrumbName.tsx','utf8').includes('dataset.pageBreadcrumb'));
});

test('USD delta has currency sign and percent retains Spanish locale',()=>{
 const s=readFileSync('components/research/CompanyHeaderQuote.tsx','utf8');
 // La variación en divisa pasa por headerChangeMoney -> formatPrice con
 // signDisplay exceptZero (F35: <0,01 con dígitos significativos).
 assert.ok(s.includes('function headerChangeMoney'), 'headerChangeMoney existe');
 assert.ok(s.includes("formatPrice(value, currency, { signDisplay: 'exceptZero' })"), 'usa formatPrice exceptZero');
 assert.ok(s.includes("quote.change_percent != null ? formatPercent(quote.change_percent"), 'porcentaje es-ES');
});

test('small delta never rounds to a bare 0 and keeps its currency sign (F35)',()=>{
 // TEF: la variación real -0,002 € salía «0 · -0,06 %».
 const eur=formatPrice(-0.002,'EUR',{signDisplay:'exceptZero'});
 assert.ok(eur.includes('€'),'EUR conserva el símbolo');
 assert.ok(eur.includes('0,002'),`EUR con dígitos significativos, salió: ${eur}`);
 assert.ok(!/^-?0\s*€$/.test(eur),'no es un 0 redondeado');
 const usd=formatPrice(-0.002,'USD',{signDisplay:'exceptZero'});
 assert.ok(usd.includes('US$'),'USD conserva el signo de divisa');
 assert.ok(usd.includes('0,002'),`USD es-ES con dígitos significativos, salió: ${usd}`);
});
