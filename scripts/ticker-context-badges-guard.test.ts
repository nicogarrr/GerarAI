/**
 * Quick win UX 5: badges «En cartera / En watchlist» en noticias y movers.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { openPositionTickers, tickerBadgesFor, TICKER_BADGE_LABELS } from '../lib/ticker-badges.ts';

const news = (readFileSync('app/(root)/research/news/page.tsx', 'utf8') + readFileSync('components/research/NewsEventsFlow.tsx', 'utf8'));
const movers = (readFileSync('components/market/MoversTable.tsx', 'utf8') + readFileSync('app/(root)/screener/page.tsx', 'utf8'));
const action = readFileSync('lib/actions/ticker-context.actions.ts', 'utf8');

test('la pertenencia se calcula por ticker normalizado', () => {
    const portfolio = new Set(['COST']);
    const watchlist = new Set(['NFLX']);
    assert.deepEqual(tickerBadgesFor('cost', portfolio, watchlist), ['portfolio']);
    assert.deepEqual(tickerBadgesFor('NFLX', portfolio, watchlist), ['watchlist']);
    assert.deepEqual(tickerBadgesFor('AAPL', portfolio, watchlist), []);
    assert.deepEqual(tickerBadgesFor('COST', new Set(['COST']), new Set(['COST'])), ['portfolio', 'watchlist']);
    assert.equal(TICKER_BADGE_LABELS.portfolio, 'En cartera');
    assert.equal(TICKER_BADGE_LABELS.watchlist, 'En watchlist');
});

test('«En cartera» exige posición abierta: quantity numérica y no nula', () => {
    // Una posición cerrada importada por IBKR (quantity 0) no lleva badge:
    // afirmar «En cartera» sin posición sería falso. El corto (quantity < 0)
    // es exposición abierta y sí lo lleva.
    const positions = [
        { ticker: 'COST', quantity: 3 },
        { ticker: 'NFLX', quantity: 0 },
        { ticker: 'TSLA', quantity: -2 },
        { ticker: 'AAPL', quantity: null },
        { ticker: ' msft ', quantity: 1 },
    ];
    assert.deepEqual(openPositionTickers(positions), ['COST', 'TSLA', 'MSFT']);
});

test('la acción filtra por posición abierta, no por mera presencia', () => {
    assert.match(action, /openPositionTickers\(positions\)/);
    assert.match(action, /quantity: number \| null/);
});

test('la lectura degrada a conjuntos vacíos, nunca a badges fabricados', () => {
    assert.match(action, /\.catch\(\(\) => \[\] as Array<\{ ticker: string; quantity: number \| null \}>\)/);
    assert.match(action, /\.catch\(\(\) => \[\] as Array<\{ symbol: string \}>\)/);
});

test('noticias y movers componen los badges junto al ticker', () => {
    for (const src of [news, movers]) {
        assert.match(src, /getTickerContext\(\)/);
        assert.match(src, /<TickerContextBadges/);
    }
    // En noticias, solo cuando hay ticker (los eventos macro no llevan).
    assert.match(news, /\{event\.ticker \? \(/);
    // En Mercado, la tabla de subidas/bajadas/activas recibe el contexto.
    assert.equal((movers.match(/tickerSets=\{tickerSets\}/g) ?? []).length, 1);
});

 test('las tarjetas móviles conservan el contexto de cartera y watchlist', () => {
    const flow = readFileSync('components/research/NewsEventsFlow.tsx', 'utf8');
    const mobile = flow.slice(flow.indexOf("<ul aria-label={t('research.flow.listAria')}"), flow.indexOf('</ul>'));
    assert.equal(JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8')).flow.listAria, 'Eventos de noticias');
    assert.match(mobile, /<TickerContextBadges/);
    assert.match(mobile, /portfolioTickers=\{portfolioSet\}/);
    assert.match(mobile, /watchlistTickers=\{watchlistSet\}/);
});
