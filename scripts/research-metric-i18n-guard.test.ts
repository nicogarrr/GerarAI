import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
const panels = readFileSync('components/research/FactsPanels.tsx', 'utf8');
// @ts-expect-error TS5097 importar un helper .ts puro desde el guard
const { METRIC_LABELS, metricLabel } = await import('../lib/research/metric-labels.ts');

// Catalogo canonico del backend: claves de FinancialFact
// (financial_ingestion_service.py, ingesta + derivadas) y de CalculatedMetric
// (metric_calculation_service.py). Si el backend crece, este test pide la
// etiqueta correspondiente en vez de dejar pasar snake_case a la UI.
const BACKEND_CATALOG = [
    'revenue', 'gross_profit', 'operating_income', 'income_before_tax',
    'income_tax_expense', 'interest_expense', 'net_income', 'ebitda',
    'eps_diluted', 'shares_diluted', 'total_assets', 'total_liabilities',
    'total_equity', 'total_debt', 'net_debt', 'cash_and_equivalents',
    'goodwill', 'intangible_assets', 'operating_lease_liabilities',
    'operating_cash_flow', 'capital_expenditure', 'depreciation_amortization',
    'free_cash_flow', 'dividends_paid', 'common_stock_repurchased',
    'common_stock_issued',
    'fcf_margin', 'gross_margin', 'operating_margin', 'net_margin',
    'effective_tax_rate', 'debt_to_equity', 'revenue_growth',
    'roic', 'roic_adjusted', 'roe', 'roa', 'fcf_conversion',
    'net_debt_to_ebitda', 'asset_life', 'gross_investment',
    'inflation_adjusted_gross_cash_flow', 'non_depreciating_assets',
    'terminal_non_depreciating_assets', 'fcf_margin_5y', 'net_margin_5y',
    'wacc', 'cfroi', 'cfroi_approx',
];

test('F321: el mapa cubre todo el catalogo canonico del backend', () => {
    for (const key of BACKEND_CATALOG) {
        assert.ok(METRIC_LABELS[key], `falta etiqueta para ${key}`);
        assert.ok(!/[a-z]_[a-z]/.test(METRIC_LABELS[key]), `${key} sigue en snake_case`);
    }
});

test('F321: el fallback humaniza claves desconocidas sin ocultarlas', () => {
    assert.equal(metricLabel('metrica_nueva_del_backend'), 'metrica nueva del backend');
    assert.equal(metricLabel('revenue'), 'Ingresos');
});

test('QA 21-oct: claves vista en prod con fallback en inglés tienen etiqueta', () => {
    // Verificado en la ficha de ASTS (21-oct-2026): «common stock issued» y
    // «products revenue» se pintaban en inglés en Hechos financieros canónicos.
    assert.equal(metricLabel('common_stock_issued'), 'Emisión de acciones ordinarias');
    assert.equal(metricLabel('common stock issued'), 'Emisión de acciones ordinarias');
    assert.equal(metricLabel('products_revenue'), 'Ingresos por productos');
    assert.equal(metricLabel('products revenue'), 'Ingresos por productos');
});

test('F321: la ficha usa metricLabel en hechos y metricas calculadas', () => {
    // Los hechos (tarjeta movil y tabla) viven en FactsPanels.
    assert.match(panels, /\{metricLabel\(fact\.metric, locale\)\}<\/span>/);
    assert.match(panels, /scope="row">\{metricLabel\(fact\.metric, locale\)\}<\/th>/);
    assert.match(page, /\{metricLabel\(metric\.metric, locale\)\}<\/span>/);
});

test('F321: los estados ok/unavailable del backend tienen etiqueta en espanol', () => {
    assert.match(page, /ok: 'disponible'/);
    assert.match(page, /unavailable: 'no disponible'/);
});
