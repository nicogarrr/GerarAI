/* eslint-disable @typescript-eslint/no-explicit-any */
/**
 * Guardas del panel /temas: lógica de vista y contrato de la página.
 * Ejecución: node --experimental-strip-types --test scripts/market-themes-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import {
  coverageLabel,
  isHot,
  parseThemeOrder,
  sortThemes,
  themeRank,
  themeTone,
  // @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
} from '../lib/market/themes.ts';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const source = (relativePath: string): string => readFileSync(join(root, relativePath), 'utf8');

type T = {
  id: string; name: string; n_total: number;
  ytd: { pct: number | null; n: number }; m1: { pct: number | null; n: number };
  rank: number | null; rank_1m: number | null; hot: boolean; turn: 'sube' | 'baja' | null; constituents: any[];
};
const theme = (name: string, ytd: number | null, m1: number | null, rank: number | null, rank1m: number | null): T => ({
  id: name.toLowerCase(), name, n_total: 12,
  ytd: { pct: ytd, n: ytd === null ? 5 : 12 }, m1: { pct: m1, n: m1 === null ? 5 : 12 },
  rank, rank_1m: rank1m, hot: false, turn: null, constituents: [],
});

describe('lógica de vista de temas', () => {
  const themes = [
    theme('Beta', 10, 30, 2, 1), theme('Alfa', 50, -5, 1, 3), theme('Sin cobertura', null, null, null, null),
    theme('Gama', -3, 12, 3, 2),
  ];

  it('ordena por YTD y por 1M con los temas sin cobertura al final', () => {
    assert.deepEqual(sortThemes(themes, 'ytd').map((t: T) => t.name), ['Alfa', 'Beta', 'Gama', 'Sin cobertura']);
    assert.deepEqual(sortThemes(themes, '1m').map((t: T) => t.name), ['Beta', 'Gama', 'Alfa', 'Sin cobertura']);
  });

  it('no muta la lista original', () => {
    const copy = JSON.stringify(themes);
    sortThemes(themes, '1m');
    assert.equal(JSON.stringify(themes), copy);
  });

  it('parseThemeOrder: solo "1m" cambia el orden; basura = YTD', () => {
    assert.equal(parseThemeOrder('1m'), '1m');
    assert.equal(parseThemeOrder(['1m', 'ytd']), '1m');
    assert.equal(parseThemeOrder(undefined), 'ytd');
    assert.equal(parseThemeOrder('<script>'), 'ytd');
  });

  it('la posición y "caliente" siguen el orden elegido y exigen cobertura', () => {
    const [alfa, beta, sin] = [themes[1], themes[0], themes[2]];
    assert.equal(themeRank(alfa, 'ytd'), 1);
    assert.equal(themeRank(alfa, '1m'), 3);
    assert.equal(isHot(alfa, '1m'), true);
    assert.equal(isHot(beta, 'ytd'), true);
    assert.equal(isHot(sin, 'ytd'), false);
    assert.equal(isHot(theme('Cuarto', 1, 1, 4, 4), 'ytd'), false);
  });

  it('tono: un 0,0 % no es una ausencia, y null no es ni subida ni bajada', () => {
    assert.equal(themeTone(0), 'up');
    assert.equal(themeTone(-0.1), 'down');
    assert.equal(themeTone(null), 'none');
    assert.equal(themeTone(Number.NaN), 'none');
  });

  it('la cobertura se declara como n/N', () => {
    assert.equal(coverageLabel({ pct: 4, n: 11 }, 12), '11/12 con datos');
  });
});

describe('página /temas', () => {
  const page = source('app/(root)/temas/page.tsx');

  it('usa los formateadores de lib/format (es-ES) y no formatea a mano', () => {
    assert.ok(page.includes("formatPercent(value, { fromRatio: false"));
    assert.ok(!/toFixed\(|toLocaleString\(/.test(page));
  });

  it('sin párrafos explicativos: el único texto corrido es el pie de una línea', () => {
    assert.ok(!/<p[^>]*>[^<{]{60,}/.test(page), 'sin párrafos largos');
    assert.equal((page.match(/<footer/g) ?? []).length, 1);
  });

  it('declara cierre/intradía y método en el pie, sin etiqueta de fuente', () => {
    // El proveedor es una etiqueta de fuente: fuera de la UI (la fuente
    // sigue viajando en la API). Frescura y método se conservan.
    assert.ok(!page.includes('data.source'));
    assert.ok(page.includes('data.method'));
    assert.ok(page.includes("data.intraday ? 'Intradía' : 'Cierre'"));
  });

  it('QA 19: sin as_of el pie lo declara, no pinta «del —»', () => {
    assert.ok(page.includes('Sin fecha de datos disponible'));
    assert.ok(page.includes('data.as_of'));
    assert.ok(!page.includes('del {formatMarketDate(data.as_of)}'));
  });

  it('el backend caído muestra el estado desconectado, no un ranking vacío', () => {
    assert.ok(page.includes('isBackendUnavailableError') && page.includes('<BackendOffline'));
    const action = source('lib/actions/market-themes.actions.ts');
    assert.ok(!/catch\s*[({]/.test(action), 'la acción no traga errores');
  });

  it('es dinámica (dato de mercado) y está en el menú de Descubrir y en robots', () => {
    assert.ok(page.includes("export const dynamic = 'force-dynamic'"));
    // Menú de Descubrir y subnav se derivan del ROUTE_CATALOG (17-oct): la
    // presencia de /temas alli cubre ambos.
    assert.ok(source('lib/constants.ts').includes("{ href: '/temas', labelKey: 'nav.items.temas'"));
    assert.equal(JSON.parse(source('lib/i18n/messages/es/nav.json')).items.temas, 'Temas');
    assert.ok(source('components/layout/SectionNav.tsx').includes('flattenNavItems'));
    assert.ok(source('app/(root)/discover/page.tsx').includes('flattenNavItems'));
    assert.ok(source('app/robots.ts').includes("'/temas'"));
  });
});
