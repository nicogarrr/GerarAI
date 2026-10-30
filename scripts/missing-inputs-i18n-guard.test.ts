import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import test from 'node:test';

// @ts-expect-error TS5097 importar un helper .ts puro desde el guard
const { metricLabel } = await import('../lib/research/metric-labels.ts');
// @ts-expect-error TS5097 importar un helper .ts puro desde el guard
const { frameworkTerm } = await import('../lib/research/framework-terms.ts');

// Misma resolución que termLabel (FundamentalModelPanels): marco primero, luego métricas.
const termLabel = (raw: string): string => frameworkTerm(raw) ?? metricLabel(raw);

// Los motores de valoración y el modelo a largo plazo publican sus entradas
// pendientes como claves (missing_inputs) y la ficha las pinta con termLabel
// («Valoración bloqueada: … faltan …», «Reverse DCF: No disponible: …»,
// «Beneficio del propietario: Insuficiente: …»). Una clave sin etiqueta caía
// al fallback y salía en inglés («adr ratio», «maintenance capex or capital
// expenditure», «fx rate:CNY/USD»). Se leen del código del backend para que
// una clave nueva pida su etiqueta en vez de colarse en inglés.
const ENGINES_DIR = 'data-engine/app/valuation';
const SOURCES = [
    ...readdirSync(ENGINES_DIR, { recursive: true, encoding: 'utf8' })
        .filter((name) => name.endsWith('.py'))
        .map((name) => path.join(ENGINES_DIR, name)),
    'data-engine/app/services/long_term_model_service.py',
    'data-engine/app/services/valuation_service.py',
    'data-engine/app/services/market_opportunity_service.py',
];
const LIST_PATTERNS = [
    /missing\w*\.(?:append|extend)\(\s*\[?([^)\n]*)/g,
    /missing_inputs["']?\s*[:=]\s*\[([^\]]*)\]/g,
];

function backendMissingInputKeys(): Map<string, string> {
    const keys = new Map<string, string>();
    for (const file of SOURCES) {
        const source = readFileSync(file, 'utf8');
        for (const pattern of LIST_PATTERNS) {
            for (const match of source.matchAll(pattern)) {
                for (const literal of match[1].matchAll(/["']([a-z][a-z0-9_]+)["']/g)) {
                    keys.set(literal[1], file);
                }
            }
        }
    }
    return keys;
}

test('ficha-4: toda entrada pendiente de los motores tiene etiqueta en español', () => {
    const keys = backendMissingInputKeys();
    assert.ok(keys.size >= 25, `el escaneo del backend encontró solo ${keys.size} claves: ¿cambió el patrón?`);
    const untranslated = [...keys]
        .filter(([key]) => termLabel(key) === key.replaceAll('_', ' '))
        .map(([key, file]) => `${key} (${file})`);
    assert.deepEqual(untranslated, []);
});

test('ficha-4: las claves revisadas a mano salen en español', () => {
    assert.equal(termLabel('adr_ratio'), 'ratio ADR (acciones ordinarias por ADR)');
    assert.equal(termLabel('maintenance_capex_or_capital_expenditure'), 'capex de mantenimiento o CapEx total');
    assert.equal(termLabel('fiscal_year'), 'ejercicio fiscal');
});

test('ficha-4: el tipo de cambio pendiente nombra el par de divisas', () => {
    // valuation_service y _reverse_dcf_price publican «fx_rate:<reporte>/<listado>».
    assert.equal(termLabel('fx_rate:CNY/USD'), 'tipo de cambio CNY/USD');
    assert.equal(termLabel('fx_rate:eur/usd'), 'tipo de cambio EUR/USD');
});
