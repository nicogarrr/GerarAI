/**
 * F6 (continuación de #828): el bloque «Detalle avanzado» sale de la misma
 * serie indicativa que el TWR cuando twr_is_exact=false (anualizado,
 * volatilidad, Sortino, VaR/CVaR, Calmar y Beta usan portfolio_returns en
 * portfolio_intelligence_service). Cada tarjeta lleva el mismo aviso.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const page = readFileSync('app/(root)/portfolio/intelligence/page.tsx', 'utf8');
const dict = JSON.parse(readFileSync('lib/i18n/messages/es/portfolio.json', 'utf8'));

// Las etiquetas viven en el diccionario i18n: la página selecciona la clave
// exacta/indicativa segun twr_is_exact y el valor es se verifica aqui.
for (const [exactKey, indicativeKey, exact, indicative] of [
    ['metricAnnualized', 'metricAnnualizedIndicative', 'Anualizado', 'Anualizado indicativo'],
    ['metricVolatility', 'metricVolatilityIndicative', 'Volatilidad', 'Volatilidad indicativa'],
    ['metricSortino', 'metricSortinoIndicative', 'Sortino', 'Sortino indicativo'],
    ['metricVar', 'metricVarIndicative', 'VaR 95%', 'VaR 95% indicativo'],
    ['metricCvar', 'metricCvarIndicative', 'CVaR 95%', 'CVaR 95% indicativo'],
    ['metricCalmar', 'metricCalmarIndicative', 'Calmar', 'Calmar indicativo'],
    ['metricBeta', 'metricBetaIndicative', 'Beta', 'Beta indicativa'],
]) {
    test(`${exact} se rotula indicativo cuando el TWR no es exacto`, () => {
        assert.ok(
            page.includes(`twr_is_exact ? ti('portfolio.intelligence.${exactKey}') : ti('portfolio.intelligence.${indicativeKey}')`),
            `la página elige entre ${exactKey} y ${indicativeKey}`,
        );
        assert.equal(dict.intelligence[exactKey], exact, 'valor es de la etiqueta exacta');
        assert.equal(dict.intelligence[indicativeKey], indicative, 'valor es de la etiqueta indicativa');
    });
}
