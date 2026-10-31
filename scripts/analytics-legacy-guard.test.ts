/**
 * Guarda de la API analytics legacy (F72): el backend retiró /analytics/*
 * intencionadamente (data-engine/tests/test_analytics_endpoints.py garantiza
 * el 404), así que el frontend no puede llamar a esa superficie ni montar
 * UI para funciones que solo existían ahí (pestaña Simulación Monte Carlo).
 * Ejecución: node --experimental-strip-types --test scripts/analytics-legacy-guard.test.ts
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join, extname } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');

const walk = (dir: string): string[] =>
    readdirSync(dir).flatMap((name) => {
        const path = join(dir, name);
        if (statSync(path).isDirectory()) {
            return walk(path);
        }
        return ['.ts', '.tsx'].includes(extname(name)) ? [path] : [];
    });

const frontendFiles = ['app', 'components', 'lib'].flatMap((dir) => walk(join(root, dir)));

void test('ningún archivo del frontend llama a la superficie legacy /analytics/*', () => {
    const offenders = frontendFiles.filter((path) => readFileSync(path, 'utf8').includes('/analytics/'));
    assert.deepEqual(offenders.map((path) => path.slice(root.length + 1)), []);
});

void test('la pestaña Simulación (Monte Carlo retirado) no vuelve sin un endpoint real', () => {
    const offenders = frontendFiles.filter((path) => /montecarlo|PortfolioRiskSimulator|generateRiskAnalysis/i.test(readFileSync(path, 'utf8')));
    assert.deepEqual(offenders.map((path) => path.slice(root.length + 1)), []);
});

void test('ningún copy ni comentario remite a la pestaña Simulación retirada', () => {
    // F130 bonus: quedaban remisiones visibles en /risk y /portfolio/intelligence
    // ("el riesgo simulado, la pestaña Simulación"). La única simulación legítima
    // que queda es el backtest walk-forward de ProPicks.
    const offenders = frontendFiles.filter((path) => {
        const text = readFileSync(path, 'utf8').replace(/simulación walk-forward/gi, '');
        return /simulaci/i.test(text);
    });
    assert.deepEqual(offenders.map((path) => path.slice(root.length + 1)), []);
});

void test('Exposiciones no niega medidas que Inteligencia sí ofrece (F130)', () => {
    const risk = readFileSync(join(root, 'app/(root)/risk/page.tsx'), 'utf8');
    assert.ok(!risk.includes('el motor aún no usa'), 'el motor SÍ usa historia de precios (Inteligencia)');
    // La distinción honesta vive en el diccionario i18n (carril C); la página
    // la referencia por clave. El guard verifica ambos extremos.
    const esRisk = JSON.parse(readFileSync(join(root, 'lib/i18n/messages/es/risk.json'), 'utf8'));
    assert.ok(risk.includes('risk.methodology.noRiskMeasures'), 'la página usa la clave de la distinción');
    assert.ok(esRisk.methodology.noRiskMeasures.includes('esas medidas están en Inteligencia'), 'la distinción honesta: esta página no las calcula');
});
