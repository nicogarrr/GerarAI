import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// El copy vive en el diccionario i18n (landing.json); el guard sigue
// comprobando el texto exacto, ahora contra el diccionario + la página.
const metodologia = readFileSync('app/(public)/metodologia/page.tsx', 'utf8')
  + readFileSync('lib/i18n/messages/es/landing.json', 'utf8');
const ficha = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');

test('F325: la metodología describe el uso real de FMP (solo US), no un retiro inexistente', () => {
    // La ficha ofrece «Refrescar financieros (FMP)» en tickers US mientras la
    // metodología decía «FMP retirado, ningún cálculo depende de FMP».
    assert.match(ficha, /Refrescar financieros \(FMP\)/);
    assert.doesNotMatch(metodologia, /FMP retirado/);
    assert.doesNotMatch(metodologia, /Ningún cálculo actual\s+depende de FMP/);
    assert.match(metodologia, /FMP solo cubre mercado US/);
    // El copy no promete restriccion en la app ni cobertura universal
    // EDGAR/ESEF: FMP rechaza fuera de US y la cobertura regulatoria
    // depende del emisor.
    assert.match(metodologia, /La API acepta el refresco con FMP para cualquier emisor/);
    // No hay fallback automatico: EDGAR/ESEF son acciones separadas del
    // usuario, no una sustitucion.
    assert.match(metodologia, /No hay sustitución automática/);
    assert.match(metodologia, /acción separada/);
    assert.doesNotMatch(metodologia, /el resto se sirve de SEC EDGAR y ESEF/);
    assert.doesNotMatch(metodologia, /se recurre a SEC EDGAR o ESEF/);
});

test('F325: el copy de precios distingue FMP, Finnhub y Yahoo según ruta real', () => {
    const backend = readFileSync('data-engine/app/services/market_refresh_service.py', 'utf8');
    const propicks = readFileSync('data-engine/app/services/propicks_price_service.py', 'utf8');
    const workers = readFileSync('data-engine/app/workers/dramatiq_app.py', 'utf8');
    assert.match(backend, /if self\.fmp\.configured\(\)/);
    assert.match(backend, /self\.fmp\.quote\(company\.ticker, max_retries=0\)/);
    assert.match(backend, /if timestamp <= 0:/);
    assert.match(backend, /if self\.finnhub\.configured\(\)/);
    assert.match(backend, /if not _us_listed\(company\):/);
    assert.match(workers, /YahooIntradayPriceProvider\(\)/);
    assert.match(propicks, /fetch_history_yfinance/);
    assert.match(propicks, /_EXCHANGE_YAHOO_SUFFIX/);
    assert.doesNotMatch(metodologia, /Los precios vienen de Finnhub y Yahoo Finance/);
    assert.match(metodologia, /los listados US se consultan primero en FMP si hay clave/);
    assert.match(metodologia, /Finnhub es el fallback/);
    assert.match(metodologia, /Yahoo Finance aporta el refresco intradía de cartera/);
    assert.match(metodologia, /Sin cotización o símbolo fiable, se muestra sin precio/);
});
