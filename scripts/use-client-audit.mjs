/**
 * D2c: detector compartido de "'use client' justificado o no".
 *
 * Un solo modulo de verdad para las dos herramientas que lo usan:
 *   - `scripts/scan-use-client.mjs`      (inventario A/B/C/D para humanos)
 *   - `scripts/no-useless-use-client.test.ts` (el guard permanente)
 *
 * Que no valga un grep por `onClick`: decidir si un fichero necesita la
 * directiva exige saber que IDENTIFICADORES emite y desde que modulo importan
 * cada uno. Un grep daria falsos positivos con la palabra "onClose" en un
 * string de copy, en un comentario o en una prop de un componente que no la
 * ejecuta, y no distinguiria `import { useState } from 'react'` de
 * `function useState() {}` declarado en el propio fichero. Por eso se usa el
 * TS compiler API, que ya esta en `node_modules` (sin dependencias nuevas).
 */
import { readFileSync, readdirSync } from 'node:fs';
import { join, sep } from 'node:path';
import ts from 'typescript';

/* ------------------------------------------------------------------ *
 * Catalogos. Cada entrada lleva el porque: son las decisiones que
 * hacen que el guard no mienta en ninguna direccion.
 * ------------------------------------------------------------------ */

/**
 * Hooks de React que solo existen en el cliente. `useState`, `useEffect`,
 * `useReducer`, `useRef`, `useContext`, `useTransition`... obligan a la
 * directiva por si solos.
 */
export const CLIENT_HOOKS = new Set([
  'useState',
  'useEffect',
  'useLayoutEffect',
  'useInsertionEffect',
  'useReducer',
  'useRef',
  'useContext',
  'useSyncExternalStore',
  'useTransition',
  'useDeferredValue',
  'useOptimistic',
  'useActionState',
  'useImperativeHandle',
  'useEffectEvent',
]);

/**
 * Hooks que se ejecutan igual en el servidor, asi que NO justifican la
 * directiva. `useMemo` y `useCallback` estan aqui y no en CLIENT_HOOKS a
 * proposito: se ejecutan durante el render del servidor, asi que un fichero
 * que solo los use sigue pudiendo ser Server Component. (Si estan, el guard
 * detectaria menos, no mas: el coste de un falso negativo es un modulo
 * cliente de mas, no un bug roto.)
 *
 * `useCallback`/`useMemo` no sonsenales DUROS pero si se cuentan aparte
 * (`memo-callback`) para poder informar sin justificar.
 */
export const SERVER_SAFE_HOOKS = new Set(['useId', 'use', 'useDebugValue', 'useMemo', 'useCallback']);

/**
 * Hooks de `next/navigation`. No son opcionales: la documentacion de Next 16
 * dice literalmente "Reading the current URL from a Server Component is not
 * supported. This design is intentional to support layout state being
 * preserved across page navigations" y "usePathname intentionally requires
 * using a Client Component"
 * (node_modules/next/dist/docs/01-app/03-api-reference/04-functions/use-pathname.md).
 * Contarlos como opcionales habria marcado `components/layout/Breadcrumbs.tsx`
 * como `'use client'` innecesario, y quitar la directiva ahi NO compila.
 */
export const NEXT_NAV_HOOKS = new Set([
  'usePathname',
  'useSearchParams',
  'useRouter',
  'useParams',
  'useSelectedLayoutSegment',
  'useSelectedLayoutSegments',
]);

/**
 * Hooks de `react-dom` (form actions). Cliente por definicion: leen un
 * contexto de React que solo existe tras la hidratacion. Sin esto,
 * `components/screeners/SubmitButton.tsx` (que solo usa `useFormStatus`)
 * pareceria un Server Component y el boton dejaria de espiar el envio.
 */
export const REACT_DOM_HOOKS = new Set(['useFormStatus', 'useFormState']);

/**
 * Globales que no existen en el runtime de servidor de React.
 * `URL` y `CustomEvent` NO estan a proposito: existen en Node 22 y marcarlos
 * daria falsos positivos en cualquier `new URL(req.url)`.
 */
export const BROWSER_GLOBALS = new Set([
  'window',
  'document',
  'localStorage',
  'sessionStorage',
  'navigator',
  'location',
  'matchMedia',
  'requestAnimationFrame',
  'cancelAnimationFrame',
  'IntersectionObserver',
  'ResizeObserver',
  'FileReader',
  'HTMLElement',
  'getComputedStyle',
]);

/**
 * Paquetes que arrastran runtime de cliente de verdad (hooks, refs,
 * listeners). No se pueden renderizar en un Server Component.
 */
export const CLIENT_ONLY_PKGS = [
  'recharts',
  'react-hook-form',
  'cmdk',
  'sonner',
  'react-markdown',
  'react-select-country-list',
  'better-auth/react',
  '@radix-ui/',
  'next-themes',
  'framer-motion',
  'react-joyride',
  'date-fns',
];

/**
 * Paquetes que PARECEN cliente y son puros: se renderizan en el servidor sin
 * coste de hidratacion. Contarlos como senal daria falsos positivos en casi
 * toda la app (`lucide-react` esta en la mayoria de los 72 ficheros con
 * `'use client'`), que es exactamente como un guard se vuelve ignorado.
 */
export const SERVER_SAFE_PKGS = ['lucide-react', 'clsx', 'tailwind-merge', 'class-variance-authority', 'qrcode.react', 'zod'];

export function isClientOnlyPkg(spec) {
  if (SERVER_SAFE_PKGS.some((p) => spec === p || spec.startsWith(p))) return false;
  return CLIENT_ONLY_PKGS.some((p) => spec === p || spec.startsWith(p));
}

/* ------------------------------------------------------------------ *
 * Lectura del fuente
 * ------------------------------------------------------------------ */

export function listSourceFiles(absDir, out = []) {
  let entries;
  try {
    entries = readdirSync(absDir, { withFileTypes: true });
  } catch {
    return out;
  }
  for (const entry of entries) {
    const full = join(absDir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === 'node_modules' || entry.name === '.next' || entry.name.startsWith('.')) continue;
      listSourceFiles(full, out);
    } else if (/\.tsx?$/.test(entry.name)) {
      out.push(full);
    }
  }
  return out;
}

/**
 * La directiva solo cuenta si es el PROLOGO: el primer statement del fichero
 * tiene que ser el literal. Un `'use client'` en medio del fichero (p.ej.
 * dentro de una cadena multilinea) no activa nada, asi que contarlo daria un
 * guard que finge vigilar algo que no existe.
 */
export function hasUseClientDirective(text) {
  const sf = ts.createSourceFile('t.tsx', text, ts.ScriptTarget.Latest, false, ts.ScriptKind.TSX);
  const first = sf.statements[0];
  if (!first) return false;
  if (ts.isImportDeclaration(first) || ts.isExportDeclaration(first)) return false;
  if (ts.isExpressionStatement(first) && ts.isStringLiteral(first.expression)) {
    return first.expression.text === 'use client';
  }
  return false;
}

/**
 * Senales de cliente que emite un fichero, y sus imports con especificador.
 * Devuelve Sets (no arrays) para que el consumidor pueda intersectarlos.
 */
export function analyzeSource(rel, text) {
  const sf = ts.createSourceFile(rel, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const signals = new Set();
  const imports = new Set();

  // Nombres declarados en el propio fichero. Sin esto, un componente que
  // declara `const window = ...` o una funcion local `useState` se marcaria
  // como cliente sin serlo.
  const localNames = new Set();
  const collectLocals = (node) => {
    if (ts.isFunctionDeclaration(node) && node.name) localNames.add(node.name.text);
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name)) localNames.add(node.name.text);
    if (ts.isParameter(node) && ts.isIdentifier(node.name)) localNames.add(node.name.text);
    if (ts.isBindingElement(node) && ts.isIdentifier(node.name)) localNames.add(node.name.text);
    if (ts.isTypeAliasDeclaration(node) && ts.isIdentifier(node.name)) localNames.add(node.name.text);
    if (ts.isInterfaceDeclaration(node) && ts.isIdentifier(node.name)) localNames.add(node.name.text);
    ts.forEachChild(node, collectLocals);
  };
  collectLocals(sf);

  const walkNode = (node) => {
    if (ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier)) {
      imports.add(node.moduleSpecifier.text);
    }
    // `dynamic(() => import('./X'))` tambien es un import: si no se cuenta,
    // los ficheros que solo se usan asi parecen huerfanos.
    if (ts.isImportKeyword(node) && node.parent && ts.isCallExpression(node.parent) && ts.isStringLiteral(node.parent.arguments[0])) {
      imports.add(node.parent.arguments[0].text);
    }

    if (ts.isCallExpression(node)) {
      const callee = node.expression;
      const name = ts.isIdentifier(callee) ? callee.text : null;
      if (name === 'lazy') signals.add('lazy');
      if (name === 'dynamic') {
        const opts = node.arguments[1];
        const ssrFalse =
          opts &&
          ts.isObjectLiteralExpression(opts) &&
          opts.properties.some(
            (p) =>
              ts.isPropertyAssignment(p) &&
              ((ts.isIdentifier(p.name) && p.name.text === 'ssr') || (ts.isStringLiteral(p.name) && p.name.text === 'ssr')) &&
              p.initializer.kind === ts.SyntaxKind.FalseKeyword,
          );
        signals.add(ssrFalse ? 'dynamic-ssr-false' : 'next-dynamic');
      }
      if (name && (CLIENT_HOOKS.has(name) || NEXT_NAV_HOOKS.has(name) || REACT_DOM_HOOKS.has(name)) && !localNames.has(name)) {
        signals.add(name);
      }
      if (name && SERVER_SAFE_HOOKS.has(name) && !localNames.has(name)) signals.add('memo-callback');
      if (name === 'createContext' || name === 'createServerContext') signals.add(name);
    }

    // Event handlers JSX: `onClick`, `onChange`, `onSubmit`, `onMouseEnter`...
    if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
      for (const attr of node.attributes.properties) {
        // `{...props}` puede traer handlers que el detector no ve. Es senal
        // aceptada (no se puede demostrar lo contrario de forma automatica),
        // pero NO es senal dura: asi que se comprueba ANTES de filtrar los
        // atributos con nombre, no despues.
        if (ts.isJsxSpreadAttribute(attr)) signals.add('jsx-spread');
        else if (ts.isJsxAttribute(attr)) {
          const attrName = attr.name.getText(sf);
          if (/^on[A-Z]/.test(attrName)) signals.add(`jsx-${attrName}`);
        }
      }
    }

    if (ts.isIdentifier(node)) {
      const t = node.text;
      if (BROWSER_GLOBALS.has(t) && !localNames.has(t)) {
        const parent = node.parent;
        // Cuando el identificador es un NOMBRE y no una referencia
        // (`foo.window`, `{ window: 1 }`, `<div window />`) no hay acceso al
        // global, asi que no se cuenta.
        const isNameOnly =
          parent &&
          ((ts.isPropertyAccessExpression(parent) && parent.name === node) ||
            (ts.isPropertyAssignment(parent) && parent.name === node) ||
            (ts.isJsxAttribute(parent) && parent.name === node) ||
            (ts.isImportSpecifier(parent) && parent.name === node) ||
            (ts.isBindingElement(parent) && parent.propertyName === node));
        if (!isNameOnly) signals.add(`browser:${t}`);
      }
    }

    if (ts.isNewExpression(node) && ts.isIdentifier(node.expression) && BROWSER_GLOBALS.has(node.expression.text)) {
      signals.add(`browser:new ${node.expression.text}`);
    }

    ts.forEachChild(node, walkNode);
  };
  walkNode(sf);

  return {
    rel,
    text,
    hasUseClient: hasUseClientDirective(text),
    signals,
    imports,
  };
}

/* ------------------------------------------------------------------ *
 * Grafo de imports
 * ------------------------------------------------------------------ */

const EXT_CANDIDATES = ['', '.tsx', '.ts', '.jsx', '.js', '/index.tsx', '/index.ts'];

/** Resuelve un especificador relativo o con alias `@/` a una ruta del repo. */
export function resolveImport(fromRel, spec, known) {
  let base;
  if (spec.startsWith('@/') || spec.startsWith('~/')) base = posixNormalize(spec.slice(2));
  else if (spec.startsWith('.')) base = posixNormalize(posixJoin(posixDirname(fromRel), spec));
  else return null;
  for (const ext of EXT_CANDIDATES) {
    const candidate = base + ext;
    if (known.has(candidate)) return candidate;
  }
  return null;
}

/* Utilidades posix: los especificadores de import son siempre '/' y este guard
 * corre igual en Windows (dev) y Linux (CI). */
function posixNormalize(p) {
  const isAbs = p.startsWith('/');
  const parts = [];
  for (const seg of p.split('/')) {
    if (seg === '' || seg === '.') continue;
    if (seg === '..') parts.pop();
    else parts.push(seg);
  }
  return (isAbs ? '/' : '') + parts.join('/');
}
function posixJoin(a, b) {
  return `${a.replace(/\/$/, '')}/${b}`;
}
function posixDirname(p) {
  const i = p.lastIndexOf('/');
  return i <= 0 ? '.' : p.slice(0, i);
}

/**
 * Senales que NO justifican la directiva por si solas, pero que tampoco
 * permiten declararla muerta.
 *
 * `memo-callback` = useMemo/useCallback. Se ejecutan en el render del
 * servidor, asi que un fichero que solo los use PUEDE ser Server Component.
 * Si contaran como justificacion, el guard no detectaria el caso D2c mas
 * tentador: "usa un hook, luego es cliente" con un hook que corre en el
 * servidor. No justifican; solo se informan.
 *
 * `jsx-spread` (`{...props}`) y `next-dynamic` sin `ssr:false` sí se aceptan:
 * pueden arrastrar un handler o un modulo cliente que el detector no puede
 * ver, asi que declararlos muertos seria un falso positivo. Un guard que
 * descarga la duda de mas sobre una indireccion se ignora la segunda vez.
 */
export const NON_JUSTIFYING_SIGNALS = new Set(['memo-callback']);
export const UNPROVABLE_SIGNALS = new Set(['jsx-spread', 'next-dynamic']);

/**
 * Audita un conjunto de ficheros y responde, para cada uno con `'use client'`,
 * si la directiva esta JUSTIFICADA.
 *
 * Motivos que justifican, en orden de fuerza:
 *  1. senal dura propia (hook de cliente, handler JSX, global de navegador,
 *     `dynamic ssr:false`, `lazy`, `createContext`);
 *  2. importar un modulo que ya es cliente (`@radix-ui/...` o un fichero
 *     local con la directiva): sin la directiva el import revienta;
 *  3. una indireccion que no se puede desmentir (`jsx-spread`,
 *     `next-dynamic` sin `ssr:false`).
 *
 * Lo que NO justifica: `useMemo`/`useCallback` (corren en servidor) ni que el
 * fichero sea importado por un Client Component. En el segundo caso sigue
 * siendo cliente por herencia y quitar la directiva no ahorra un byte: es el
 * unico caso que necesita excepcion manual, porque el guard no puede saber si
 * el padre va a seguir siendo cliente mañana.
 */
export function auditUseClient(analyzedList) {
  const known = new Set(analyzedList.map((a) => a.rel));
  const clientRoots = new Set(analyzedList.filter((a) => a.hasUseClient).map((a) => a.rel));

  const resolvedImports = new Map();
  const importersOf = new Map(analyzedList.map((a) => [a.rel, new Set()]));
  for (const a of analyzedList) {
    const set = new Set();
    for (const spec of a.imports) {
      const target = resolveImport(a.rel, spec, known);
      if (target) {
        set.add(target);
        importersOf.get(target).add(a.rel);
      }
    }
    resolvedImports.set(a.rel, set);
  }

  // ¿Este modulo esta debajo de un Client Component? Es la condicion que hace
  // que quitar su directiva NO ahorre nada: sigue siendo cliente por herencia.
  // Se recorre hacia ARRIBA por los importadores, nunca hacia abajo (bajar
  // seria preguntar "¿este modulo usa cliente?", que no es lo mismo).
  const importedByClient = (rel, seen = new Set()) => {
    if (seen.has(rel)) return false;
    seen.add(rel);
    for (const importer of importersOf.get(rel) ?? []) {
      if (clientRoots.has(importer)) return true;
      if (importedByClient(importer, seen)) return true;
    }
    return false;
  };

  return analyzedList.map((a) => {
    const targets = resolvedImports.get(a.rel);
    const importsClientModule = [...targets].filter((t) => clientRoots.has(t));
    const clientPkgs = [...a.imports].filter(isClientOnlyPkg);

    const hardSignals = [...a.signals].filter((s) => !NON_JUSTIFYING_SIGNALS.has(s));

    const reasons = [];
    for (const s of hardSignals) reasons.push(s);
    for (const p of clientPkgs) reasons.push(`libreria cliente: ${p}`);
    for (const t of importsClientModule) reasons.push(`importa cliente: ${t}`);

    return {
      rel: a.rel,
      hasUseClient: a.hasUseClient,
      signals: a.signals,
      hardSignals,
      unprovable: hardSignals.filter((s) => UNPROVABLE_SIGNALS.has(s)),
      importsClientModule,
      clientPkgs,
      justified: reasons.length > 0,
      reasons,
      inheritedFromClient: importedByClient(a.rel),
      importers: [...(importersOf.get(a.rel) ?? [])].sort(),
    };
  });
}

/** Atajo: lista, lee y audita los `.tsx?` de varios subdirectorios del repo. */
export function auditRepo(repoRoot, subdirs) {
  const files = subdirs.flatMap((d) => listSourceFiles(join(repoRoot, d)));
  const analyzed = files.map((abs) => analyzeSource(abs.slice(repoRoot.length + 1).split(sep).join('/'), readFileSync(abs, 'utf8')));
  return auditUseClient(analyzed);
}
