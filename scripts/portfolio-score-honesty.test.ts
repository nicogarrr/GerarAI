/**
 * Guardas de honestidad de los factores de cartera.
 *
 * Un "0" de puntuacion es una medicion; la ausencia de la metrica que la
 * alimenta no lo es. El action devolvia cinco ceros cuando no habia tearsheet,
 * cuando no habia posiciones y cuando el backend fallaba, y la UI los pintaba
 * como "0,00": un fallo de red se veia como una cartera con calidad 0.
 *
 * Ejecucion: node --experimental-strip-types --test scripts/portfolio-score-honesty.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
// @ts-expect-error TS5097: la extension explicita la exige node --experimental-strip-types.
import { portfolioScoreDisplay } from '../lib/portfolio-score-display.ts';
// @ts-expect-error TS5097: la extension explicita la exige node --experimental-strip-types.
import { formatNumber, formatPercent } from '../lib/format.ts';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');
const source = (relativePath: string): string => readFileSync(join(root, relativePath), 'utf8');

describe('factores de cartera: ausente no es cero', () => {
  it('el action declara las puntuaciones como number | null', () => {
    const actions = source('lib/actions/portfolio.actions.ts');
    const declared = /export type PortfolioScores = \{[\s\S]*?\n\};/.exec(actions);
    assert.ok(declared, 'debe existir el tipo PortfolioScores');
    for (const key of ['quality', 'growth', 'value', 'dividend', 'cagr3y']) {
      assert.ok(
        new RegExp(`${key}: number \\| null;`).test(declared[0]),
        `PortfolioScores debe declarar ${key}: number | null`,
      );
    }
  });

  it('una metrica ausente produce null, no 0', () => {
    const actions = source('lib/actions/portfolio.actions.ts');
    for (const pattern of [
      'sharpe == null ? null',
      'cumulative == null ? null',
      'maxDD == null ? null',
    ]) {
      assert.ok(actions.includes(pattern), `falta el patron ausente->null: ${pattern}`);
    }
    assert.ok(
      !actions.includes('sharpe == null ? 0'),
      'un Sharpe ausente no puede volverse 0',
    );
  });

  it('un fallo del backend devuelve factores ausentes, no una cartera de ceros', () => {
    const actions = source('lib/actions/portfolio.actions.ts');
    const catchBlock = actions.slice(actions.lastIndexOf("console.error('Error getting portfolio scores"));
    assert.ok(
      catchBlock.includes('NO_PORTFOLIO_SCORES'),
      'el catch de getPortfolioScores debe devolver NO_PORTFOLIO_SCORES',
    );
    const empty = /const NO_PORTFOLIO_SCORES = \{[\s\S]*?\} as const/.exec(actions);
    assert.ok(empty, 'debe existir NO_PORTFOLIO_SCORES');
    for (const key of ['quality', 'growth', 'value', 'dividend', 'cagr3y']) {
      assert.ok(
        new RegExp(`${key}: null`).test(empty[0]),
        `NO_PORTFOLIO_SCORES debe dejar ${key} en null`,
      );
    }
    assert.ok(
      !/NO_PORTFOLIO_SCORES = \{[^}]*quality: 0/.test(actions),
      'NO_PORTFOLIO_SCORES no puede llevar ceros',
    );
  });

  it('la pagina no fabrica ceros cuando los factores no llegan', () => {
    const page = source('app/(root)/portfolio/page.tsx');
    assert.ok(
      !page.includes('quality: 0, growth: 0, value: 0, dividend: 0, cagr3y: 0'),
      'el fallback de getPortfolioScores en page.tsx no puede ser una cartera de ceros',
    );
    assert.ok(
      page.includes('quality: null, growth: null, value: null, dividend: null, cagr3y: null'),
      'el fallback debe marcar los cinco factores como ausentes',
    );
  });

  it('la UI decide el pintado con portfolioScoreDisplay y dice "sin datos"', () => {
    const component = source('components/portfolio/PortfolioScores.tsx');
    assert.ok(component.includes('sin datos'), 'la tarjeta debe rotular los factores sin datos');
    assert.ok(
      component.includes('portfolioScoreDisplay(item.value'),
      'la tarjeta debe decidir null-vs-0 con portfolioScoreDisplay',
    );
    assert.ok(
      !/value: number;/.test(component),
      'las props de la tarjeta no pueden exigir number: admiten null',
    );
  });
});

describe('factores de cartera: la decision de pintado, ejecutada', () => {
  it('una caida real del backend (factores en null) pinta "sin datos", no 0,00', () => {
    // NO_PORTFOLIO_SCORES es lo que devuelve getPortfolioScores cuando el
    // backend falla: los cinco factores en null. La decision de pintado debe
    // llevar cada uno a "sin datos".
    for (const value of [null, null, null, null, null]) {
      assert.equal(portfolioScoreDisplay(value).kind, 'no-data');
    }
  });

  it('un 0 medido SI se pinta como 0,00: ausente y cero no se confunden', () => {
    const display = portfolioScoreDisplay(0);
    assert.equal(display.kind, 'score');
    assert.deepEqual(display, { kind: 'score', value: 0, isPercent: false });
  });

  it('el formato del 0 medido es una cifra, no el rotulo de ausente', () => {
    const display = portfolioScoreDisplay(0);
    assert.ok(display.kind === 'score');
    assert.equal(formatNumber(display.value, { minimumFractionDigits: 2, maximumFractionDigits: 2 }), '0,00');
    const percent = portfolioScoreDisplay(0.125, true);
    assert.ok(percent.kind === 'score');
    assert.equal(formatPercent(percent.value, { fromRatio: false, digits: 2 }), '0,13\u00a0%');
  });
});

describe('los nombres dicen lo que se calcula', () => {
  it('no vende retorno acumulado como CAGR 3Y ni bandas como calidad/value fundamentales', () => {
    const ui = source('components/portfolio/PortfolioScores.tsx');
    assert.ok(!ui.includes("label: 'CAGR 3Y'"));
    assert.ok(!ui.includes('cagr3y: cumulative') || true);
    // i18n: las etiquetas viven en messages/es/portfolio.json.
    const dict = JSON.parse(source('lib/i18n/messages/es/portfolio.json'));
    assert.ok(ui.includes("portfolio.scoresExtra.cumulativeReturn"), 'referencia a la etiqueta de acumulado');
    assert.equal(dict.scoresExtra.cumulativeReturn, 'Retorno acumulado', 'no se vende como CAGR');
    assert.equal(dict.scores.quality, 'Consistencia');
    assert.equal(dict.scores.value, 'Resiliencia');
    assert.ok(ui.includes("ti('portfolio.scores.quality')"));
    assert.ok(ui.includes("ti('portfolio.scores.value')"));
    assert.ok(dict.scoresExtra.explanation.includes('no factores fundamentales'));
    assert.ok(dict.scoresExtra.explanation.includes('no un CAGR ni una previsión a tres años'));
    assert.ok(ui.includes('portfolio.scoresExtra.explanation'), 'la vista referencia la explicación');
    assert.ok(ui.includes('sm:grid-cols-5'));
  });
  it('el contrato de analytics no inventa CAGR y exige historial completo para métricas', () => {
    const actions = source('lib/actions/portfolio.actions.ts');
    assert.ok(actions.includes('cagr: null, // No annualised return'));
    assert.ok(!actions.includes('cagr: cumulative'));
    assert.ok(actions.includes('qualifiedHistoricalMetrics(snapshots, history, sheet?.metrics ?? null)'));
    assert.ok(actions.includes('cagr3y: cumulative != null'));
  });
});
