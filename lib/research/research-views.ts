/**
 * Selector de la ficha de empresa: 3 pestañas visibles (Resumen, Números,
 * Fuentes) y un menú "Más" con lo de seguimiento. Cada pestaña agrupa sus
 * módulos en una sola fila; nada se borra.
 *
 * COMPATIBILIDAD: los `?view=` antiguos siguen siendo URLs validas. Cada
 * modulo conserva su clave historica (`overview`, `thesis`, `chat`...) y
 * `asView` acepta tanto una clave de modulo como una clave de grupo (nueva o
 * de los pasos anteriores Entender/Valorar/Seguir), asi que
 * `/research/AAPL?view=thesis` y `/research/AAPL?view=tesis` abren lo mismo.
 *
 * Test funcional: scripts/research-views-guard.test.ts.
 */
export const GROUPS = [
  { key: 'resumen', label: 'Resumen', entry: 'overview' },
  { key: 'numeros', label: 'Números', entry: 'financials' },
  { key: 'fuentes', label: 'Fuentes', entry: 'documents' },
  { key: 'mas', label: 'Más', entry: 'changes' },
] as const;

export const MODULES = [
  { key: 'overview', label: 'Vista general', group: 'resumen' },
  { key: 'thesis', label: 'Tesis', group: 'resumen' },
  { key: 'noticias', label: 'Noticias', group: 'resumen' },
  { key: 'financials', label: 'Financieros', group: 'numeros' },
  { key: 'valuation', label: 'Valoración', group: 'numeros' },
  { key: 'model', label: 'Modelo a largo plazo', group: 'numeros' },
  { key: 'peers', label: 'Comparables', group: 'numeros' },
  { key: 'moat', label: 'Foso', group: 'numeros' },
  { key: 'capital', label: 'Dilución y recompras', group: 'numeros', path: 'share-capital' },
  { key: 'terminal', label: 'Terminal financiero', group: 'numeros', path: 'financial-terminal' },
  { key: 'supuestos', label: 'Supuestos de drivers', group: 'mas', path: 'driver-assumptions' },
  { key: 'market-opportunity', label: 'Oportunidad de mercado', group: 'mas' },
  { key: 'documents', label: 'Documentos', group: 'fuentes' },
  { key: 'sources', label: 'Fuentes', group: 'fuentes' },
  { key: 'chat', label: 'Chat con fuentes', group: 'fuentes' },
  { key: 'changes', label: 'Cambios y revisiones', group: 'mas' },
  { key: 'holders', label: 'Superinversores', group: 'mas' },
  { key: 'lecciones', label: 'Lecciones de decisiones', group: 'mas', path: 'decision-lessons' },
  { key: 'directiva', label: 'Credibilidad de la directiva', group: 'mas', path: 'management-credibility' },
  { key: 'satellites', label: 'Satélites AST', group: 'mas' },
] as const;

export type View = (typeof MODULES)[number]['key'];

/**
 * URLs antiguas: las claves de los grupos previos (6 grupos y los 3 pasos
 * Entender/Valorar/Seguir) siguen abriendo su modulo de entrada.
 *
 * Map, no objeto llano: un lookup por string sobre un Record hereda del
 * prototipo (`?view=constructor` devolveria `Object` truthy y se colaria como
 * View). `Map.get` es inmune (auditoria #1073).
 */
const LEGACY_GROUP_ENTRIES = new Map<string, View>([
  ['resumen', 'overview'],
  ['entender', 'overview'],
  ['valorar', 'model'],
  ['seguir', 'changes'],
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
