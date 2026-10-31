/**
 * Guard de velas (lightweight-charts v5, TradingView): la librería es
 * ESM-only y NO puede entrar en el bundle de servidor; el montaje es cliente
 * con `dynamic(ssr: false)`, la atribución a TradingView es obligatoria por
 * licencia: logo + enlace en el propio chart y aviso público en /metodologia
 * (fuera del pie de la landing por decisión de producto, 1 nov 2026). Los
 * mapeos de datos son honestos (sin OHLC no hay velas, sin volumen no hay 0
 * fabricado).
 * Ejecución: node --experimental-strip-types --test scripts/charts-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';

// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { summarizeCandles, toCandleRows, toCandlestickData, toVolumeData } from '../lib/market/candles.ts';

const chart = readFileSync('components/research/CompanyTechnicalChart.tsx', 'utf8');
const workspace = readFileSync('components/research/CompanyTechnicalWorkspace.tsx', 'utf8');
const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
const workspaceActions = readFileSync('lib/actions/market-workspace.actions.ts', 'utf8');
const finnhub = readFileSync('lib/actions/finnhub.actions.ts', 'utf8');
const quoteRoute = existsSync('app/api/quote/route.ts') ? readFileSync('app/api/quote/route.ts', 'utf8') : '';  // /api/quote se borro: era codigo muerto con cuatro '|| 0' que inventaban variaciones
const metodologia = readFileSync('app/(public)/metodologia/page.tsx', 'utf8');
const landingEs = readFileSync('lib/i18n/messages/es/landing.json', 'utf8');
const candles = readFileSync('lib/market/candles.ts', 'utf8');

const STATIC_LW_IMPORT = /^import\s+(?!type)[^;]*?from\s+['"]lightweight-charts['"]/m;

describe('charts: montaje solo-cliente (ESM-only, Next 16)', () => {
    it('el workspace monta el chart tecnico con dynamic y ssr:false', () => {
        assert.match(workspace, /dynamic\(\(\) => import\('\.\/CompanyTechnicalChart'\)/);
        assert.match(workspace, /ssr:\s*false/);
    });

    it('el chart es un Client Component que carga la librería por import dinámico', () => {
        assert.match(chart, /^'use client';/m);
        assert.match(chart, /await import\('lightweight-charts'\)/);
    });

    it('ningún fichero de servidor importa la librería de forma estática', () => {
        for (const [name, source] of [
            ['page', page],
            ['workspace-actions', workspaceActions],
            ['finnhub', finnhub],
            ['quote-route', quoteRoute],
        ] as const) {
            assert.ok(!STATIC_LW_IMPORT.test(source), `${name} no debe importar lightweight-charts en estático`);
        }
        assert.ok(!STATIC_LW_IMPORT.test(chart), 'el chart tampoco usa import estático en runtime (solo import type)');
    });
});

describe('charts: atribución obligatoria a TradingView', () => {
    it('el pie del chart nombra a TradingView y enlaza a tradingview.com', () => {
        assert.match(chart, /TradingView/);
        // La URL vive en la constante TRADINGVIEW_URL (lib/market/candles.ts,
        // fuente única); el chart la usa como href del enlace visible.
        assert.match(chart, /href=\{TRADINGVIEW_URL\}/);
        assert.match(candles, /TRADINGVIEW_URL = 'https:\/\/www\.tradingview\.com\/'/);
        assert.match(chart, /attributionLogo:\s*true/);
    });

    it('la atribución pública vive en /metodologia: aviso de la NOTICE y enlace', () => {
        // Decisión de producto (1 nov 2026): fuera del pie de la landing; en la
        // página pública donde menos se ve. La doc de la licencia pide el aviso
        // de la NOTICE y el enlace a tradingview.com en una página pública.
        assert.match(metodologia, /landing\.metodologia\.chartsAttribution/);
        assert.match(metodologia, /https:\/\/www\.tradingview\.com\//);
        assert.match(landingEs, /TradingView Lightweight Charts™ · Copyright \(c\) 2025 TradingView, Inc\./);
    });
});

describe('charts: mapeos honestos de velas y volumen', () => {
    const ohlc = [
        { date: '2026-09-28', open: 10, high: 12, low: 9, close: 11, volume: 1000 },
        { date: '2026-09-29', open: 11, high: 13, low: 10, close: 12, volume: null },
        { date: '2026-09-30', open: 12, high: 12.5, low: 11, close: 11.5, volume: 2000 },
    ];

    it('solo las sesiones con OHLC completo llegan a las velas, ordenadas y sin duplicados', () => {
        const rows = toCandleRows([
            { date: '2026-09-30', open: 12, high: 12.5, low: 11, close: 11.5, volume: 2000 },
            { date: '2026-09-28', open: 10, high: 12, low: 9, close: 11, volume: 1000 },
            // Solo cierre: no es una vela (nunca O=H=L=C inventado).
            { date: '2026-09-29', close: 12, volume: 500 },
            // Duplicado: la última occurrence gana.
            { date: '2026-09-28', open: 10, high: 12, low: 9, close: 11, volume: 1000 },
            // Fecha o número roto: fuera.
            { date: 'no-fecha', open: 1, high: 2, low: 0.5, close: 1.5, volume: 10 },
            { date: '2026-09-27', open: 1, high: 2, low: 0.5, close: Number.NaN, volume: 10 },
        ]);
        assert.deepEqual(
            rows.map((row) => row.time),
            ['2026-09-28', '2026-09-30'],
        );
        assert.deepEqual(toCandlestickData(rows)[0], {
            time: '2026-09-28',
            open: 10,
            high: 12,
            low: 9,
            close: 11,
        });
    });

    it('el volumen desconocido se omite y nunca se fabrica un 0', () => {
        const rows = toCandleRows(ohlc);
        const volumes = toVolumeData(rows, { up: 'u', down: 'd' });
        assert.equal(volumes.length, 2);
        assert.ok(!volumes.some((bar) => bar.time === '2026-09-29'), 'la sesión sin volumen no entra en el histograma');
        assert.deepEqual(volumes[0], { time: '2026-09-28', value: 1000, color: 'u' });
        assert.deepEqual(volumes[1], { time: '2026-09-30', value: 2000, color: 'd' });
    });

    it('el resumen para el aria-label calcula variación y rango sin aparentar', () => {
        const summary = summarizeCandles(toCandleRows(ohlc));
        assert.ok(summary);
        assert.equal(summary.count, 3);
        assert.equal(summary.lastClose, 11.5);
        assert.equal(summary.change, 0.5);
        assert.equal(summary.rangeHigh, 13);
        assert.equal(summary.rangeLow, 9);
        assert.equal(summary.knownVolumeSessions, 2);
        assert.equal(summarizeCandles([]), null);
    });
});
