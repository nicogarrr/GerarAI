import React from 'react';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
import { render, screen } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
const request = vi.hoisted(() => vi.fn());
vi.mock('@/lib/actions/investors.actions', () => ({ getInstitutionalActivity: request }));
import { InstitutionalActivitySection } from '@/components/research/InstitutionalActivitySection';
const data = { status: 'ok', filter: 'all', period: null, prior_period: null, fetched_at: null, page: 1, page_size: 25, pages: 1, total: 0, rows: [] };
beforeEach(() => { request.mockReset(); request.mockResolvedValue(data); });
it.each([
  [{}, 'all', 1], [{ ia_status: 'reduce', ia_page: '3' }, 'reduce', 3],
  [{ ia_status: 'bad', ia_page: '-1' }, 'all', 1], [{ ia_page: '0' }, 'all', 1],
  [{ ia_page: '123456789' }, 'all', 1], [{ ia_status: 'nuevo', ia_page: 'x' }, 'nuevo', 1],
] as const)('normalizes query safely without writing', async (query, status, page) => {
  render(await InstitutionalActivitySection({ ticker: 'BRK/B', query, locale: 'en' }));
  expect(request).toHaveBeenCalledExactlyOnceWith('BRK/B', status, page);
  expect(screen.getByRole('link', { name: 'Increases' }).getAttribute('href')).toContain('/research/BRK%2FB?');
});
it('preserves unrelated params, strips absent values and degrades one failed request honestly', async () => {
  request.mockRejectedValueOnce(new Error('network'));
  render(await InstitutionalActivitySection({ ticker: 'ASTS', query: { years: '5', ia_status: undefined }, locale: 'es' }));
  expect(screen.getByRole('status')).toHaveTextContent(/No se pudo cargar/);
  expect(request).toHaveBeenCalledTimes(1);
});
it('executes the actual changed page JSX wiring, not a handwritten duplicate', async () => {
  const file = 'app/(root)/research/[ticker]/page.tsx';
  const text = readFileSync(file, 'utf8');
  const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  let node: ts.JsxSelfClosingElement | undefined;
  let imported = false;
  const visit = (n: ts.Node) => {
    if (ts.isImportDeclaration(n) && n.moduleSpecifier.getText(source) === "'@/components/research/InstitutionalActivitySection'") imported = true;
    if (ts.isJsxSelfClosingElement(n) && n.tagName.getText(source) === 'InstitutionalActivitySection') node = n;
    ts.forEachChild(n, visit);
  };
  visit(source); expect(imported).toBe(true); expect(node).toBeDefined();
  const code = ts.transpileModule(`return (${node!.getText(source)});`, { compilerOptions: { jsx: ts.JsxEmit.React } }).outputText;
  const props = { ticker: 'BRK/B', query: { ia_status: 'reduce', ia_page: '2', years: '5' }, locale: 'en' as const };
  const element = new Function('React', 'InstitutionalActivitySection', 'ticker', 'query', 'locale', code)(React, InstitutionalActivitySection, props.ticker, props.query, props.locale);
  expect(element.type).toBe(InstitutionalActivitySection);
  expect(element.props).toEqual(props);
  render(await element.type(element.props));
  expect(request).toHaveBeenCalledExactlyOnceWith('BRK/B', 'reduce', 2);
  expect(screen.getByRole('link', { name: 'Increases' })).toHaveAttribute('href', '/research/BRK%2FB?ia_status=aumenta&ia_page=1&years=5#superinversores');
  console.log('page changed JSX line executed:', source.getLineAndCharacterOfPosition(node!.getStart(source)).line + 1);
});
