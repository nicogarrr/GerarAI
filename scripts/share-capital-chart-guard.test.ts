/**
 * Guard de rendimiento móvil: recharts (~120 KB gzip con sus d3) no puede
 * viajar en el bundle inicial de /research/[ticker]/share-capital. La
 * gráfica de evolución se carga diferida (chunk propio) y el esqueleto
 * reserva el alto del contenedor para no mover el layout al llegar.
 *
 * Medida (build local, main 3f9631d8): la ruta cargaba 227,4 KB gzip de JS
 * inicial, 120 KB más que el resto de la app; 102 KB gz eran un solo chunk
 * de recharts. Tras el cambio la ruta queda en ~107 KB gzip.
 *
 * Ejecución: node --experimental-strip-types --test scripts/share-capital-chart-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const panel = readFileSync('components/research/ShareCapitalPanel.tsx', 'utf8');
const chart = readFileSync('components/research/ShareCapitalChart.tsx', 'utf8');

const STATIC_RECHARTS = /^import\s+(?!type)[^;]*?from\s+['"]recharts['"]/m;

describe('share-capital: recharts fuera del bundle inicial', () => {
    it('el panel no importa recharts en estático', () => {
        assert.ok(!STATIC_RECHARTS.test(panel), 'ShareCapitalPanel no debe importar recharts en estático');
    });

    it('la gráfica vive en su propio Client Component cargado con dynamic()', () => {
        assert.match(chart, /^'use client';/m);
        assert.match(chart, STATIC_RECHARTS);
        assert.match(panel, /dynamic\(\(\) => import\('@\/components\/research\/ShareCapitalChart'\)/);
    });

    it('el estado de carga reserva el alto del contenedor (sin salto de layout)', () => {
        assert.match(panel, /loading:\s*\(\)\s*=>/, 'dynamic() debe declarar loading');
        assert.match(panel, /h-full w-full animate-pulse/);
        // El contenedor de la gráfica mantiene su h-64 fijo.
        assert.match(panel, /h-64 min-w-0/);
    });

    it('la gráfica solo se renderiza con serie de más de un punto', () => {
        assert.match(panel, /data\.series\.length > 1 && <Panel/);
        assert.match(panel, /<ShareCapitalChart series=\{data\.series\} \/>/);
    });
});
