import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';
import ts from 'typescript';

function violations(text, file = 'fixture.ts') {
  const src = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true);
  if (!src.statements.some(s => ts.isExpressionStatement(s) && ts.isStringLiteral(s.expression) && s.expression.text === 'use server')) return [];
  const has = (s, kind) => s.modifiers?.some(m => m.kind === kind);
  const asyncFn = s => (ts.isArrowFunction(s) || ts.isFunctionExpression(s) || ts.isFunctionDeclaration(s)) && has(s, ts.SyntaxKind.AsyncKeyword);
  const callable = s => asyncFn(s) || (ts.isCallExpression(s) && s.expression.getText(src) === 'cache' && s.arguments.length === 1 && asyncFn(s.arguments[0]));
  const bad = [];
  for (const s of src.statements) {
    if (ts.isExportDeclaration(s)) {
      if (!s.isTypeOnly && !(s.exportClause && ts.isNamedExports(s.exportClause) && s.exportClause.elements.every(e => e.isTypeOnly))) bad.push(s.getText(src));
      continue;
    }
    if (!has(s, ts.SyntaxKind.ExportKeyword)) continue;
    if (ts.isTypeAliasDeclaration(s) || ts.isInterfaceDeclaration(s)) continue;
    if (ts.isFunctionDeclaration(s) && asyncFn(s)) continue;
    if (ts.isVariableStatement(s) && s.declarationList.declarations.every(d => d.initializer && callable(d.initializer))) continue;
    bad.push(s.getText(src));
  }
  return bad;
}
function files(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap(e => e.isDirectory() ? files(join(dir, e.name)) : /\.[cm]?[jt]sx?$/.test(e.name) ? [join(dir, e.name)] : []);
}
test('use server modules export only async functions, never runtime arrays or objects', () => {
  const scanned = ['app', 'lib', 'components'].flatMap(files);
  assert.ok(scanned.length > 100);
  const bad = scanned.flatMap(file => violations(readFileSync(file, 'utf8'), file).map(value => `${file}: ${value.slice(0, 120)}`));
  assert.deepEqual(bad, []);
});
test('guard catches runtime exports but permits erased types and async actions', () => {
  for (const value of ['export const TYPES = [1];', 'export const state = {};', 'export function sync() {}', 'export class Foo {}', 'export { value };', 'export * from "x";']) assert.equal(violations(`'use server'; ${value}`).length, 1, value);
  assert.deepEqual(violations(`'use server'; export type T = string; export interface I {} export async function f() {} export const g = async () => {}; export const h = cache(async () => 1); export type { A } from 'x';`), []);
});
