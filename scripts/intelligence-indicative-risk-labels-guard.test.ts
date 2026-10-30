/**
 * F6: con twr_is_exact=false, Sharpe y caída máxima salen de la MISMA serie
 * indicativa (pesos estáticos actuales) que el TWR (portfolio_intelligence_
 * service: portfolio_returns = indicative_returns). Solo el TWR se rotulaba
 * como indicativo; las tres tarjetas deben llevar el mismo aviso.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const page = readFileSync('app/(root)/portfolio/intelligence/page.tsx', 'utf8');

test('Sharpe y caída máxima se rotulan indicativos cuando el TWR no es exacto', () => {
    // i18n: la página elige la clave exacta/indicativa; los valores es se verifican aquí.
    const dict = JSON.parse(readFileSync('lib/i18n/messages/es/portfolio.json', 'utf8'));
    for (const [exactKey, indicativeKey, exact, indicative] of [
        ['kpiSharpe', 'kpiSharpeIndicative', 'Sharpe', 'Sharpe indicativo'],
        ['kpiMaxDrawdown', 'kpiMaxDrawdownIndicative', 'Máx. caída', 'Máx. caída indicativa'],
        ['kpiTwrDaily', 'kpiTwrIndicative', 'TWR diario', 'TWR indicativo'],
    ]) {
        assert.ok(
            page.includes(`twr_is_exact ? ti('portfolio.intelligence.${exactKey}') : ti('portfolio.intelligence.${indicativeKey}')`),
            `la página elige entre ${exactKey} y ${indicativeKey}`,
        );
        assert.equal(dict.intelligence[exactKey], exact);
        assert.equal(dict.intelligence[indicativeKey], indicative);
    }
});
