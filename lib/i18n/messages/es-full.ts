/**
 * Castellano COMPLETO y estático: lo usan el servidor, los tests y los scripts
 * de Node (condición `default` de `#i18n-es` en package.json). El navegador
 * resuelve `es.browser.ts`, que solo lleva las áreas básicas y descarga el
 * resto por área según la ruta.
 */
import alerts__es from './es/alerts.json' with { type: 'json' };
import auth__es from './es/auth.json' with { type: 'json' };
import bottlenecks__es from './es/bottlenecks.json' with { type: 'json' };
import brain__es from './es/brain.json' with { type: 'json' };
import calendar__es from './es/calendar.json' with { type: 'json' };
import chat__es from './es/chat.json' with { type: 'json' };
import common__es from './es/common.json' with { type: 'json' };
import corporateActions__es from './es/corporateActions.json' with { type: 'json' };
import data__es from './es/data.json' with { type: 'json' };
import discover__es from './es/discover.json' with { type: 'json' };
import emails__es from './es/emails.json' with { type: 'json' };
import errors__es from './es/errors.json' with { type: 'json' };
import export__es from './es/export.json' with { type: 'json' };
import help__es from './es/help.json' with { type: 'json' };
import home__es from './es/home.json' with { type: 'json' };
import insider__es from './es/insider.json' with { type: 'json' };
import investors__es from './es/investors.json' with { type: 'json' };
import knowledge__es from './es/knowledge.json' with { type: 'json' };
import knowledgeGraph__es from './es/knowledgeGraph.json' with { type: 'json' };
import labels__es from './es/labels.json' with { type: 'json' };
import landing__es from './es/landing.json' with { type: 'json' };
import markets__es from './es/markets.json' with { type: 'json' };
import movers__es from './es/movers.json' with { type: 'json' };
import nav__es from './es/nav.json' with { type: 'json' };
import ownership__es from './es/ownership.json' with { type: 'json' };
import paperTrading__es from './es/paperTrading.json' with { type: 'json' };
import plan__es from './es/plan.json' with { type: 'json' };
import portfolio__es from './es/portfolio.json' with { type: 'json' };
import propicks__es from './es/propicks.json' with { type: 'json' };
import research__es from './es/research.json' with { type: 'json' };
import researchShared__es from './es/researchShared.json' with { type: 'json' };
import risk__es from './es/risk.json' with { type: 'json' };
import screener__es from './es/screener.json' with { type: 'json' };
import search__es from './es/search.json' with { type: 'json' };
import security__es from './es/security.json' with { type: 'json' };
import settings__es from './es/settings.json' with { type: 'json' };
import shell__es from './es/shell.json' with { type: 'json' };
import shorts__es from './es/shorts.json' with { type: 'json' };
import signals__es from './es/signals.json' with { type: 'json' };
import stocks__es from './es/stocks.json' with { type: 'json' };
import taxes__es from './es/taxes.json' with { type: 'json' };
import themes__es from './es/themes.json' with { type: 'json' };
import ui__es from './es/ui.json' with { type: 'json' };
import watchlist__es from './es/watchlist.json' with { type: 'json' };
import workProducts__es from './es/workProducts.json' with { type: 'json' };

export const bundledSpanish = {
    alerts: alerts__es,
    auth: auth__es,
    bottlenecks: bottlenecks__es,
    brain: brain__es,
    calendar: calendar__es,
    chat: chat__es,
    common: common__es,
    corporateActions: corporateActions__es,
    data: data__es,
    discover: discover__es,
    emails: emails__es,
    errors: errors__es,
    export: export__es,
    help: help__es,
    home: home__es,
    insider: insider__es,
    investors: investors__es,
    knowledge: knowledge__es,
    knowledgeGraph: knowledgeGraph__es,
    labels: labels__es,
    landing: landing__es,
    markets: markets__es,
    movers: movers__es,
    nav: nav__es,
    ownership: ownership__es,
    paperTrading: paperTrading__es,
    plan: plan__es,
    portfolio: portfolio__es,
    propicks: propicks__es,
    research: research__es,
    researchShared: researchShared__es,
    risk: risk__es,
    screener: screener__es,
    search: search__es,
    security: security__es,
    settings: settings__es,
    shell: shell__es,
    shorts: shorts__es,
    signals: signals__es,
    stocks: stocks__es,
    taxes: taxes__es,
    themes: themes__es,
    ui: ui__es,
    watchlist: watchlist__es,
    workProducts: workProducts__es,
};

/** Diccionario castellano completo: referencia de claves y tipos. */
export type SpanishMessages = typeof bundledSpanish;

export type SpanishArea = keyof SpanishMessages;

export function loadSpanishArea(area: SpanishArea): Promise<SpanishMessages[SpanishArea]> {
  return Promise.resolve(bundledSpanish[area]);
}
