/**
 * Guardas de la frase "tu cartera en una linea" de /inicio (F38) y de la
 * divisa del valor total (F42).
 * Ejecución: node --experimental-strip-types --test scripts/portfolio-insight.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { buildPortfolioInsight, hasCostBasis } from '../lib/portfolio-insight.ts';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');
const source = (relativePath: string): string => readFileSync(join(root, relativePath), 'utf8');

describe('buildPortfolioInsight', () => {
  it('sin resumen o sin posiciones devuelve empty: la tarjeta pide la primera inversion', () => {
    assert.deepEqual(buildPortfolioInsight(null), { kind: 'empty' });
    assert.deepEqual(buildPortfolioInsight(undefined), { kind: 'empty' });
    assert.deepEqual(buildPortfolioInsight({ holdings: [] }), { kind: 'empty' });
  });

  it('posiciones sin base de coste no inventan una rentabilidad (F17)', () => {
    const insight = buildPortfolioInsight({
      holdings: [{ symbol: 'AAPL', cost: 0, gain: 0, gainPercent: 0 }],
    });
    assert.deepEqual(insight, { kind: 'no-cost-basis' });
  });

  it('posiciones con FX ausente tampoco entran en la frase de movimiento', () => {
    const insight = buildPortfolioInsight({
      holdings: [{ symbol: 'AAPL', cost: 100, gain: 10, gainPercent: 10, fxMissing: true }],
    });
    assert.deepEqual(insight, { kind: 'no-cost-basis' });
  });

  it('con base de coste resume el movimiento agregado y nombra la posicion con mayor variacion desde la compra', () => {
    const insight = buildPortfolioInsight({
      holdings: [
        { symbol: 'AAPL', cost: 100, gain: 10, gainPercent: 10 },
        { symbol: 'MSFT', cost: 300, gain: -30, gainPercent: -10 },
        { symbol: 'JPM', cost: 100, gain: 20, gainPercent: 20 },
      ],
    });
    assert.deepEqual(insight, {
      kind: 'movement',
      direction: 'up',
      totalPercent: 0, // (10 - 30 + 20) / 500 * 100
      topSymbol: 'JPM',
      topGainPercent: 20,
      partial: false,
    });
  });

  it('mezcla con posiciones sin base de coste: movimiento parcial, nunca global', () => {
    // AAPL con coste +10% y MSFT sin coste (fuera del calculo): el
    // porcentaje solo cubre AAPL y la frase debe declararlo; presentarlo
    // como global seria una afirmacion no verificable para toda la cartera.
    const insight = buildPortfolioInsight({
      holdings: [
        { symbol: 'AAPL', cost: 100, gain: 10, gainPercent: 10 },
        { symbol: 'MSFT', cost: 0, gain: 0, gainPercent: 0 },
      ],
    });
    assert.equal(insight.kind, 'movement');
    if (insight.kind === 'movement') {
      assert.equal(insight.partial, true);
      assert.equal(insight.totalPercent, 10);
    }
  });

  it('direction es down cuando el agregado es negativo', () => {
    const insight = buildPortfolioInsight({
      holdings: [{ symbol: 'MSFT', cost: 100, gain: -5, gainPercent: -5 }],
    });
    assert.equal(insight.kind, 'movement');
    if (insight.kind === 'movement') {
      assert.equal(insight.direction, 'down');
      assert.equal(insight.totalPercent, -5);
      assert.equal(insight.partial, false);
    }
  });
});

describe('guardas de regresion de /inicio', () => {
  it('el insight se deriva del resumen por useMemo, sin estado ni waterfall (F38)', () => {
    const overview = source('components/PersonalizedOverview.tsx');
    assert.ok(
      overview.includes('useMemo(() => buildPortfolioInsight(portfolioSummary), [portfolioSummary])'),
      'PersonalizedOverview debe derivar el insight del resumen con useMemo',
    );
    assert.ok(!overview.includes('setAiInsight'), 'PersonalizedOverview no debe recalcular el insight tras el waterfall');
    assert.ok(
      overview.includes('Entre las posiciones con base de coste'),
      'la frase parcial debe declarar que cubre solo las posiciones con base de coste',
    );
  });

  it('el valor total de la cartera se formatea en su divisa base, no en USD fijo (F42)', () => {
    const overview = source('components/PersonalizedOverview.tsx');
    assert.ok(
      overview.includes('<PortfolioValueBreakdown summary={portfolioSummary} />')
        && source('components/portfolio/PortfolioValueBreakdown.tsx').includes('formatMoney(totalValue, baseCurrency)'),
      'el total de "Tu cartera hoy" debe usar portfolioSummary.baseCurrency',
    );
  });
});

describe('hasCostBasis (F2)', () => {
  it('sin coste conocido el coste, la ganancia y el rendimiento son N/D, no 0', () => {
    assert.equal(hasCostBasis(null), false);
    assert.equal(hasCostBasis({ holdings: [] }), false);
    assert.equal(
      hasCostBasis({ holdings: [{ symbol: 'A', cost: 0, gain: 0, gainPercent: 0 }] }),
      false,
    );
    assert.equal(
      hasCostBasis({ holdings: [{ symbol: 'A', cost: 100, gain: 5, gainPercent: 5, fxMissing: true }] }),
      false,
    );
    assert.equal(
      hasCostBasis({ holdings: [{ symbol: 'A', cost: 100, gain: 5, gainPercent: 5 }] }),
      true,
    );
  });

  // El resumen de cartera (N/D sin base de coste) se comprueba renderizándolo:
  // tests/unit/components/PortfolioSummary.test.tsx.
});
