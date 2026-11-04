/**
 * Guarda (hermana de format-locale-i18n-guard): los helpers .ts de lib/ que
 * formatean cifras, fechas o «N/D» también deben respetar el idioma activo.
 *
 * #4516 cerró la clase en los .tsx traducidos, pero un componente traducido
 * que llama a un helper de lib/ SIN parámetro de locale seguía pintando en
 * castellano en la app en inglés: el helper formateaba dentro con es-ES fijo,
 * con un formateador de `@/lib/format` sin locale o con NA/NO_CORRIDO
 * («Sin datos», «12,5 %», «4.100,00 €» en la ficha, impuestos…).
 *
 * Dos reglas:
 *  A. Un helper de lib/ que recibe `locale` no puede llamar a un formateador de
 *     lib/format.ts sin pasárselo (lo perdería por el camino).
 *  B. Un .tsx traducido (useT/getT/useFormat/getFormat) no puede llamar a un
 *     helper de lib/ que formatea en castellano fijo y no acepta locale. Se
 *     sigue la cadena de llamadas entre helpers (A llama a B que usa es-ES).
 *     Las server actions ('use server') quedan fuera: sus mensajes son frases
 *     enteras en castellano (motivos de rechazo, avisos), otra clase de fallo
 *     que se traduce con un código estable, no pasando el locale a un formato.
 *
 * Cómo arreglarlo: añadir `locale: Locale = DEFAULT_LOCALE` al helper,
 * propagarlo (naFor(locale), formatMoney(..., locale), Intl según locale) y
 * pasarlo desde el componente (`fmt.locale` / useLocale()).
 *
 * Ejecución: node --experimental-strip-types --test scripts/format-locale-lib-helpers-guard.test.ts
 */
import assert from 'node:assert/strict';
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { describe, it } from 'node:test';
import ts from 'typescript';

const ROOT = process.cwd();
const FORMAT_FILE = join(ROOT, 'lib/format.ts');
const SPANISH_CONSTANTS = new Set(['NA', 'NO_CORRIDO', 'FORMAT_LOCALE']);
const SERVER_ACTION = /^\s*(?:\/\/[^\n]*\n|\/\*[\s\S]*?\*\/\s*)*['"]use server['"]/;
const TRANSLATED = /\b(?:useT|getT|useFormat|getFormat)\s*\(/;

type SourceMap = Map<string, string>; // ruta absoluta → texto

function localeParamIndex(formatText: string): Map<string, number> {
  const sf = ts.createSourceFile(FORMAT_FILE, formatText, ts.ScriptTarget.Latest, true);
  const out = new Map<string, number>();
  sf.forEachChild((node) => {
    if (!ts.isFunctionDeclaration(node) || !node.name) return;
    const index = node.parameters.findIndex((p) => ts.isIdentifier(p.name) && p.name.text === 'locale');
    if (index >= 0) out.set(node.name.text, index);
  });
  return out;
}

function walk(dir: string, ext: string, out: string[] = []): string[] {
  if (!existsSync(dir)) return out;
  for (const entry of readdirSync(dir)) {
    if (entry === 'node_modules' || entry.startsWith('.')) continue;
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) walk(path, ext, out);
    else if (path.endsWith(ext) && !path.endsWith('.d.ts') && !/\.test\.tsx?$/.test(path)) out.push(path);
  }
  return out;
}

function resolveImport(spec: string, from: string, sources: SourceMap): string | null {
  const base = spec.startsWith('@/') ? join(ROOT, spec.slice(2)) : spec.startsWith('.') ? resolve(dirname(from), spec) : null;
  if (!base) return null;
  for (const candidate of [base, `${base}.ts`, `${base}.tsx`, join(base, 'index.ts')]) {
    if (sources.has(candidate)) return candidate;
  }
  return null;
}

type Imported = Map<string, { file: string; name: string }>;

function importsOf(sf: ts.SourceFile, file: string, sources: SourceMap): Imported {
  const out: Imported = new Map();
  sf.forEachChild((node) => {
    if (!ts.isImportDeclaration(node) || !ts.isStringLiteral(node.moduleSpecifier) || node.importClause?.isTypeOnly) return;
    const target = resolveImport(node.moduleSpecifier.text, file, sources);
    const bindings = node.importClause?.namedBindings;
    if (!target || !bindings || !ts.isNamedImports(bindings)) return;
    for (const element of bindings.elements) {
      if (!element.isTypeOnly) out.set(element.name.text, { file: target, name: (element.propertyName ?? element.name).text });
    }
  });
  return out;
}

function takesLocale(fn: ts.SignatureDeclarationBase): boolean {
  return fn.parameters.some((p) => {
    if (ts.isIdentifier(p.name) && /locale|lang/i.test(p.name.text)) return true;
    if (ts.isObjectBindingPattern(p.name)) {
      return p.name.elements.some((e) => ts.isIdentifier(e.name) && /locale|lang/i.test(e.name.text));
    }
    return Boolean(p.type && /\bLocale\b|'en'|"en"/.test(p.type.getText()));
  });
}

type Fn = { file: string; name: string; node: ts.FunctionLikeDeclaration; sf: ts.SourceFile; imports: Imported; locale: boolean };

function topLevelFunctions(sf: ts.SourceFile, file: string, imports: Imported): Fn[] {
  const out: Fn[] = [];
  const add = (name: string, node: ts.FunctionLikeDeclaration) => out.push({ file, name, node, sf, imports, locale: takesLocale(node) });
  sf.forEachChild((node) => {
    if (ts.isFunctionDeclaration(node) && node.name && node.body) add(node.name.text, node);
    if (ts.isVariableStatement(node)) {
      for (const decl of node.declarationList.declarations) {
        const init = decl.initializer;
        if (ts.isIdentifier(decl.name) && init && (ts.isArrowFunction(init) || ts.isFunctionExpression(init))) add(decl.name.text, init);
      }
    }
  });
  return out;
}

const key = (file: string, name: string) => `${file}#${name}`;

/** Analiza lib/ + los .tsx dados. Devuelve las infracciones de las reglas A y B. */
export function findLibLocaleLeaks(sources: SourceMap, tsxFiles: string[]): string[] {
  const formatText = sources.get(FORMAT_FILE);
  if (formatText === undefined) throw new Error('lib/format.ts no encontrado');
  const localeIndex = localeParamIndex(formatText);
  const fns = new Map<string, Fn>();
  for (const [file, text] of sources) {
    if (file === FORMAT_FILE || !file.endsWith('.ts') || SERVER_ACTION.test(text)) continue;
    const sf = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true);
    const imports = importsOf(sf, file, sources);
    for (const fn of topLevelFunctions(sf, file, imports)) fns.set(key(file, fn.name), fn);
  }
  const lineOf = (sf: ts.SourceFile, node: ts.Node) => sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1;
  const callee = (fn: { file: string; imports: Imported }, name: string): string => {
    const imported = fn.imports.get(name);
    return imported ? key(imported.file, imported.name) : key(fn.file, name);
  };
  /** Formateador de lib/format.ts llamado sin locale. */
  const unlocalizedFormatter = (fn: { imports: Imported }, call: ts.CallExpression): string | null => {
    if (!ts.isIdentifier(call.expression)) return null;
    const imported = fn.imports.get(call.expression.text);
    if (!imported || imported.file !== FORMAT_FILE) return null;
    const index = localeIndex.get(imported.name);
    return index !== undefined && call.arguments.length <= index ? imported.name : null;
  };

  // Motivo directo por el que un helper SIN locale formatea en castellano.
  const spanish = new Map<string, string>();
  for (const [id, fn] of fns) {
    if (fn.locale) continue;
    let reason: string | null = null;
    const visit = (node: ts.Node): void => {
      if (reason) return;
      if (ts.isCallExpression(node)) {
        const formatter = unlocalizedFormatter(fn, node);
        if (formatter) reason = `${formatter}() sin locale`;
      } else if (ts.isStringLiteral(node) && node.text === 'es-ES') {
        reason = "'es-ES' fijo";
      } else if (ts.isIdentifier(node) && !ts.isImportSpecifier(node.parent)) {
        const imported = fn.imports.get(node.text);
        if (imported?.file === FORMAT_FILE && SPANISH_CONSTANTS.has(imported.name)) reason = `${imported.name} fijo`;
      }
      ts.forEachChild(node, visit);
    };
    visit(fn.node.body ?? fn.node);
    if (reason) spanish.set(id, reason);
  }
  // Cadena: un helper sin locale que llama a otro que formatea en castellano.
  for (let changed = true; changed; ) {
    changed = false;
    for (const [id, fn] of fns) {
      if (fn.locale || spanish.has(id)) continue;
      let via: string | null = null;
      const visit = (node: ts.Node): void => {
        if (via) return;
        if (ts.isCallExpression(node) && ts.isIdentifier(node.expression)) {
          const target = callee(fn, node.expression.text);
          if (target !== id && spanish.has(target)) via = `vía ${node.expression.text}()`;
        }
        ts.forEachChild(node, visit);
      };
      visit(fn.node.body ?? fn.node);
      if (via) {
        spanish.set(id, via);
        changed = true;
      }
    }
  }

  const hits: string[] = [];
  // Regla A: helper con locale que lo pierde al llamar a un formateador.
  for (const fn of fns.values()) {
    if (!fn.locale) continue;
    const visit = (node: ts.Node): void => {
      if (ts.isCallExpression(node)) {
        const formatter = unlocalizedFormatter(fn, node);
        if (formatter) hits.push(`${relative(ROOT, fn.file)}:${lineOf(fn.sf, node)} ${fn.name}() recibe locale y llama a ${formatter}() sin él`);
      }
      ts.forEachChild(node, visit);
    };
    visit(fn.node.body ?? fn.node);
  }
  // Regla B: componente traducido que llama a un helper en castellano fijo.
  for (const file of tsxFiles) {
    const text = sources.get(file) ?? readFileSync(file, 'utf8');
    if (!TRANSLATED.test(text)) continue;
    const sf = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
    const imports = importsOf(sf, file, sources);
    const visit = (node: ts.Node): void => {
      if (ts.isCallExpression(node) && ts.isIdentifier(node.expression)) {
        const imported = imports.get(node.expression.text);
        const reason = imported && imported.file !== FORMAT_FILE ? spanish.get(key(imported.file, imported.name)) : undefined;
        if (imported && reason) {
          hits.push(`${relative(ROOT, file)}:${lineOf(sf, node)} llama a ${imported.name}() de ${relative(ROOT, imported.file)}, que formatea en castellano (${reason}) y no acepta locale`);
        }
      }
      ts.forEachChild(node, visit);
    };
    visit(sf);
  }
  return hits;
}

function repoSources(): { sources: SourceMap; tsx: string[] } {
  const sources: SourceMap = new Map();
  for (const file of walk(join(ROOT, 'lib'), '.ts')) sources.set(file, readFileSync(file, 'utf8'));
  const tsx = ['app', 'components', 'lib'].flatMap((dir) => walk(join(ROOT, dir), '.tsx'));
  return { sources, tsx };
}

describe('helpers de lib/ con el idioma activo', () => {
  it('detecta las dos reglas (y la cadena entre helpers) y acepta las formas correctas', () => {
    const fake = (rel: string) => join(ROOT, rel);
    const sources: SourceMap = new Map([
      [FORMAT_FILE, readFileSync(FORMAT_FILE, 'utf8')],
      [fake('lib/__fake/es.ts'), [
        "import { formatMoney, NA } from '../format.ts';",
        "export function pct(v: number): string { return v.toLocaleString('es-ES') + ' %'; }",
        "export function cell(v: number | null): string { return v === null ? NA : formatMoney(v, 'EUR'); }",
        "export function median(v: number): string { return pct(v); }",
        "export function drops(v: number, locale: 'es' | 'en' = 'es'): string { return formatMoney(v, 'EUR'); }",
        "export function ok(v: number, locale: 'es' | 'en' = 'es'): string { return formatMoney(v, 'EUR', undefined, undefined, locale); }",
        "export function plain(v: number): string { return String(v); }",
      ].join('\n')],
      [fake('components/__Fake.tsx'), [
        "import { pct, cell, median, ok, plain } from '@/lib/__fake/es';",
        "export function F() { const t = useT(); return [pct(1), cell(null), median(2), ok(3, 'en'), plain(4)]; }",
      ].join('\n')],
    ]);
    const hits = findLibLocaleLeaks(sources, [fake('components/__Fake.tsx')]);
    assert.equal(hits.length, 4, hits.join('\n'));
    assert.ok(hits.some((h) => /drops\(\) recibe locale y llama a formatMoney\(\)/.test(h)));
    assert.ok(hits.some((h) => /llama a pct\(\).*'es-ES' fijo/.test(h)));
    assert.ok(hits.some((h) => /llama a cell\(\).*NA fijo/.test(h)));
    assert.ok(hits.some((h) => /llama a median\(\).*vía pct\(\)/.test(h)));
  });

  it('ningún helper de lib/ pierde el locale ni pinta en castellano en un componente traducido', () => {
    const { sources, tsx } = repoSources();
    const hits = findLibLocaleLeaks(sources, tsx);
    assert.deepEqual(hits, [], `Añade locale al helper y pásalo desde el componente:\n${hits.join('\n')}`);
  });
});
