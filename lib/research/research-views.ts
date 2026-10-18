/**
 * Selector de la ficha de empresa. El recorrido simple (WorldStocks punto 1,
 * aprobado por Nico 2026-10-16) son 3 pasos: Entender -> Valorar -> Seguir.
 * Los 19 destinos (14 vistas + 5 subrutas) se agrupan bajo esos 3 pasos;
 * nada se borra, lo secundario queda un nivel debajo.
 *
 * COMPATIBILIDAD: los `?view=` antiguos siguen siendo URLs validas. Cada
 * modulo conserva su clave historica (`overview`, `thesis`, `chat`...) y
 * `asView` acepta tanto una clave de modulo como una clave de grupo, asi que
 * `/research/AAPL?view=thesis` y `/research/AAPL?view=tesis` abren lo mismo.
 *
 * Test funcional: scripts/research-views-guard.test.ts.
 */
export const GROUPS = [
  { key: 'entender', label: '1 · Entender', entry: 'overview' },
  { key: 'valorar', label: '2 · Valorar', entry: 'model' },
  { key: 'seguir', label: '3 · Seguir', entry: 'changes' },
] as const;

export const MODULES = [
  { key: 'overview', label: 'Vista general', group: 'entender' },
  { key: 'moat', label: 'Foso', group: 'entender' },
  { key: 'satellites', label: 'Satélites AST', group: 'seguir' },
  { key: 'thesis', label: 'Tesis', group: 'entender' },
  { key: 'financials', label: 'Financieros', group: 'entender' },
  { key: 'capital', label: 'Dilución y recompras', group: 'entender', path: 'share-capital' },
  { key: 'terminal', label: 'Terminal financiero', group: 'entender', path: 'financial-terminal' },
  { key: 'supuestos', label: 'Supuestos de drivers', group: 'valorar', path: 'driver-assumptions' },
  { key: 'model', label: 'Modelo a largo plazo', group: 'valorar' },
  { key: 'market-opportunity', label: 'Oportunidad de mercado', group: 'valorar' },
  { key: 'valuation', label: 'Valoración', group: 'valorar' },
  { key: 'peers', label: 'Comparables', group: 'valorar' },
  { key: 'documents', label: 'Documentos', group: 'entender' },
  { key: 'sources', label: 'Fuentes', group: 'entender' },
  { key: 'chat', label: 'Chat con fuentes', group: 'entender' },
  { key: 'changes', label: 'Cambios y revisiones', group: 'seguir' },
  { key: 'holders', label: 'Superinversores', group: 'seguir' },
  { key: 'lecciones', label: 'Lecciones de decisiones', group: 'seguir', path: 'decision-lessons' },
  { key: 'directiva', label: 'Credibilidad de la directiva', group: 'seguir', path: 'management-credibility' },
] as const;

export type View = (typeof MODULES)[number]['key'];

/**
 * URLs antiguas: las claves de los 6 grupos previos a los 3 pasos siguen
 * abriendo su modulo de entrada.
 *
 * Map, no objeto llano: un lookup por string sobre un Record hereda del
 * prototipo (`?view=constructor` devolveria `Object` truthy y se colaria como
 * View). `Map.get` es inmune (auditoria #1073).
 */
const LEGACY_GROUP_ENTRIES = new Map<string, View>([
  ['resumen', 'overview'],
  ['tesis', 'thesis'],
  ['financieros', 'financials'],
  ['modelo', 'model'],
  ['evidencia', 'documents'],
  ['seguimiento', 'changes'],
]);

/**
 * Acepta la clave de un modulo (`?view=thesis`) o la de un grupo
 * (`?view=tesis`). Los modulos de subruta se ignoran: no son `?view=`, son
 * rutas propias, asi que una clave suelta cae en la vista general en vez de
 * abrir un documento que no existe en este arbol.
 */
export function asView(value: string | undefined): View {
  const asModule = MODULES.find((module) => module.key === value && !('path' in module));
  if (asModule) return asModule.key;
  const asGroup = GROUPS.find((group) => group.key === value);
  if (asGroup) return asGroup.entry;
  const legacy = value ? LEGACY_GROUP_ENTRIES.get(value) : undefined;
  if (legacy) return legacy;
  return 'overview';
}

/** `?view=` para un modulo; los de subruta conservan su ruta propia. */
export function moduleHref(ticker: string, module: (typeof MODULES)[number]): string {
  const base = `/research/${encodeURIComponent(ticker)}`;
  return 'path' in module ? `${base}/${module.path}` : `${base}?view=${module.key}`;
}
