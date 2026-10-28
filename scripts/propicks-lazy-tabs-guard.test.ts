/**
 * Guard de rendimiento: en /propicks solo la pestaña inicial («Selección IA»)
 * viaja en el bundle inicial. Las vistas del resto de pestañas (Joyas,
 * Deep value, Estrategia, Backtesting, Paper trading, Radar) se montan solo
 * al abrirlas, así que su JS debe cargar con next/dynamic: si vuelven a
 * importarse en estático, ~28 KB gz regresan al primer pintado móvil.
 *
 * Ejecución: node --experimental-strip-types --test scripts/propicks-lazy-tabs-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const tabs = readFileSync('components/proPicks/ProPicksTabs.tsx', 'utf8');

const LAZY_VIEWS = [
    'RadarGlobalView',
    'GemsView',
    'DeepValueView',
    'PaperTradingView',
    'MonthlyRebalanceView',
    'StrategyFactsheet',
    'TrackRecordView',
    'StrategySelector',
    'WalkForwardResults',
    'DcaBacktestPanel',
];

describe('propicks: vistas de pestañas no iniciales diferidas', () => {
    it('ninguna vista de pestaña se importa en estático', () => {
        for (const view of LAZY_VIEWS) {
            assert.ok(
                !new RegExp(`import ${view} from `).test(tabs),
                `${view} no debe importarse en estático`,
            );
            assert.match(tabs, new RegExp(`const ${view} = dynamic\\(\\(\\) => import\\('\\./${view}'\\)`), `${view} debe cargar con next/dynamic`);
        }
    });

    it('la pestaña inicial (Selección IA) sigue eager y montada siempre', () => {
        assert.match(tabs, /import EnhancedProPicksContent from '\.\/EnhancedProPicksContent';/);
        assert.ok(!/dynamic\(\(\) => import\('\.\/EnhancedProPicksContent'\)/.test(tabs));
        assert.match(tabs, /<TabsContent value="picks" forceMount/);
    });

    it('cada vista diferida muestra un fallback accesible mientras carga', () => {
        assert.match(tabs, /loading: TabFallback/);
        assert.match(tabs, /aria-busy="true"/);
        assert.match(tabs, /Cargando vista…/);
    });
});
