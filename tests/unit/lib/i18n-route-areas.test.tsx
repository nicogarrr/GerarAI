import { readFileSync } from 'node:fs';
import path from 'node:path';
import { Suspense } from 'react';
import { act, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CORE_AREAS as SCRIPT_CORE, computeRouteAreas, listAreas, renderGenerated } from '../../../scripts/i18n-route-areas.mjs';
import { CORE_AREAS, NOT_FOUND_AREAS, ROUTE_AREAS } from '@/lib/i18n/route-areas.generated';
import { routePatternRegex, spanishAreasForPath } from '@/lib/i18n/route-areas';

const root = path.resolve(__dirname, '../../..');

describe('castellano por área según la ruta: el mapa cubre cada página', () => {
  const computed = computeRouteAreas() as { routes: Record<string, string[]>; notFound: string[]; unresolved: string[] };

  it('cada clave que usa una ruta (página, layouts, client components, import() dinámicos) es de un área que esa ruta carga', () => {
    const missing: string[] = [];
    for (const [route, areas] of Object.entries(computed.routes)) {
      const loaded = new Set([...(ROUTE_AREAS[route] ?? []), ...CORE_AREAS]);
      for (const area of areas) if (!loaded.has(area)) missing.push(`${route}: ${area}`);
    }
    for (const area of computed.notFound) if (!NOT_FOUND_AREAS.includes(area) && !(CORE_AREAS as readonly string[]).includes(area)) missing.push(`404: ${area}`);
    // Si falla: `node scripts/i18n-route-areas.mjs` y commitear route-areas.generated.ts.
    expect(missing).toEqual([]);
    expect(Object.keys(ROUTE_AREAS).sort()).toEqual(Object.keys(computed.routes).sort());
  });

  it('el análisis resuelve todos los imports del grafo (si no, podría saltarse claves)', () => {
    expect(computed.unresolved).toEqual([]);
  });

  it('el fichero generado es exactamente lo que escribe el script', () => {
    const onDisk = readFileSync(path.join(root, 'lib/i18n/route-areas.generated.ts'), 'utf8');
    expect(onDisk).toBe(renderGenerated(computed));
  });

  it('el navegador lleva estáticas solo las áreas básicas y un import() por cada una de las demás', () => {
    expect([...CORE_AREAS]).toEqual(SCRIPT_CORE);
    const pkg = JSON.parse(readFileSync(path.join(root, 'package.json'), 'utf8'));
    expect(pkg.imports['#i18n-es']).toEqual({
      browser: './lib/i18n/messages/es.browser.ts',
      default: './lib/i18n/messages/es-full.ts',
    });
    expect(pkg.scripts.prebuild).toContain('scripts/i18n-route-areas.mjs');
    const browser = readFileSync(path.join(root, 'lib/i18n/messages/es.browser.ts'), 'utf8');
    const staticAreas = [...browser.matchAll(/^import \w+ from '\.\/es\/(\w+)\.json'/gm)].map((m) => m[1]).sort();
    const lazyAreas = [...browser.matchAll(/import\('\.\/es\/(\w+)\.json'\)/g)].map((m) => m[1]).sort();
    expect(staticAreas).toEqual([...CORE_AREAS].sort());
    expect([...staticAreas, ...lazyAreas].sort()).toEqual(listAreas());
    const registry = readFileSync(path.join(root, 'lib/i18n/messages/index.ts'), 'utf8');
    expect(registry).not.toMatch(/from\s+['"]\.\/es\/\w+\.json['"]/);
  });

  it('una página como /inicio no necesita las áreas de otras secciones', () => {
    const inicio = ROUTE_AREAS['/inicio'];
    expect(inicio).toContain('home');
    expect(inicio).toContain('portfolio');
    // Las claves de research que usa /inicio viven en researchShared: research.json (27 KB gzip) no se descarga.
    expect(inicio).toContain('researchShared');
    expect(inicio).not.toContain('research');
    expect(inicio).not.toContain('taxes');
    expect(inicio).not.toContain('landing');
    expect(ROUTE_AREAS['/']).toContain('landing');
  });
});

describe('spanishAreasForPath', () => {
  it('casa segmentos dinámicos, quita la barra final y la query', () => {
    expect(routePatternRegex('/research/[ticker]').test('/research/AAPL')).toBe(true);
    expect(routePatternRegex('/research/[ticker]').test('/research/AAPL/tesis')).toBe(false);
    expect(routePatternRegex('/docs/[...slug]').test('/docs/a/b')).toBe(true);
    expect(routePatternRegex('/docs/[[...slug]]').test('/docs')).toBe(true);
    expect(spanishAreasForPath('/research/AAPL/')).toEqual([...ROUTE_AREAS['/research/[ticker]']].sort());
    expect(spanishAreasForPath('/inicio?x=1')).toEqual([...ROUTE_AREAS['/inicio']].sort());
  });

  it('si casa con varios patrones carga la unión; si no casa con ninguno, lo del 404', () => {
    const news = spanishAreasForPath('/research/news');
    for (const area of [...ROUTE_AREAS['/research/news'], ...ROUTE_AREAS['/research/[ticker]']]) expect(news).toContain(area);
    expect(spanishAreasForPath('/no-existe/en/la/app')).toEqual([...NOT_FOUND_AREAS].sort());
    expect(spanishAreasForPath(null)).toEqual([...ROUTE_AREAS['/']].sort());
  });
});

describe('LocaleProvider en producción (navegador): carga por área', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
    vi.doUnmock('#i18n-es');
    vi.doUnmock('next/navigation');
    vi.doUnmock('#i18n-en-compact');
  });

  async function setup(pathname: string) {
    vi.resetModules();
    vi.stubEnv('NODE_ENV', 'production');
    const loads: string[] = [];
    vi.doMock('next/navigation', () => ({ usePathname: () => pathname }));
    // Como en el navegador: sin inglés estático.
    vi.doMock('#i18n-en-compact', () => ({
      bundledCompactEnglish: null,
      loadCompactEnglish: async () => (await import('@/lib/i18n/messages/en.compact.json')).default,
    }));
    vi.doMock('#i18n-es', async () => {
      const actual = await vi.importActual<typeof import('@/lib/i18n/messages/es.browser')>('@/lib/i18n/messages/es.browser');
      return {
        ...actual,
        loadSpanishArea: (area: Parameters<typeof actual.loadSpanishArea>[0]) => {
          loads.push(area);
          return actual.loadSpanishArea(area);
        },
      };
    });
    const client = await import('@/lib/i18n/client');
    const registry = await import('@/lib/i18n/messages');
    return { ...client, ...registry, loads };
  }

  it('en /inicio espera a sus áreas antes de pintar y no pide las de otras secciones', async () => {
    const { LocaleProvider, useT, hasSpanishAreas, loads } = await setup('/inicio');
    expect(hasSpanishAreas(['home'])).toBe(false);
    expect(hasSpanishAreas(['common'])).toBe(true);
    function Probe() {
      const t = useT();
      return <span>{t('home.metadata.title')}</span>;
    }
    await act(async () => {
      render(<Suspense fallback={<span>cargando</span>}><LocaleProvider locale="es"><Probe /></LocaleProvider></Suspense>);
    });
    expect(await screen.findByText('GerarAI · Research OS de inversión')).toBeInTheDocument();
    expect(loads).toContain('home');
    expect(loads).not.toContain('taxes');
    expect(hasSpanishAreas(['taxes'])).toBe(false);
  });

  it('red de seguridad: una clave de un área que la ruta no cargó se descarga y se vuelve a pintar', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const { LocaleProvider, useT } = await setup('/calendar');
    function Probe() {
      const t = useT();
      return <span data-testid="probe">{t('taxes.year')}</span>;
    }
    await act(async () => {
      render(<Suspense fallback={<span>cargando</span>}><LocaleProvider locale="es"><Probe /></LocaleProvider></Suspense>);
    });
    expect(await screen.findByText('Ejercicio')).toBeInTheDocument();
    warn.mockRestore();
  });

  it('el inglés se expande sobre el castellano entero: primero se cargan todas las áreas', async () => {
    const { loadSpanishAreas, registerCompactEnglish, hasSpanishAreas, hasEnglishMessages } = await setup('/calendar');
    const { translateMessage } = await import('@/lib/i18n/translate');
    const compact = (await import('@/lib/i18n/messages/en.compact.json')).default as Parameters<typeof registerCompactEnglish>[0];
    expect(() => registerCompactEnglish(compact)).toThrow(/castellano completo/);
    await loadSpanishAreas(listAreas());
    expect(hasSpanishAreas(listAreas())).toBe(true);
    registerCompactEnglish(compact);
    expect(hasEnglishMessages()).toBe(true);
    expect(translateMessage('en', 'common.actions.save')).toBe('Save');
    expect(translateMessage('en', 'taxes.year')).not.toBe('');
  });
});
