/**
 * Contexto de página explícito para el cerebro global (pastilla "Viendo X").
 *
 * El ticker viaja como TEXTO: la Company se resuelve en el backend dentro
 * del catálogo global; el contenido privado posterior se aísla por tenant.
 * El cliente nunca manda IDs de base de datos.
 *
 * Las etiquetas visibles viven en los diccionarios (brain.panel.pageSections.*),
 * patrón labels.ts: aquí queda la clave estable y el texto se resuelve por
 * locale. Antes el literal español viajaba hardcodeado y la pastilla se
 * pintaba en castellano incluso con English activado ("Viewing Inicio").
 */
import esBrain from '../i18n/messages/es/brain.json' with { type: 'json' };
import enBrain from '../i18n/messages/en/brain.json' with { type: 'json' };

export type BrainPageContext = {
    path: string;
    label: string | null;
    ticker: string | null;
};

type BrainSectionKey = keyof typeof esBrain.panel.pageSections;

const SECTION_LABELS: Array<[RegExp, BrainSectionKey]> = [
    [/^\/inicio/, 'inicio'],
    [/^\/portfolio/, 'portfolio'],
    [/^\/watchlist/, 'watchlist'],
    [/^\/knowledge/, 'knowledge'],
    [/^\/inversores/, 'inversores'],
    [/^\/temas/, 'temas'],
    [/^\/propicks/, 'propicks'],
    [/^\/calendar/, 'calendar'],
    [/^\/macro-calendar/, 'macroCalendar'],
    [/^\/screener/, 'screener'],
    [/^\/discover/, 'discover'],
    [/^\/cuellos/, 'cuellos'],
    [/^\/alerts/, 'alerts'],
    [/^\/plan/, 'plan'],
    [/^\/risk/, 'risk'],
    [/^\/taxes/, 'taxes'],
    [/^\/security/, 'security'],
    [/^\/research/, 'research'],
    [/^\/settings/, 'settings'],
];

/** Rutas propias bajo /research: la ruta estática gana a [ticker] en el
 * router, así que NUNCA son la ficha de una empresa. Sin esta lista el
 * cerebro rotulaba /research/news como la empresa "NEWS" y pedía su ficha
 * al catálogo (auditoría v1.0, 2026-10-27). */
const RESEARCH_RESERVED_ROUTES: Array<[RegExp, BrainSectionKey]> = [
    [/^\/research\/news(?:\/|$)/i, 'researchNews'],
    [/^\/research\/sources(?:\/|$)/i, 'researchSources'],
    [/^\/research\/assistant(?:\/|$)/i, 'researchAssistant'],
];

const SECTION_TEXT: Record<'es' | 'en', Record<BrainSectionKey, string>> = {
    es: esBrain.panel.pageSections,
    en: enBrain.panel.pageSections,
};

// Uso por literal para el guard de i18n (claves consumidas por objeto).
export const BRAIN_PAGE_KEY_LITERALS = [
    'brain.panel.pageSections.inicio',
    'brain.panel.pageSections.portfolio',
    'brain.panel.pageSections.watchlist',
    'brain.panel.pageSections.knowledge',
    'brain.panel.pageSections.inversores',
    'brain.panel.pageSections.temas',
    'brain.panel.pageSections.propicks',
    'brain.panel.pageSections.calendar',
    'brain.panel.pageSections.macroCalendar',
    'brain.panel.pageSections.screener',
    'brain.panel.pageSections.discover',
    'brain.panel.pageSections.cuellos',
    'brain.panel.pageSections.alerts',
    'brain.panel.pageSections.plan',
    'brain.panel.pageSections.risk',
    'brain.panel.pageSections.taxes',
    'brain.panel.pageSections.security',
    'brain.panel.pageSections.research',
    'brain.panel.pageSections.settings',
    'brain.panel.pageSections.researchNews',
    'brain.panel.pageSections.researchSources',
    'brain.panel.pageSections.researchAssistant',
];

const TICKER_RE = /^[A-Z0-9.\-]{1,20}$/;

/** Deriva el contexto de la ruta actual; null si la página no es identificable. */
export function brainPageContext(pathname: string | null, locale: 'es' | 'en' = 'es'): BrainPageContext | null {
    if (!pathname) return null;
    const labels = SECTION_TEXT[locale];
    for (const [pattern, key] of RESEARCH_RESERVED_ROUTES) {
        if (pattern.test(pathname)) {
            return { path: pathname, label: labels[key], ticker: null };
        }
    }
    const research = pathname.match(/^\/research\/([A-Za-z0-9.\-]{1,20})(?:\/|$)/);
    if (research) {
        const ticker = research[1].toUpperCase();
        if (TICKER_RE.test(ticker)) {
            return { path: pathname, label: ticker, ticker };
        }
    }
    const stocks = pathname.match(/^\/stocks\/([A-Za-z0-9.\-]{1,20})(?:\/|$)/);
    if (stocks) {
        const ticker = stocks[1].toUpperCase();
        if (TICKER_RE.test(ticker)) {
            return { path: pathname, label: ticker, ticker };
        }
    }
    for (const [pattern, key] of SECTION_LABELS) {
        if (pattern.test(pathname)) {
            return { path: pathname, label: labels[key], ticker: null };
        }
    }
    return null;
}
