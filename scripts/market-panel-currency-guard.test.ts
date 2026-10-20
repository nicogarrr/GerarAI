/**
 * F380b: superficies de mercado no caen a USD con una divisa inválida.
 * Sin divisa válida se muestra el número sin símbolo, nunca USD por defecto.
 * (El panel CompanyMarketPanel se eliminó por código muerto; queda movers.)
 * Ejecución: node --experimental-strip-types --test scripts/market-panel-currency-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const movers = readFileSync(join(root, 'components/market/MoversTable.tsx'), 'utf8');

describe('movers: divisa', () => {
    it('no asume USD con una divisa ausente o inválida', () => {
        assert.ok(!/'USD'/.test(movers), "la página de movers no debe contener 'USD' literal");
        assert.ok(!movers.includes('safeCurrency'), 'safeCurrency (caía a USD) queda eliminado');
        assert.match(
            movers,
            /isValidCurrencyCode\(row\.currency\) \? formatPrice\(row\.price, row\.currency\) : formatNumber\(row\.price\)/,
        );
    });
});
