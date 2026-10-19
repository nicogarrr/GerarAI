/**
 * F253/F254: la watchlist (página y panel de /inicio) pedía la cotización con
 * el ticker DESNUDO a Finnhub: para un emisor no-US eso devuelve el gemelo
 * americano (ASML salía a 1.743,94 US$ mientras research muestra Amsterdam a
 * 1.522,60 €) u OTRO emisor (ALM -> Almonty), y AENA salía «sin datos» pese
 * a tener cotización vía .MC. Además el precio se formateaba SIEMPRE como
 * USD. Contrato: el símbolo y la divisa los decide el master
 * (quoteSymbolFor + getResearchCompanyBasics) vía getWatchlistEntryData.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const page = readFileSync('app/(root)/watchlist/page.tsx', 'utf8');
const overview = `${readFileSync('components/PersonalizedOverview.tsx', 'utf8')}\n${readFileSync('lib/actions/home-overview.actions.ts', 'utf8')}`;
const action = readFileSync('lib/actions/watchlist.actions.ts', 'utf8');

for (const [name, src] of [['watchlist page', page], ['inicio overview', overview]] as const) {
    test(`${name}: cotización vía getWatchlistEntryData (master), nunca ticker desnudo`, () => {
        assert.match(src, /getWatchlistEntryData/);
        assert.ok(
            !/getStockFinancialData\(item\.symbol\)|getStockQuote\(item\.symbol\)/.test(src),
            'el ticker desnudo resuelve en la línea US (ADR u homónimo)',
        );
    });

    test(`${name}: el precio nunca se formatea con USD asumido`, () => {
        assert.ok(
            !/format(Price|Money)\(stock\.price,\s*'USD'\)|format(Price|Money)\(stock\.price\)/.test(src),
            'un «US$» asumido contradice la divisa real del listado',
        );
    });
}

test('la acción resuelve símbolo y divisa con el master', () => {
    assert.match(action, /quoteSymbolFor\(basics, normalized\)/);
    assert.match(action, /getResearchCompanyBasics\(normalized\)/);
});

test('métricas Finnhub solo para líneas US (nunca del ADR ni de un homónimo)', () => {
    // La variante cambia (getStockValuationBasics: solo profile2+metric, sin /quote
    // duplicada ni /price-target); la condición que fija el guard se mantiene:
    // métricas Finnhub SOLO para líneas US, nunca del ADR ni de un homónimo.
    assert.match(action, /usListing \? getStockValuationBasics\(normalized\) : Promise\.resolve\(null\)/);
});

test('sin correspondencia validada: «sin datos», nunca el ticker desnudo', () => {
    assert.match(action, /if \(!quoteSymbol\) return base;/);
});

test('la divisa visible la pone solo el master: nunca un USD inventado', () => {
    assert.match(action, /currency: base\.currency/);
    assert.ok(!/\? 'USD' : null/.test(action), 'asumir USD sin divisa real contradice F253');
});

test('el market cap declara su divisa (formato multi-divisa con la divisa real)', () => {
    assert.equal(
        page.match(/stock\.marketCap !== null \? formatMarketCap\(stock\.marketCap, stock\.currency\) : NA/g)?.length ?? 0,
        2,
        'tarjeta y tabla: valor con divisa real solo con dato; null es NA pelado',
    );
    assert.ok(
        !/formatMarketCapUsd\(stock\.marketCap\)/.test(page),
        'el cap ya no es solo-US (respaldo backend): formatear siempre en $ inventaría la divisa',
    );
});
