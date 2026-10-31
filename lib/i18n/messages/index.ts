/**
 * Registro central de diccionarios i18n. PROPIEDAD EXCLUSIVA del carril de
 * infraestructura i18n: nadie más añade ni quita áreas aquí (pide el área al
 * piloto si la necesitas).
 *
 * Un archivo por área y locale: messages/<locale>/<area>.json. El nombre del
 * archivo ES el prefijo de clave: taxes.json -> t('taxes.*'). El contenido de
 * cada archivo no repite el prefijo (settings.json guarda "title", no
 * "settings.title").
 *
 * messages.es es la referencia completa: de ella se deriva TranslationKey y
 * contra ella se verifica la paridad de en en scripts/check-i18n.mjs. Un área
 * en vacía ({}) es un área pendiente de traducir por su carril; t() cae al
 * texto es mientras tanto (ver translate.ts).
 */
import type { Locale } from '../locale.ts';

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
import risk__es from './es/risk.json' with { type: 'json' };
import screener__es from './es/screener.json' with { type: 'json' };
import search__es from './es/search.json' with { type: 'json' };
import security__es from './es/security.json' with { type: 'json' };
import settings__es from './es/settings.json' with { type: 'json' };
import shell__es from './es/shell.json' with { type: 'json' };
import signals__es from './es/signals.json' with { type: 'json' };
import stocks__es from './es/stocks.json' with { type: 'json' };
import taxes__es from './es/taxes.json' with { type: 'json' };
import themes__es from './es/themes.json' with { type: 'json' };
import ui__es from './es/ui.json' with { type: 'json' };
import watchlist__es from './es/watchlist.json' with { type: 'json' };
import workProducts__es from './es/workProducts.json' with { type: 'json' };

import alerts__en from './en/alerts.json' with { type: 'json' };
import auth__en from './en/auth.json' with { type: 'json' };
import bottlenecks__en from './en/bottlenecks.json' with { type: 'json' };
import brain__en from './en/brain.json' with { type: 'json' };
import calendar__en from './en/calendar.json' with { type: 'json' };
import chat__en from './en/chat.json' with { type: 'json' };
import common__en from './en/common.json' with { type: 'json' };
import corporateActions__en from './en/corporateActions.json' with { type: 'json' };
import data__en from './en/data.json' with { type: 'json' };
import discover__en from './en/discover.json' with { type: 'json' };
import emails__en from './en/emails.json' with { type: 'json' };
import errors__en from './en/errors.json' with { type: 'json' };
import export__en from './en/export.json' with { type: 'json' };
import help__en from './en/help.json' with { type: 'json' };
import home__en from './en/home.json' with { type: 'json' };
import insider__en from './en/insider.json' with { type: 'json' };
import investors__en from './en/investors.json' with { type: 'json' };
import knowledge__en from './en/knowledge.json' with { type: 'json' };
import knowledgeGraph__en from './en/knowledgeGraph.json' with { type: 'json' };
import landing__en from './en/landing.json' with { type: 'json' };
import markets__en from './en/markets.json' with { type: 'json' };
import movers__en from './en/movers.json' with { type: 'json' };
import nav__en from './en/nav.json' with { type: 'json' };
import ownership__en from './en/ownership.json' with { type: 'json' };
import paperTrading__en from './en/paperTrading.json' with { type: 'json' };
import plan__en from './en/plan.json' with { type: 'json' };
import portfolio__en from './en/portfolio.json' with { type: 'json' };
import propicks__en from './en/propicks.json' with { type: 'json' };
import research__en from './en/research.json' with { type: 'json' };
import risk__en from './en/risk.json' with { type: 'json' };
import screener__en from './en/screener.json' with { type: 'json' };
import search__en from './en/search.json' with { type: 'json' };
import security__en from './en/security.json' with { type: 'json' };
import settings__en from './en/settings.json' with { type: 'json' };
import shell__en from './en/shell.json' with { type: 'json' };
import signals__en from './en/signals.json' with { type: 'json' };
import stocks__en from './en/stocks.json' with { type: 'json' };
import taxes__en from './en/taxes.json' with { type: 'json' };
import themes__en from './en/themes.json' with { type: 'json' };
import ui__en from './en/ui.json' with { type: 'json' };
import watchlist__en from './en/watchlist.json' with { type: 'json' };
import workProducts__en from './en/workProducts.json' with { type: 'json' };

/** Áreas registradas (el orden es el del contrato; no lo uses para pintar). */
export const I18N_AREAS = ['alerts', 'auth', 'bottlenecks', 'brain', 'calendar', 'chat', 'common', 'corporateActions', 'data', 'discover', 'emails', 'errors', 'export', 'help', 'home', 'insider', 'investors', 'knowledge', 'knowledgeGraph', 'landing', 'markets', 'movers', 'nav', 'ownership', 'paperTrading', 'plan', 'portfolio', 'propicks', 'research', 'risk', 'screener', 'search', 'security', 'settings', 'shell', 'signals', 'stocks', 'taxes', 'themes', 'ui', 'watchlist', 'workProducts'] as const;

const es = {
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
    risk: risk__es,
    screener: screener__es,
    search: search__es,
    security: security__es,
    settings: settings__es,
    shell: shell__es,
    signals: signals__es,
    stocks: stocks__es,
    taxes: taxes__es,
    themes: themes__es,
    ui: ui__es,
    watchlist: watchlist__es,
    workProducts: workProducts__es,
};

/** Diccionario del locale por defecto y referencia de claves. */
export type Messages = typeof es;

// Las áreas en pendientes son {} hasta que su carril las traduzca; el guard
// check:i18n exige paridad exacta de claves por área en cuanto tiene contenido.
const en = {
    alerts: alerts__en,
    auth: auth__en,
    bottlenecks: bottlenecks__en,
    brain: brain__en,
    calendar: calendar__en,
    chat: chat__en,
    common: common__en,
    corporateActions: corporateActions__en,
    data: data__en,
    discover: discover__en,
    emails: emails__en,
    errors: errors__en,
    export: export__en,
    help: help__en,
    home: home__en,
    insider: insider__en,
    investors: investors__en,
    knowledge: knowledge__en,
    knowledgeGraph: knowledgeGraph__en,
    landing: landing__en,
    markets: markets__en,
    movers: movers__en,
    nav: nav__en,
    ownership: ownership__en,
    paperTrading: paperTrading__en,
    plan: plan__en,
    portfolio: portfolio__en,
    propicks: propicks__en,
    research: research__en,
    risk: risk__en,
    screener: screener__en,
    search: search__en,
    security: security__en,
    settings: settings__en,
    shell: shell__en,
    signals: signals__en,
    stocks: stocks__en,
    taxes: taxes__en,
    themes: themes__en,
    ui: ui__en,
    watchlist: watchlist__en,
    workProducts: workProducts__en,
} as Messages;

export const messages: Record<Locale, Messages> = { es, en };

export function getMessages(locale: Locale): Messages {
  return messages[locale] ?? messages.es;
}

// Re-export del tipo clave: los consumidores lo importan de
// '@/lib/i18n/messages' (lib/constants.ts, lib/nav/build-crumbs.ts).
export type { TranslationKey, TranslationVars } from '../t.ts';
