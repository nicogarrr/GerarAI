/**
 * Guard del tearsheet de cartera: Sharpe sin dato es N/D en color neutro
 * (nunca verde por defecto) y las métricas llevan su fecha de corte.
 * Ejecución: node --experimental-strip-types --test scripts/portfolio-tearsheet-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const view = readFileSync('components/portfolio/PortfolioTearsheet.tsx', 'utf8');

describe('tearsheet: honestidad de Sharpe y fecha de corte', () => {
    it('Sharpe null no se pinta verde (?? 0 convertía N/D en positivo)', () => {
        assert.ok(!/sharpe \?\? 0\)? >= 0/.test(view.replace(/\s+/g, ' ')), 'sharpe ?? 0 >= 0 pinta N/D en verde');
        assert.match(view, /metrics\.sharpe === null \? 'text-gray-400'/);
    });
    it('las métricas declaran la fecha de corte de los datos', () => {
        // i18n: el texto vive en messages/<locale>/portfolio.json.
        assert.match(view, /portfolio\.tearsheetExtra\.exposureAsOf/);
        assert.match(view, /f\.formatDate\(tearsheet\.exposure\.snapshot_date\)/);
        const dict = JSON.parse(readFileSync('lib/i18n/messages/es/portfolio.json', 'utf8'));
        assert.ok(dict.tearsheetExtra.exposureAsOf.includes('datos hasta el '), 'valor es de la fecha de corte');
    });
});
