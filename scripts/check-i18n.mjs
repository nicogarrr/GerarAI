/**
 * Guard de i18n. Fallo rapido y sin dependencias para tres regresiones concretas:
 *
 *  1. Una clave de `t()` que ya no existe en lib/i18n/es.json. En produccion
 *     `t()` devuelve la propia clave, asi que el usuario veria literalmente
 *     "common.states.empty" en pantalla.
 *  2. Un literal funcional en ingles reintroducido en app/ o components/. La
 *     app es es-ES y en el repo ya se colaron paginas enteras en ingles
 *     (app/(root)/screeners/[screenId]/page.tsx era un unico literal de 16
 *     lineas) y el boton de cerrar de todos los modales decia "Close".
 *  3. Claves huerfanas: en el diccionario pero sin ningun `t()` que las use.
 *     En produccion son copy que nadie pinta (y que nadie revisa cuando
 *     cambia la interfaz). Solo se falla si la huerfana es NUEVA: las ya
 *     conocidas estan listadas con su motivo y la lista no puede crecer sola.
 *
 * Solo se inspecciona TEXTO VISIBLE: el contenido de los literales de cadena y
 * los text nodes de JSX. Los identificadores (`isSubmitting`), los nombres de
 * funcion (`getMoatQualityScore`), los valores de atributo (`type="submit"`) y
 * las claves del backend no se tocan, porque ahi el ingles es legitimo.
 *
 * Uso: node scripts/check-i18n.mjs
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, extname } from "node:path";

const ROOT = process.cwd();
const es = {};
for (const area of readdirSync(join(ROOT, "lib/i18n/messages/es"))) {
  if (area.endsWith(".json")) es[area.slice(0, -5)] = JSON.parse(readFileSync(join(ROOT, "lib/i18n/messages/es", area), "utf8"));
}

/* ------------------------------------------------------------------ *
 * 1. Claves de t() que no existen
 * ------------------------------------------------------------------ */

const keyPaths = (node, prefix = "") => {
  if (node === null || typeof node !== "object" || Array.isArray(node)) return [prefix];
  return Object.entries(node).flatMap(([key, value]) =>
    keyPaths(value, prefix ? `${prefix}.${key}` : key),
  );
};

const validKeys = new Set(keyPaths(es));
// Nonempty English areas must match Spanish leaf keys and placeholders.
const parityErrors = [];
for (const file of readdirSync(join(ROOT, 'lib/i18n/messages/en')).filter((f) => f.endsWith('.json'))) {
  const area = file.slice(0, -5);
  const en = JSON.parse(readFileSync(join(ROOT, 'lib/i18n/messages/en', file), 'utf8'));
  if (Object.keys(en).length === 0) continue; // Area not migrated yet.
  const leaves = (node, prefix = '') => Object.entries(node).flatMap(([k, v]) => {
    const path = prefix ? `${prefix}.${k}` : k;
    return typeof v === 'string' ? [[path, v]] : leaves(v, path);
  });
  const expected = new Map(leaves(es[area] ?? {}));
  const actual = new Map(leaves(en));
  for (const key of new Set([...expected.keys(), ...actual.keys()])) {
    const a = expected.get(key), b = actual.get(key);
    const vars = (value) => [...(value ?? '').matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort().join(',');
    if (a === undefined || b === undefined || vars(a) !== vars(b)) parityErrors.push(`${area}.${key}`);
  }
}
if (parityErrors.length) {
  console.error('i18n: ES/EN key or placeholder mismatch:', parityErrors.join(', '));
  process.exit(1);
}


const walk = (dir, out = []) => {
  for (const entry of readdirSync(dir)) {
    if (entry === "node_modules" || entry.startsWith(".")) continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) walk(full, out);
    else if ([".ts", ".tsx"].includes(extname(full))) out.push(full);
  }
  return out;
};

const files = [
  ...walk(join(ROOT, "app")),
  ...walk(join(ROOT, "components")),
  ...walk(join(ROOT, "lib")),
];

const missingKeys = [];
for (const file of files) {
  const source = readFileSync(file, "utf8");
  for (const match of source.matchAll(/\bt\(\s*'([a-z][A-Za-z0-9]*(?:\.[A-Za-z0-9]+)+)'/g)) {
    if (!validKeys.has(match[1])) {
      missingKeys.push(`${file.slice(ROOT.length + 1)}: ${match[1]}`);
    }
  }
}

/* ------------------------------------------------------------------ *
 * 2. Texto visible en ingles
 * ------------------------------------------------------------------ */

// Frases: coincidencia por contenida en un chunk de texto visible.
const ENGLISH_PHRASES = [
  "Loading...", "Loading…", "No results", "Search for a command", "Command Palette",
  "Show commands", "Something went wrong", "Try again", "Get started", "Learn more",
  "Read more", "Coming soon", "Under construction", "Not available", "No data",
  "Ticker Symbol", "Company Name", "Last Close", "Open Price",
  "Avg. Volume", "As of", "Updated at", "Created at", "Saved screen", "No match",
  "new match", "Portfolio totals exclude", "Work product",
  // Nulos: los canonicos son NA='N/D' y NO_CORRIDO='No corrido'.
  "N/A",
];

// Etiquetas enteras: coincidencia solo si el chunk ES la etiqueta.
const ENGLISH_LABELS = new Set([
  "Close", "Retry", "Undo", "Submit", "Cancel", "Delete", "Remove", "Dismiss",
  "Offline", "Not found", "Unknown", "Required", "Optional",
  "Example", "Missing", "PASS", "FAIL", "match", "Overview", "Settings",
  "Dashboard", "Welcome back", "Create account", "Sign in", "Sign out",
]);

// Se ignoran del todo los ficheros donde el ingles es correcto por diseno.
const ALLOW = [
  // Formato de datos parseados del backend, no copy de UI.
  "lib/glossary.ts",
  // Claves de objeto que viajan al data-engine, no etiquetas de interfaz.
  "lib/constants.ts",
  // server actions: sus "labels" son claves de registro del backend.
  "lib/actions/",
  // Los propios diccionarios y su infraestructura.
  "lib/i18n/t.ts",
  "lib/i18n/messages/",
  // Placeholders por locale («N/D» es, «N/A» en; «No corrido» / «Not run»):
  // son formato de datos, no copy de interfaz (format.ts).
  "lib/format.ts",
];

/** Texto visible de un fichero: literales de cadena y text nodes de JSX. */
const visibleChunks = (source) => {
  const chunks = [];
  const withoutComments = source
    .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, " "))
    .replace(/\/\/[^\n]*/g, (m) => m.replace(/[^\n]/g, " "));

  // Literales de cadena que NO son valores de atributo (`foo="bar"`).
  const literal = /(^|[=({\[,;:?&|!+\-*/%<>]\s*)('([^'\\\n]{2,})'|"([^"\\\n]{2,})"|`([^`\\]{2,})`)/g;
  for (const match of withoutComments.matchAll(literal)) {
    const value = match[3] ?? match[4] ?? match[5] ?? "";
    if (!/[\p{L}]/u.test(value)) continue;
    if (/^[a-z0-9_.-]+$/i.test(value) && !/[A-Z]/.test(value)) continue; // clave o enum
    chunks.push(value);
  }

  // Text nodes de JSX: >texto<
  for (const match of withoutComments.matchAll(/>([^<>{}]*[a-zA-ZáéíóúñÁÉÍÓÚÑ][^<>{}]*)</g)) {
    const value = match[1].trim();
    if (value) chunks.push(value);
  }

  return chunks;
};

const englishHits = [];
for (const file of files) {
  const rel = file.slice(ROOT.length + 1).replace(/\\/g, "/");
  if (ALLOW.some((prefix) => rel === prefix || rel.startsWith(prefix))) continue;
  const source = readFileSync(file, "utf8");
  for (const chunk of visibleChunks(source)) {
    const trimmed = chunk.trim();
    const line = source.slice(0, source.indexOf(chunk)).split("\n").length;
    if (ENGLISH_LABELS.has(trimmed)) {
      englishHits.push(`${rel}:~${line}  etiqueta  "${trimmed}"`);
      continue;
    }
    const phrase = ENGLISH_PHRASES.find((p) => trimmed.includes(p));
    if (phrase) englishHits.push(`${rel}:~${line}  "${phrase}"  ->  ${trimmed.slice(0, 80)}`);
  }
}

/* ------------------------------------------------------------------ *
 * 3. Claves huerfanas: en el diccionario pero sin uso
 * ------------------------------------------------------------------ */

/**
 * Claves que llegan a `t()` a traves de una variable: `t(item.labelKey)` en
 * components/knowledge-graph/KnowledgeGraphCanvas.tsx, con el labelKey
 * construido como literal en lib/knowledge-graph/graph-model.ts. Sin contar
 * esos literales como uso, todo el bloque `knowledgeGraph.detail.fields.*`
 * pareceria huerfano siendo copy que si se pinta.
 */
const used = new Set();
const literals = new Set();
for (const file of files) {
  const source = readFileSync(file, "utf8");
  for (const match of source.matchAll(/\bt\(\s*'([^']+)'/g)) used.add(match[1]);
  // Solo literales con FORMA de clave (mismo patron que el chequeo 1): un
  // "cualquier cosa entre comillas" se come bloques enteros cuando hay
  // comillas sin parear en comentarios y esconde usos reales.
  for (const match of source.matchAll(/'([a-z][A-Za-z0-9]*(?:\.[A-Za-z0-9]+)+)'/g)) literals.add(match[1]);
}
for (const key of literals) if (validKeys.has(key)) used.add(key);

const orphans = [...validKeys].filter((k) => !used.has(k));

/**
 * Huerfanas conocidas, con motivo. RATCHET y no carta blanca: una huerfana
 * NUEVA es fallo, para que el diccionario no crezca solo con copy que nadie
 * pinta. Si una clave de esta lista empieza a usarse, el guard AVISA para
 * que se borre la entrada (aviso y no fallo porque 2 de las claves de
 * knowledgeGraph las va a consumir el trabajo de honestidad de fx6 y no
 * queremos bloquear ese landing).
 */
const KNOWN_ORPHANS = {
  // global-error se monta sin provider: consume errors.globalError.* leyendo
  // el diccionario del area directamente (no puede pasar por t()).
  'errors.globalError.title': 'consumida en app/global-error.tsx por acceso directo al diccionario (sin provider)',
  'errors.globalError.body': 'consumida en app/global-error.tsx por acceso directo al diccionario (sin provider)',
  'errors.globalError.reference': 'consumida en app/global-error.tsx por acceso directo al diccionario (sin provider)',
  'errors.globalError.retry': 'consumida en app/global-error.tsx por acceso directo al diccionario (sin provider)',
  'errors.globalError.htmlLang': 'consumida en app/global-error.tsx por acceso directo al diccionario (sin provider)',
  // Copy segura de errores del backend (bloque ERROR_MESSAGES trasladado de
  // lib/constants.ts): el mapeo codigo -> clave vive en lib/types/errors.ts,
  // fuera del carril que migro los diccionarios; se consume al adaptarlo.
  'errors.backend.invalidSymbol': 'copy de error de backend; el mapeo codigo -> clave se adapta en lib/types/errors.ts',
  'errors.backend.missingApiKey': 'copy de error de backend; el mapeo codigo -> clave se adapta en lib/types/errors.ts',
  'errors.backend.rateLimitExceeded': 'copy de error de backend; el mapeo codigo -> clave se adapta en lib/types/errors.ts',
  'errors.backend.databaseError': 'copy de error de backend; el mapeo codigo -> clave se adapta en lib/types/errors.ts',
  'errors.backend.externalApiError': 'copy de error de backend; el mapeo codigo -> clave se adapta en lib/types/errors.ts',
  'errors.backend.notFound': 'copy de error de backend; el mapeo codigo -> clave se adapta en lib/types/errors.ts',
  'errors.backend.validationError': 'copy de error de backend; el mapeo codigo -> clave se adapta en lib/types/errors.ts',
  // Consumidas via INVESTMENT_GOAL_LABEL_KEYS/RISK_TOLERANCE_LABEL_KEYS/
  // PREFERRED_INDUSTRY_LABEL_KEYS (lib/constants.ts): el literal tiene
  // guiones bajos y el detector de usos no cuenta segmentos con '_'.
  'auth.risk.very_aggressive': 'consumida via RISK_TOLERANCE_LABEL_KEYS (literal con guion bajo no detectado)',
  'auth.industries.real_estate': 'consumida via PREFERRED_INDUSTRY_LABEL_KEYS (literal con guion bajo no detectado)',
  // Consumidas via REASON_LABEL_KEYS (HistoricalStressView), LEDGER_LABEL_KEYS y
  // ATTRIBUTION_ND_LABEL_KEYS (portfolio/intelligence): las claves llevan
  // guion bajo y el detector de usos no cuenta segmentos con '_' (misma
  // limitacion documentada arriba).
  'portfolio.stress.reason_history_gaps': 'consumida via REASON_LABEL_KEYS en components/historical-stress/HistoricalStressView.tsx (guion bajo no detectado)',
  'portfolio.stress.reason_provider_error': 'consumida via REASON_LABEL_KEYS en components/historical-stress/HistoricalStressView.tsx (guion bajo no detectado)',
  'portfolio.stress.reason_no_safe_symbol': 'consumida via REASON_LABEL_KEYS en components/historical-stress/HistoricalStressView.tsx (guion bajo no detectado)',
  'portfolio.stress.reason_currency_mismatch': 'consumida via REASON_LABEL_KEYS en components/historical-stress/HistoricalStressView.tsx (guion bajo no detectado)',
  'portfolio.stress.reason_currency_unverified': 'consumida via REASON_LABEL_KEYS en components/historical-stress/HistoricalStressView.tsx (guion bajo no detectado)',
  'portfolio.stress.reason_incomplete_portfolio': 'consumida via REASON_LABEL_KEYS en components/historical-stress/HistoricalStressView.tsx (guion bajo no detectado)',
  'portfolio.intelligence.ledger_missing_ledger': 'consumida via LEDGER_LABEL_KEYS en app/(root)/portfolio/intelligence/page.tsx (guion bajo no detectado)',
  'portfolio.intelligence.ledger_incomplete_ledger': 'consumida via LEDGER_LABEL_KEYS en app/(root)/portfolio/intelligence/page.tsx (guion bajo no detectado)',
  'portfolio.intelligence.ledger_missing_fx': 'consumida via LEDGER_LABEL_KEYS en app/(root)/portfolio/intelligence/page.tsx (guion bajo no detectado)',
  'portfolio.intelligence.ledger_missing_start_price': 'consumida via LEDGER_LABEL_KEYS en app/(root)/portfolio/intelligence/page.tsx (guion bajo no detectado)',
  'portfolio.intelligence.ledger_missing_start_fx': 'consumida via LEDGER_LABEL_KEYS en app/(root)/portfolio/intelligence/page.tsx (guion bajo no detectado)',
  'portfolio.intelligence.ledger_missing_end_value': 'consumida via LEDGER_LABEL_KEYS en app/(root)/portfolio/intelligence/page.tsx (guion bajo no detectado)',
  'portfolio.intelligence.ledger_fallback': 'fallback de LEDGER_LABEL_KEYS en app/(root)/portfolio/intelligence/page.tsx (guion bajo no detectado)',
  'portfolio.intelligence.attrNd_fundamental_growth': 'consumida via ATTRIBUTION_ND_LABEL_KEYS en app/(root)/portfolio/intelligence/page.tsx (guion bajo no detectado)',
  'portfolio.intelligence.attrNd_multiple': 'consumida via ATTRIBUTION_ND_LABEL_KEYS en app/(root)/portfolio/intelligence/page.tsx (guion bajo no detectado)',
  'portfolio.intelligence.attrNd_dividends': 'consumida via ATTRIBUTION_ND_LABEL_KEYS en app/(root)/portfolio/intelligence/page.tsx (guion bajo no detectado)',
  'portfolio.intelligence.attrNd_buybacks': 'consumida via ATTRIBUTION_ND_LABEL_KEYS en app/(root)/portfolio/intelligence/page.tsx (guion bajo no detectado)',
  'portfolio.intelligence.attrNd_dilution': 'consumida via ATTRIBUTION_ND_LABEL_KEYS en app/(root)/portfolio/intelligence/page.tsx (guion bajo no detectado)',
  'portfolio.intelligence.attrNd_fx': 'consumida via ATTRIBUTION_ND_LABEL_KEYS en app/(root)/portfolio/intelligence/page.tsx (guion bajo no detectado)',
  'portfolio.intelligence.attrNd_sizing': 'consumida via ATTRIBUTION_ND_LABEL_KEYS en app/(root)/portfolio/intelligence/page.tsx (guion bajo no detectado)',
  'portfolio.intelligence.attrNd_fallback': 'fallback de ATTRIBUTION_ND_LABEL_KEYS en app/(root)/portfolio/intelligence/page.tsx (guion bajo no detectado)',

  // Vocabulario canonico del diseno (acciones, estados y etiquetas de tabla)
  // definido en el diccionario comun para que los componentes no reescriban
  // el copy uno a uno. Sin consumidor todavia: si acaba sin adoptarse, la
  // accion correcta es borrar la clave de lib/i18n/es.json.
  'common.actions.save': 'verbo canonico de accion del diseno, sin boton que lo consuma hoy',
  'common.actions.close': 'verbo canonico de accion del diseno, sin boton que lo consuma hoy',
  'common.actions.regenerate': 'verbo canonico de accion del diseno, sin boton que lo consuma hoy',
  'common.actions.export': 'verbo canonico de accion del diseno, sin boton que lo consuma hoy',
  'common.states.empty': 'estado canonico de lista vacia, sin componente que lo consuma hoy',
  'common.states.noResults': 'estado canonico de busqueda sin resultados, sin componente que lo consuma hoy',
  'common.states.error': 'estado canonico de error, sin componente que lo consuma hoy',
  'common.states.errorHint': 'estado canonico de error, sin componente que lo consuma hoy',
  'common.states.backendOfflineTitle': 'estado canonico de backend caido, sin componente que lo consuma hoy',
  'common.labels.company': 'etiqueta canonica de tabla, sin tabla que la consuma hoy',
  'common.labels.sector': 'etiqueta canonica de tabla, sin tabla que la consuma hoy',
  'common.labels.price': 'etiqueta canonica de tabla, sin tabla que la consuma hoy',
  'common.labels.score': 'etiqueta canonica de tabla, sin tabla que la consuma hoy',
  'common.labels.coverage': 'etiqueta canonica de tabla, sin tabla que la consuma hoy',
  'common.labels.confidence': 'etiqueta canonica de tabla, sin tabla que la consuma hoy',
  'common.labels.missing': 'etiqueta canonica de tabla, sin tabla que la consuma hoy',
  'ui.dialog.close': 'copy del dialogo/modal; el cierre todavia se localiza inline',
  'ui.dialog.confirm': 'copy del dialogo/modal; la confirmacion todavia se localiza inline',
  'ui.dialog.cancel': 'copy del dialogo/modal; la cancelacion todavia se localiza inline',
  'ui.command.placeholder': 'copy de la paleta de comandos, sin componente que lo consuma hoy',
  'ui.search.placeholder': 'copy del buscador, sin componente que lo consuma hoy',
  'research.sources': 'rotulo "Fuentes" reservado para la ficha de research, sin consumidor hoy',
  'movers.gainers': 'rotulo de la tabla de movers; la pagina usa caption literal, pendiente de migrar',
  'movers.losers': 'rotulo de la tabla de movers; la pagina usa caption literal, pendiente de migrar',
};

// Finite migration reservations: new orphan keys must still fail the ratchet.
const TRANSITION_KEYS = new Set([
  'nav.portfolio', 'nav.research', 'nav.screeners', 'nav.search',
  'common.actions.delete', 'common.actions.search', 'common.actions.retry',
  'common.states.loading', 'ui.pagination.prev', 'ui.pagination.next',
  'common.na', 'common.notRun',
]);
const newOrphans = orphans.filter((k) => !(k in KNOWN_ORPHANS) && !TRANSITION_KEYS.has(k));
const staleOrphans = Object.keys(KNOWN_ORPHANS).filter((k) => !orphans.includes(k));

/* ------------------------------------------------------------------ */

/* ------------------------------------------------------------------ *
 * 4. t() LEGACY (siempre español) fuera de lib/
 * ------------------------------------------------------------------ */

// `t` de lib/i18n/t está fijado al español: en una página o componente pinta
// español aunque el usuario elija English en Ajustes. En app/, components/ y
// hooks/ se usa getT() (server) o useT() (client). Los imports de solo tipos
// (`import type { TranslationKey }`) siguen permitidos.
const legacyImports = [];
for (const file of [...files, ...walk(join(ROOT, "hooks"))]) {
  const rel = file.slice(ROOT.length + 1);
  if (rel.startsWith("lib/")) continue;
  const source = readFileSync(file, "utf8");
  for (const m of source.matchAll(/import\s+(type\s+)?\{([^}]*)\}\s*from\s*['"]@\/lib\/i18n\/t['"]/g)) {
    if (m[1]) continue;
    const values = m[2].split(",").map((s) => s.trim()).filter((s) => s && !s.startsWith("type "));
    // Excepción: `const esT = t;` como valor por defecto de un parámetro `ti`
    // (helpers que el llamador debe invocar con su t del idioma activo).
    const onlyFallback = values.length === 1 && values[0] === "t" &&
      /const esT(: \w+)? = t;/.test(source) && !/(?<![\w.])t\(/.test(source);
    if (values.length && !onlyFallback) legacyImports.push(`${rel}: ${values.join(", ")}`);
  }
}

const unique = [...new Set(englishHits)];

if (missingKeys.length > 0) {
  console.error(`\ni18n: ${missingKeys.length} clave(s) de t() que no existen en lib/i18n/messages/es/:`);
  for (const hit of missingKeys) console.error(`  - ${hit}`);
}

if (unique.length > 0) {
  console.error(`\ni18n: ${unique.length} literal(es) en ingles en app/ o components/:`);
  for (const hit of unique) console.error(`  - ${hit}`);
}

if (newOrphans.length > 0) {
  console.error(`\ni18n: ${newOrphans.length} clave(s) sin uso NUEVA(S) (no estan en KNOWN_ORPHANS):`);
  for (const key of newOrphans) console.error(`  - ${key}`);
  console.error('  Usa la clave en un t() o, si el copy sobra, borrala de lib/i18n/es.json.');
}

if (staleOrphans.length > 0) {
  console.error(`\ni18n (aviso, no fallo): ${staleOrphans.length} entrada(s) de KNOWN_ORPHANS ya no son huerfanas, borralas:`);
  for (const key of staleOrphans) console.error(`  - ${key}`);
}

if (legacyImports.length > 0) {
  console.error(`\ni18n: ${legacyImports.length} import(s) del t() LEGACY (siempre español) en app/, components/ o hooks/; usa getT() o useT():`);
  for (const hit of legacyImports) console.error(`  - ${hit}`);
}

if (missingKeys.length > 0 || unique.length > 0 || newOrphans.length > 0 || legacyImports.length > 0) {
  console.error(
    "\nVer lib/i18n/README.md. Los anglicismos aceptados (Watchlist, Screeners, Sharpe, CAGR, PER (TTM)...) no deben aparecer aqui.\n",
  );
  process.exit(1);
}

console.log(
  `i18n ok: ${validKeys.size} claves, ${files.length} ficheros, 0 literales en ingles, ${orphans.length} huerfana(s) conocida(s) y listada(s).`,
);
