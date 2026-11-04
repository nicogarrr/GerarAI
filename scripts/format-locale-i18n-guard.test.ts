/**
 * Guarda: un componente traducido (usa useT()/getT()) no puede formatear
 * cifras, fechas ni «N/D» con los formateadores sueltos de `@/lib/format`
 * sin pasarles el locale. Sin locale, esas funciones formatean SIEMPRE en
 * es-ES: con la app en inglés salían «4.100,00 €», «+87,2 %», «19 nov 2026»
 * o «N/D» junto a textos ya traducidos (#4501 arregló tres componentes; esta
 * guarda cierra la clase entera).
 *
 * Cómo arreglarlo: en cliente `const fmt = useFormat()` (lib/i18n/client), en
 * servidor `const fmt = await getFormat()` (lib/i18n/server), y usar
 * `fmt.formatMoney(...)`, `fmt.na`, etc. Pasar el locale a mano también vale.
 *
 * La posición del parámetro `locale` de cada formateador se lee de la propia
 * firma en lib/format.ts, así que un formateador nuevo queda cubierto solo.
 *
 * Ejecución: node --experimental-strip-types --test scripts/format-locale-i18n-guard.test.ts
 */
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { describe, it } from 'node:test';
import ts from 'typescript';

const ROOT = process.cwd();
const FORMAT_MODULE = '@/lib/format';
/** Constantes en castellano fijo: en un componente traducido van por fmt.na / fmt.noCorrido. */
const SPANISH_CONSTANTS = new Set(['NA', 'NO_CORRIDO']);

function localeParamIndex(): Map<string, number> {
  const path = join(ROOT, 'lib/format.ts');
  const sf = ts.createSourceFile(path, readFileSync(path, 'utf8'), ts.ScriptTarget.Latest, true);
  const out = new Map<string, number>();
  sf.forEachChild((node) => {
    if (!ts.isFunctionDeclaration(node) || !node.name) return;
    if (!node.modifiers?.some((m) => m.kind === ts.SyntaxKind.ExportKeyword)) return;
    const index = node.parameters.findIndex((param) => ts.isIdentifier(param.name) && param.name.text === 'locale');
    if (index >= 0) out.set(node.name.text, index);
  });
  return out;
}

function tsxFiles(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (name === 'node_modules' || name.startsWith('.')) continue;
    const path = join(dir, name);
    if (statSync(path).isDirectory()) tsxFiles(path, out);
    else if (path.endsWith('.tsx')) out.push(path);
  }
  return out;
}

/** Llamadas sin locale (y constantes en castellano) de un .tsx traducido. */
export function findUnlocalizedFormatting(text: string, fileName: string, localeIndex: Map<string, number>): string[] {
  if (!/\b(?:useT|getT)\s*\(/.test(text)) return [];
  const sf = ts.createSourceFile(fileName, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const imported = new Map<string, string>();
  sf.forEachChild((node) => {
    if (!ts.isImportDeclaration(node) || !ts.isStringLiteral(node.moduleSpecifier)) return;
    if (node.moduleSpecifier.text !== FORMAT_MODULE || node.importClause?.isTypeOnly) return;
    const bindings = node.importClause?.namedBindings;
    if (!bindings || !ts.isNamedImports(bindings)) return;
    for (const element of bindings.elements) {
      if (element.isTypeOnly) continue;
      imported.set(element.name.text, (element.propertyName ?? element.name).text);
    }
  });
  if (imported.size === 0) return [];
  const hits: string[] = [];
  const line = (node: ts.Node) => sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1;
  const visit = (node: ts.Node): void => {
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && imported.has(node.expression.text)) {
      const original = imported.get(node.expression.text)!;
      const index = localeIndex.get(original);
      if (index !== undefined && node.arguments.length <= index) hits.push(`${original}() sin locale, línea ${line(node)}`);
    } else if (
      ts.isIdentifier(node) &&
      imported.has(node.text) &&
      SPANISH_CONSTANTS.has(imported.get(node.text)!) &&
      !ts.isImportSpecifier(node.parent)
    ) {
      hits.push(`${imported.get(node.text)} en castellano fijo, línea ${line(node)}`);
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  return hits;
}

describe('formato con el idioma activo en componentes traducidos', () => {
  const localeIndex = localeParamIndex();

  it('lee la posición del locale de las firmas de lib/format.ts', () => {
    // Si estas firmas cambian de forma, la guarda debe seguir viéndolas.
    assert.equal(localeIndex.get('formatMoney'), 4);
    assert.equal(localeIndex.get('formatNumber'), 3);
    assert.equal(localeIndex.get('formatDate'), 3);
    assert.ok(localeIndex.size >= 15, `solo ${localeIndex.size} formateadores con locale`);
  });

  it('detecta el patrón (llamada sin locale, alias y NA) y acepta las formas correctas', () => {
    const bad = [
      "import { formatMoney as fm, NA, formatDate } from '@/lib/format';",
      "export function X() { const t = useT(); return [fm(1, 'EUR'), NA, formatDate(d, undefined, NA, 'en')]; }",
    ].join('\n');
    const hits = findUnlocalizedFormatting(bad, 'x.tsx', localeIndex);
    assert.equal(hits.length, 3, hits.join('; '));
    assert.match(hits[0], /^formatMoney\(\) sin locale/);
    const good = [
      "import { formatMoney } from '@/lib/format';",
      "export function X() { const t = useT(); const locale = useLocale(); const f = useFormat();",
      "  return [formatMoney(1, 'EUR', undefined, undefined, locale), f.formatMoney(2), f.na]; }",
    ].join('\n');
    assert.deepEqual(findUnlocalizedFormatting(good, 'y.tsx', localeIndex), []);
    // Sin useT/getT el componente no está traducido: fuera de esta guarda.
    assert.deepEqual(findUnlocalizedFormatting("import { NA } from '@/lib/format'; export const a = NA;", 'z.tsx', localeIndex), []);
  });

  it('ningún .tsx con useT/getT formatea en castellano fijo', () => {
    const offenders: string[] = [];
    for (const file of ['app', 'components', 'lib'].flatMap((dir) => tsxFiles(join(ROOT, dir)))) {
      const hits = findUnlocalizedFormatting(readFileSync(file, 'utf8'), file, localeIndex);
      if (hits.length) offenders.push(`${relative(ROOT, file)}: ${hits.join('; ')}`);
    }
    assert.deepEqual(offenders, [], `Usa useFormat()/getFormat() (o pasa el locale):\n${offenders.join('\n')}`);
  });
});
