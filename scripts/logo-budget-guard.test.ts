/**
 * Guard: /api/logo tiene un presupuesto total duro. Medido en prod
 * (31-oct-2026, cuenta Claude B): /api/logo/AENA tardó 10.3s y Vercel la
 * mató con 504 (función Hobby de 10s); /api/logo/GOOGLE tardó 1.447ms en
 * 404. fetchSiteIcon encadena home + candidatos con timeout de 8s CADA uno;
 * sin presupuesto total, un icono lento cuelga la función y gasta CPU.
 */
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import assert from 'node:assert/strict';

test('/api/logo acota la resolución completa con cancelación real', () => {
    const route = readFileSync('app/api/logo/[ticker]/route.ts', 'utf8');
    assert.ok(route.includes('LOGO_TOTAL_BUDGET_MS'), 'falta el presupuesto total');
    assert.ok(route.includes('new AbortController()'), 'falta el AbortController del presupuesto');
    assert.ok(route.includes('controller.abort()'), 'el temporizador debe abortar de verdad');
    assert.ok(route.includes('AbortSignal.any'), 'la señal debe componerse con la de cada fetch');
    assert.ok(!route.includes('AbortSignal.timeout(5000)'), 'Finnhub no puede seguir con 5s de timeout');
    const budget = readFileSync('lib/logos/logo-budget.ts', 'utf8');
    assert.ok(budget.includes('LOGO_TOTAL_BUDGET_MS = 4000'), 'el presupuesto vive en lib/logos/logo-budget.ts');
});
