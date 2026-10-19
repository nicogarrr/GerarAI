/**
 * Cruce Temas <-> Cuellos: el mapeo curado solo puede enlazar ids y nombres
 * que existen de verdad en market_themes.py (cestas) y bottleneck_service.py
 * (temas de escasez), y ambas paginas deben usarlo.
 * Ejecución: node --experimental-strip-types --test scripts/theme-bottleneck-map-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { BOTTLENECK_TO_THEMES, THEME_TO_BOTTLENECK } from '../lib/market/theme-bottleneck-map.ts';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const baskets = readFileSync(join(root, 'data-engine/app/services/market_themes.py'), 'utf8');
const bottlenecks = readFileSync(join(root, 'data-engine/app/services/bottleneck_service.py'), 'utf8');

const basketIds = new Set([...baskets.matchAll(/"id": "([^"]+)"/g)].map((m) => m[1]));
const basketNames = new Map(
    [...baskets.matchAll(/"id": "([^"]+)",\s*\n\s*"name": "([^"]+)"/g)].map((m) => [m[1], m[2]]),
);
const bottleneckThemes = new Set(
    [...bottlenecks.matchAll(/^    "([^"]+)": r"/gm)].map((m) => m[1]),
);

describe('cruce temas <-> cuellos: mapeo coherente con las fuentes reales', () => {
    it('cada clave del mapeo es una cesta real y cada valor un tema de cuello real', () => {
        for (const [id, theme] of Object.entries(THEME_TO_BOTTLENECK)) {
            assert.ok(basketIds.has(id), `cesta desconocida: ${id}`);
            assert.ok(bottleneckThemes.has(theme), `tema de cuello desconocido: ${theme}`);
        }
    });
    it('la dirección inversa usa ids y nombres reales y es consistente', () => {
        for (const [bottleneck, themes] of Object.entries(BOTTLENECK_TO_THEMES)) {
            assert.ok(bottleneckThemes.has(bottleneck), `cuello desconocido: ${bottleneck}`);
            for (const theme of themes) {
                assert.equal(THEME_TO_BOTTLENECK[theme.id], bottleneck, `inversa rota: ${theme.id}`);
                assert.equal(basketNames.get(theme.id), theme.name, `nombre desactualizado: ${theme.id}`);
            }
        }
    });
    it('ambas páginas consumen el mapeo', () => {
        assert.match(
            readFileSync(join(root, 'app/(root)/temas/page.tsx'), 'utf8'),
            /THEME_TO_BOTTLENECK/,
        );
        assert.match(
            readFileSync(join(root, 'app/(root)/cuellos/page.tsx'), 'utf8'),
            /BOTTLENECK_TO_THEMES/,
        );
    });
});
