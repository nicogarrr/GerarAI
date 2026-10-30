/**
 * Ficha de empresa: UNA fila de seis pestañas (Resumen, Tesis, Finanzas,
 * Valoración, Seguimiento, Fuentes). Decisión de Nico del 29-oct-2026
 * (opción 1 de «Una fila, no tres menús»): nada de tres niveles de menús ni
 * cajón «Análisis avanzado»; cada pestaña es una página y sus módulos son
 * secciones seguidas con título claro y ancla, nunca otra barra global.
 *
 * COMPATIBILIDAD: los `?view=` antiguos siguen siendo URLs válidas.
 * `asView` acepta claves de módulo (`thesis`, `moat`...), claves de pestaña
 * (`finanzas`, `valoracion`...) y las claves de los grupos históricos
 * (Entender/Valorar/Seguir, resumen/numeros/fuentes/mas), y devuelve el
 * módulo de ENTRADA de la pestaña correspondiente. `canonicalViewUrl` da la
 * URL canónica de cada clave antigua para que la página redirija una sola
 * vez (una URL por contenido; las subrutas antiguas redirigen a su ancla).
 *
 * Test funcional: scripts/research-views-guard.test.ts y
 * tests/unit/lib/research/research-views.test.ts.
 */
export const TABS = [
  { key: 'resumen', label: 'Resumen', entry: 'overview' },
  { key: 'tesis', label: 'Tesis', entry: 'thesis' },
  { key: 'finanzas', label: 'Finanzas', entry: 'financials' },
  { key: 'valoracion', label: 'Valoración', entry: 'valuation' },
  { key: 'seguimiento', label: 'Seguimiento', entry: 'changes' },
  { key: 'fuentes', label: 'Fuentes', entry: 'documents' },
] as const;

export type TabKey = (typeof TABS)[number]['key'];

/**
 * Módulos de la ficha. `tab` es la pestaña que lo contiene; `anchor` es el
 * id de su sección dentro de esa pestaña (los módulos de entrada no llevan:
 * abren la pestaña desde arriba). `path` recuerda la subruta histórica del
 * módulo: esa URL redirige a la sección (ver `subrouteRedirect`).
 */
export const MODULES = [
  { key: 'overview', label: 'Vista general', tab: 'resumen' },
  { key: 'noticias', label: 'Noticias', tab: 'resumen', anchor: 'noticias' },
  { key: 'thesis', label: 'Tesis', tab: 'tesis' },
  { key: 'financials', label: 'Financieros', tab: 'finanzas' },
  { key: 'terminal', label: 'Terminal financiero', tab: 'finanzas', anchor: 'terminal', path: 'financial-terminal' },
  { key: 'capital', label: 'Dilución y recompras', tab: 'finanzas', anchor: 'dilucion', path: 'share-capital' },
  { key: 'valuation', label: 'Valoración', tab: 'valoracion' },
  { key: 'model', label: 'Modelo a largo plazo', tab: 'valoracion', anchor: 'modelo' },
  { key: 'supuestos', label: 'Supuestos de drivers', tab: 'valoracion', anchor: 'supuestos', path: 'driver-assumptions' },
  { key: 'market-opportunity', label: 'Oportunidad de mercado', tab: 'valoracion', anchor: 'oportunidad' },
  { key: 'peers', label: 'Comparables', tab: 'valoracion', anchor: 'comparables' },
  { key: 'moat', label: 'Foso', tab: 'valoracion', anchor: 'foso' },
  { key: 'changes', label: 'Cambios y revisiones', tab: 'seguimiento' },
  { key: 'holders', label: 'Superinversores', tab: 'seguimiento', anchor: 'superinversores' },
  { key: 'directiva', label: 'Credibilidad de la directiva', tab: 'seguimiento', anchor: 'directiva', path: 'management-credibility' },
  { key: 'lecciones', label: 'Lecciones de decisiones', tab: 'seguimiento', anchor: 'lecciones', path: 'decision-lessons' },
  { key: 'satellites', label: 'Satélites AST', tab: 'seguimiento', anchor: 'satellites' },
  { key: 'documents', label: 'Documentos', tab: 'fuentes' },
  { key: 'sources', label: 'Fuentes', tab: 'fuentes', anchor: 'fuentes' },
  { key: 'chat', label: 'Chat con fuentes', tab: 'fuentes', anchor: 'chat' },
] as const;

export type View = (typeof MODULES)[number]['key'];

type Module = (typeof MODULES)[number];

const moduleByKey = new Map<string, Module>(MODULES.map((module) => [module.key, module]));
const tabByKey = new Map<string, (typeof TABS)[number]>(TABS.map((tab) => [tab.key, tab]));

/**
 * URLs antiguas: claves de los grupos previos (resumen/numeros/fuentes/mas
 * y los 3 pasos Entender/Valorar/Seguir) y alias sueltos. Map, no objeto
 * llano: un lookup por string sobre un Record hereda del prototipo
 * (`?view=constructor` devolvería `Object` truthy y se colaría como View).
 * `Map.get` es inmune (auditoría #1073).
 */
const LEGACY_GROUP_ENTRIES = new Map<string, View>([
  ['resumen', 'overview'],
  // Era «3 pestañas + Más» (antes del 29-oct-2026).
  ['numeros', 'financials'],
  ['mas', 'changes'],
  ['entender', 'overview'],
  ['valorar', 'model'],
  ['seguir', 'changes'],
  ['financieros', 'financials'],
  ['modelo', 'model'],
  ['evidencia', 'documents'],
  // 'tesis', 'seguimiento' y 'fuentes' ya son claves de pestaña canónicas.
]);

function entryOfTab(tab: TabKey): View {
  return tabByKey.get(tab)!.entry;
}

/** Pestaña que contiene una vista (módulo de entrada incluido). */
export function tabOfView(view: View): TabKey {
  return moduleByKey.get(view)?.tab ?? 'resumen';
}

/**
 * Vista activa de la ficha: acepta clave de módulo (`?view=moat`), de
 * pestaña (`?view=valoracion`) o de grupo histórico (`?view=numeros`) y
 * devuelve el módulo de ENTRADA de la pestaña correspondiente. Lo
 * desconocido cae en la vista general, como siempre.
 */
export function asView(value: string | undefined): View {
  const mod = value ? moduleByKey.get(value) : undefined;
  if (mod) return entryOfTab(mod.tab);
  const tab = value ? tabByKey.get(value) : undefined;
  if (tab) return tab.entry;
  const legacy = value ? LEGACY_GROUP_ENTRIES.get(value) : undefined;
  if (legacy) return entryOfTab(tabOfView(legacy));
  return 'overview';
}

/**
 * Ancla de la sección pedida por una clave de módulo (`moat` -> `foso`).
 * Los módulos de entrada y las claves de pestaña/grupo no llevan ancla.
 */
export function viewAnchor(value: string | undefined): string | undefined {
  const mod = value ? moduleByKey.get(value) : undefined;
  return mod && 'anchor' in mod ? mod.anchor : undefined;
}

/** URL canónica de una pestaña: el Resumen es la ficha desnuda, sin `?view=`. */
export function tabHref(ticker: string, tab: TabKey): string {
  const base = `/research/${encodeURIComponent(ticker)}`;
  return tab === 'resumen' ? base : `${base}?view=${tab}`;
}

/** URL canónica de un módulo: la de su pestaña, con ancla si es sección. */
export function moduleHref(ticker: string, module: Module): string {
  const href = tabHref(ticker, module.tab);
  return 'anchor' in module ? `${href}#${module.anchor}` : href;
}

/**
 * URL canónica para una clave `?view=` recibida, o null si la URL ya es
 * canónica (sin parámetro, clave de pestaña, `overview`) o la clave es
 * desconocida (cae en la vista general sin redirect, como siempre).
 */
export function canonicalViewUrl(ticker: string, requested: string | undefined): string | null {
  if (!requested) return null;
  const mod = moduleByKey.get(requested);
  // Las claves de módulo nunca son canónicas (`?view=moat` -> su pestaña con
  // ancla; `?view=overview` -> la ficha desnuda): ninguna coincide con las
  // claves de pestaña, así que siempre hay URL mejor.
  if (mod) return moduleHref(ticker, mod);
  if (tabByKey.has(requested)) return null;
  const legacy = LEGACY_GROUP_ENTRIES.get(requested);
  if (legacy) return moduleHref(ticker, moduleByKey.get(legacy)!);
  return null;
}

/**
 * Destino de una subruta histórica de la ficha (`/research/T/share-capital`)
 * dentro de su pestaña, o null si la subruta no era un módulo de la ficha.
 */
export function subrouteRedirect(ticker: string, subroute: string): string | null {
  const mod = MODULES.find((item) => 'path' in item && item.path === subroute);
  return mod ? moduleHref(ticker, mod) : null;
}
