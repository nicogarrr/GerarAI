/**
 * Guard F143 (distintivo de tenencia en la ficha de research): el badge
 * junto al ticker refleja la posicion viva del tenant
 * (snapshot.in_portfolio, calculado en backend desde `positions`), NO la
 * clase estatica companies.company_type fijada al alta de la ficha.
 *
 * Bug original (prod): AAPL con 12 acciones en cartera mostraba
 * "candidato de analisis" (company_type=research_candidate) y SPCX, sin
 * posicion del tenant, mostraba "portfolio holding" - en ingles, porque
 * 'portfolio_holding' no tiene traduccion y label() cae al fallback crudo.
 *
 * Ejecucion: node --experimental-strip-types --test scripts/portfolio-holding-badge-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');

describe('portfolio holding badge guard (F143)', () => {
  it('el badge usa la tenencia viva del snapshot', () => {
    assert.match(page, /snapshot\.in_portfolio/, 'el badge debe derivarse de snapshot.in_portfolio');
    assert.ok(page.includes("t('research.fichaInPortfolio')"), 'la tenencia viva se etiqueta via i18n');
    const esResearch = JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8'));
    assert.equal(esResearch['fichaInPortfolio'], 'en cartera', 'el literal ES visible no cambia');
  });

  it('company_type ya no se pinta directamente como badge', () => {
    assert.equal(
      page.includes('{label(company.company_type)}'),
      false,
      'company_type es estatico y miente en los dos sentidos; no puede ser el badge',
    );
  });

  it('portfolio_holding sin posicion viva no sobrevive como etiqueta', () => {
    assert.match(
      page,
      /company_type === 'portfolio_holding' \? 'research_candidate'/,
      'un portfolio_holding estatico sin posicion viva se muestra como candidato de analisis',
    );
  });
});
