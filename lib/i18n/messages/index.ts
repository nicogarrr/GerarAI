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

// El inglés compacto llega por `#i18n-en-compact`: en el servidor (y en
// tests/scripts) es el JSON estático; en el navegador es un módulo vacío y el
// diccionario se descarga aparte, solo si el locale es «en» (LocaleProvider).
// Así quien usa la app en castellano no descarga ni expande ~230 KB de inglés.
import { bundledCompactEnglish, type CompactEnglish } from '#i18n-en-compact';

// El castellano llega por `#i18n-es`: en el servidor (y en tests/scripts) es
// el diccionario completo y estático; en el navegador solo trae las áreas del
// shell y el resto se descarga por área según la ruta (LocaleProvider).
import { bundledSpanish, loadSpanishArea, type SpanishMessages } from '#i18n-es';

/** Áreas registradas (el orden es el del contrato; no lo uses para pintar). */
export const I18N_AREAS = ['alerts', 'auth', 'bottlenecks', 'brain', 'calendar', 'chat', 'common', 'corporateActions', 'data', 'discover', 'emails', 'errors', 'export', 'help', 'home', 'insider', 'investors', 'knowledge', 'knowledgeGraph', 'landing', 'markets', 'movers', 'nav', 'ownership', 'paperTrading', 'plan', 'portfolio', 'propicks', 'research', 'researchShared', 'risk', 'screener', 'search', 'security', 'settings', 'shell', 'signals', 'stocks', 'taxes', 'themes', 'ui', 'watchlist', 'workProducts'] as const;

export type I18nArea = (typeof I18N_AREAS)[number];

// En el navegador empieza incompleto y se va rellenando con loadSpanishAreas.
const es = { ...bundledSpanish } as SpanishMessages;

/** ¿Están ya en memoria todas estas áreas del castellano? */
export function hasSpanishAreas(areas: readonly string[]): boolean {
  return areas.every((area) => area in es);
}

/** Carga (si faltan) y registra estas áreas del castellano. */
export function loadSpanishAreas(areas: readonly string[]): Promise<void> {
  const missing = areas.filter((area) => !(area in es)) as (keyof SpanishMessages)[];
  if (missing.length === 0) return Promise.resolve();
  return Promise.all(missing.map(async (area) => {
    const dict = await loadSpanishArea(area);
    (es as Record<string, unknown>)[area] = dict;
  })).then(() => undefined);
}

// Red de seguridad: si una pantalla pide una clave de un área que su ruta no
// cargó (el mapa de scripts/i18n-route-areas.mjs se quedó corto), se descarga
// esa área y se avisa a useT() para volver a pintar. Solo cambia la versión en
// ese caso: la carga normal por ruta no provoca re-renders.
let recoveryVersion = 0;
const recoveryListeners = new Set<() => void>();
const recovering = new Set<string>();

/** ¿Es `area` un área real del castellano que aún no está en memoria? (solo en el navegador) */
export function isSpanishAreaPending(area: string): boolean {
  return (I18N_AREAS as readonly string[]).includes(area) && !(area in es);
}

export function recoverSpanishArea(area: string): void {
  if (!isSpanishAreaPending(area) || recovering.has(area)) return;
  recovering.add(area);
  if (process.env.NODE_ENV !== 'production') {
    console.warn(`[i18n] El área «${area}» no estaba cargada en esta ruta: ejecuta \`node scripts/i18n-route-areas.mjs\`.`);
  }
  loadSpanishAreas([area]).then(() => {
    recovering.delete(area);
    recoveryVersion += 1;
    for (const listener of recoveryListeners) listener();
  }, () => recovering.delete(area));
}

export function subscribeSpanishRecovery(listener: () => void): () => void {
  recoveryListeners.add(listener);
  return () => recoveryListeners.delete(listener);
}

export function getSpanishRecoveryVersion(): number {
  return recoveryVersion;
}

/** Diccionario del locale por defecto y referencia de claves. */
export type Messages = SpanishMessages;

// English shares Spanish's key structure: ship its values only, without a
// second copy of every key. Source JSON remains readable for translators.
function expandEnglish(reference: unknown, values: (string | null)[]): unknown {
  let index = 0;
  function visit(node: unknown): unknown {
    if (typeof node === 'string') {
      if (index >= values.length) throw new Error('Truncated compact English dictionary');
      return values[index++] ?? undefined;
    }
    return Object.fromEntries(Object.entries(node as Record<string, unknown>)
      .map(([key, value]) => [key, visit(value)]));
  }
  const expanded = visit(reference);
  if (index !== values.length) throw new Error('Invalid compact English dictionary');
  return expanded;
}
let en: Messages | null = null;

/**
 * Registra el inglés compacto (idempotente). El inglés se expande sobre la
 * estructura del castellano: antes hay que tener cargadas TODAS sus áreas
 * (en el navegador, loadSpanishAreas(I18N_AREAS)).
 */
export function registerCompactEnglish(compact: CompactEnglish): void {
  if (en) return;
  if (!hasSpanishAreas(I18N_AREAS)) throw new Error('[i18n] El inglés necesita el castellano completo cargado');
  en = Object.fromEntries(Object.entries(es).map(([area, reference]) => [
    area, expandEnglish(reference, compact[area as keyof typeof compact]),
  ])) as Messages;
}

if (bundledCompactEnglish) registerCompactEnglish(bundledCompactEnglish);

/** ¿Está ya el diccionario inglés en memoria? (en el navegador, tras cargarlo). */
export function hasEnglishMessages(): boolean {
  return en !== null;
}

export const messages: Record<Locale, Messages> = {
  es,
  // Mientras el inglés no está cargado (solo en el navegador), es = referencia.
  get en() { return en ?? es; },
};

export function getMessages(locale: Locale): Messages {
  return messages[locale] ?? messages.es;
}

// Re-export del tipo clave: los consumidores lo importan de
// '@/lib/i18n/messages' (lib/constants.ts, lib/nav/build-crumbs.ts).
export type { TranslationKey, TranslationVars } from '../t.ts';
