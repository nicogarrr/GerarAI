/**
 * Castellano en el NAVEGADOR (condición `browser` de `#i18n-es`).
 *
 * Antes iban las 42 áreas (~130 KB gzip) en el chunk común de todas las
 * páginas. Ahora el chunk común lleva solo las áreas del shell (CORE_AREAS de
 * route-areas.generated.ts) y cada área restante es un chunk aparte, con hash
 * y cacheable, que se pide según la ruta (LocaleProvider). Las áreas de la
 * ruta con la que arranca la página se cargan al evaluar este módulo, antes de
 * hidratar.
 */
import type { SpanishArea, SpanishMessages } from './es-full.ts';
import { spanishAreasForPath } from '../route-areas';

import common__es from './es/common.json' with { type: 'json' };
import errors__es from './es/errors.json' with { type: 'json' };
import nav__es from './es/nav.json' with { type: 'json' };
import search__es from './es/search.json' with { type: 'json' };
import shell__es from './es/shell.json' with { type: 'json' };
import ui__es from './es/ui.json' with { type: 'json' };

export type { SpanishArea, SpanishMessages };

/** Áreas que van en el chunk común (deben coincidir con CORE_AREAS). */
export const bundledSpanish: Partial<SpanishMessages> = {
    common: common__es,
    errors: errors__es,
    nav: nav__es,
    search: search__es,
    shell: shell__es,
    ui: ui__es,
};

type Loader = () => Promise<{ default: unknown }>;

// Un import() literal por área: el bundler hace un chunk por área.
const LOADERS: Partial<Record<SpanishArea, Loader>> = {
    alerts: () => import('./es/alerts.json'),
    auth: () => import('./es/auth.json'),
    bottlenecks: () => import('./es/bottlenecks.json'),
    brain: () => import('./es/brain.json'),
    calendar: () => import('./es/calendar.json'),
    chat: () => import('./es/chat.json'),
    corporateActions: () => import('./es/corporateActions.json'),
    data: () => import('./es/data.json'),
    discover: () => import('./es/discover.json'),
    emails: () => import('./es/emails.json'),
    export: () => import('./es/export.json'),
    help: () => import('./es/help.json'),
    home: () => import('./es/home.json'),
    insider: () => import('./es/insider.json'),
    investors: () => import('./es/investors.json'),
    knowledge: () => import('./es/knowledge.json'),
    knowledgeGraph: () => import('./es/knowledgeGraph.json'),
    landing: () => import('./es/landing.json'),
    markets: () => import('./es/markets.json'),
    movers: () => import('./es/movers.json'),
    ownership: () => import('./es/ownership.json'),
    paperTrading: () => import('./es/paperTrading.json'),
    plan: () => import('./es/plan.json'),
    portfolio: () => import('./es/portfolio.json'),
    propicks: () => import('./es/propicks.json'),
    research: () => import('./es/research.json'),
    risk: () => import('./es/risk.json'),
    screener: () => import('./es/screener.json'),
    security: () => import('./es/security.json'),
    settings: () => import('./es/settings.json'),
    signals: () => import('./es/signals.json'),
    stocks: () => import('./es/stocks.json'),
    taxes: () => import('./es/taxes.json'),
    themes: () => import('./es/themes.json'),
    watchlist: () => import('./es/watchlist.json'),
    workProducts: () => import('./es/workProducts.json'),
};

const pending = new Map<SpanishArea, Promise<SpanishMessages[SpanishArea]>>();

export function loadSpanishArea(area: SpanishArea): Promise<SpanishMessages[SpanishArea]> {
  const bundled = bundledSpanish[area];
  if (bundled) return Promise.resolve(bundled);
  let promise = pending.get(area);
  if (!promise) {
    const loader = LOADERS[area];
    if (!loader) return Promise.reject(new Error(`[i18n] Área desconocida: ${area}`));
    promise = loader().then((module) => module.default as SpanishMessages[SpanishArea]);
    // Un fallo de red no deja la promesa rota en caché: el siguiente intento reintenta.
    promise.catch(() => pending.delete(area));
    pending.set(area, promise);
  }
  return promise;
}

// Las áreas de la ruta con la que arranca la página se esperan aquí, con un
// await de nivel superior: la app no se evalúa (ni hidrata) hasta tenerlas, así
// que la hidratación nunca se suspende por el diccionario. Si una descarga
// falla, se sigue sin ella (t() la reintenta al pedir una clave suya).
if (typeof location !== 'undefined') {
  await Promise.all(spanishAreasForPath(location.pathname).map(async (area) => {
    try {
      (bundledSpanish as Record<string, unknown>)[area] = await loadSpanishArea(area as SpanishArea);
    } catch {
      /* red caída: se reintenta al usarla */
    }
  }));
}
