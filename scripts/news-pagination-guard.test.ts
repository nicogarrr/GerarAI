import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const flow = readFileSync('components/research/NewsEventsFlow.tsx', 'utf8');
const page = readFileSync('app/(root)/research/news/page.tsx', 'utf8');
const actions = readFileSync('lib/actions/research.actions.ts', 'utf8');
const flowEs = JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8')).flow;
const route = readFileSync('data-engine/app/api/routes/news.py', 'utf8');

test('el flujo de noticias pagina dentro de la pagina, sin scroll infinito', () => {
  assert.doesNotMatch(flow, /IntersectionObserver/);
  assert.doesNotMatch(flow, /Cargar más/);
  assert.doesNotMatch(actions, /loadMoreResearchNews/);
  assert.match(flow, /label=\{t\('research\.flow\.paginationAria'\)\}/);
  assert.equal(flowEs.paginationAria, 'Paginación');
  assert.match(flow, /rel="prev"/);
  assert.match(flow, /rel="next"/);
  assert.match(flow, /'pagina'/);
});

test('la pagina pide al servidor la ventana de ?pagina y un evento extra para saber si hay siguiente', () => {
  assert.match(page, /pagina\?: string/);
  assert.match(page, /ticker\?: string/);
  assert.match(page, /getResearchNews\(\s*lane,\s*\(page - 1\) \* NEWS_PAGE_SIZE,\s*NEWS_PAGE_SIZE \+ 1,\s*ticker,\s*paraTiTickers,?\s*\)/);
  assert.match(page, /fetched\.length > NEWS_PAGE_SIZE/);
  assert.doesNotMatch(page, /events\.filter\(/);
});

test('el carril cambia de pagina conservando lane y la API acota limit/offset en SQL', () => {
  assert.match(flow, /query\.set\('lane', lane\)/);
  assert.match(route, /Annotated\[int, Query\(ge=1, le=100\)\] = 100/);
  assert.match(route, /offset: Annotated\[int, Query\(ge=0\)\] = 0/);
  assert.match(route, /lane: Literal\["empresa", "macro", "gobierno"\]/);
});

test('el móvil alcanza la siguiente página sin bajar treinta tarjetas',()=>{
 assert.match(readFileSync('lib/news-paging.ts','utf8'),/NEWS_PAGE_SIZE = 10/);
 assert.ok(flow.indexOf("label={t('research.flow.paginationAria')}")<flow.indexOf("t('research.flow.laneFilterAria')"));
 assert.match(flow,/label=\{t\('research\.flow\.paginationBottomAria'\)\}/);
 assert.equal(flowEs.paginationBottomAria,'Paginación inferior');
 assert.equal(flowEs.laneFilterAria,'Filtrar por carril');
});

test('solo quedan carriles de fuentes: Gobierno se conserva y Social desaparece', () => {
  assert.doesNotMatch(flow, /SocialChip|key: 'social'|StockTwits/);
  assert.doesNotMatch(page, /query\.lane === 'social'/);
  assert.doesNotMatch(actions, /lane === 'social'/);
  assert.match(flow, /key: 'gobierno', labelKey: 'research\.flow\.lane\.government'/);
  assert.equal(flowEs.lane.government, 'Gobierno');
  assert.match(route, /retired_lane != "social"/);
});
