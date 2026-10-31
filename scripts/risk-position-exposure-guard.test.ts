/**
 * Guard F43 (/risk «Exposición por posición»): el valor de mercado se
 * pintaba como número crudo («4524.072612») y el sector en inglés
 * («Technology»). market_value llega del backend en divisa base
 * (risk_service.py: value_base) y debe formatearse como dinero con la
 * divisa base del dashboard; el sector usa etiquetaSector (lib/labels).
 *
 * Ejecucion: node --experimental-strip-types --test scripts/risk-position-exposure-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const view = readFileSync('components/risk/RiskDashboardView.tsx', 'utf8');

describe('risk position exposure guard (F43)', () => {
  it('el valor de mercado se formatea como dinero con la divisa base', () => {
    assert.match(view, /f\.formatMoney\(numeric, baseCurrency\)/, 'formatMoney con baseCurrency (locale activo)');
    assert.equal(view.includes('formatRecordValue(position.market_value)'), false, 'sin numero crudo');
  });

  it('el sector usa etiqueta ES compartida, nunca el string inglés crudo', () => {
    assert.match(view, /etiquetaSector\(String\(sector\)\)/, 'etiquetaSector aplicada');
    assert.equal(view.includes('formatRecordValue(position.sector)'), false, 'sin sector crudo');
  });

  it('la divisa base viene del dashboard (misma regla que el resumen)', () => {
    assert.match(view, /dashboard\.base_currency/, 'base_currency del dashboard');
    assert.match(view, /\?\s*dashboard\.base_currency\s*:\s*'EUR'/, 'fallback EUR igual que humanizeRiskDashboard');
  });

  it('los nulos siguen siendo NA honesto (nunca «NaN €»)', () => {
    assert.match(view, /if \(!Number\.isFinite\(numeric\)\) return t\('common\.na'\);/, 'guardia de no numérico');
    assert.match(view, /if \(value === null \|\| value === undefined \|\| value === ''\) return t\('common\.na'\);/, 'guardia de ausente');
  });
});
