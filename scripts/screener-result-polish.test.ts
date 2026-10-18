import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
// @ts-expect-error node explicit extension
import {exchangeDisplayName} from '../lib/exchangeName.ts';
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
