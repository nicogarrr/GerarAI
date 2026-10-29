import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const quote = readFileSync('components/research/CompanyHeaderQuote.tsx', 'utf8');
const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
const navigation = readFileSync('components/research/CompanyNavigation.tsx', 'utf8');
describe('ficha: cifra grande y métricas compactas', () => {
    it('precio grande y variación en píldora, neutro si es cero', () => {
        assert.match(quote, /text-4xl/);
        assert.match(quote, /rounded-full/);
        assert.match(quote, /signBase > 0/);
        assert.match(quote, /signBase < 0/);
        assert.match(quote, /text-emerald-300/);
        assert.match(quote, /text-red-300/);
    });
    it('cuatro métricas verificadas de la cotización, sin adivinar múltiplos', () => {
        assert.match(quote, /company-metric-strip/);
        for (const label of ['Apertura', 'Máximo', 'Mínimo', 'Cierre anterior']) assert.ok(quote.includes(label));
        assert.match(quote, /value == null \|\| !isValidCurrencyCode\(currency\) \? NA : headerMoney/);
        // Nico (29-oct-2026): el USD de cabecera va en es-ES como el resto de divisas.
        assert.match(quote, /function headerMoney[\s\S]*?return formatMoney\(value, currency/);
        assert.match(quote, /return formatMoney\(value, currency\)/);
        assert.match(quote, /divide-gray-800/);
        assert.match(quote, /isValidCurrencyCode\(currency\)/);
    });
    it('pestañas limpias sin borrar rutas ni módulos', () => {
        assert.match(navigation, /primary === group \? 'border-teal-300 text-gray-100'/);
        const views = readFileSync('lib/research/research-views.ts', 'utf8');
        for (const view of ['resumen', 'numeros', 'fuentes', 'mas']) assert.ok(views.includes(`key: '${view}'`));
        // Las 6 claves de grupo antiguas siguen abriendo su módulo (compat ?view=), en un Map (sin prototipo).
        for (const legacy of ['resumen', 'tesis', 'financieros', 'modelo', 'evidencia', 'seguimiento']) assert.ok(views.includes(`['${legacy}',`));
        assert.doesNotMatch(page, /captura de solo lectura/);
    });
});

it('alertas anuncia una sola copia de carga traducida', () => {
    const alerts = readFileSync('components/alerts/AlertsManager.tsx', 'utf8');
    assert.doesNotMatch(alerts, /Cargando alertas[.…]/);
    assert.match(alerts, /t\('common.states.loadingAlerts'\)/);
});
