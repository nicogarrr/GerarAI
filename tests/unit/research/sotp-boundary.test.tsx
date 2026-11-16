import React, { Suspense } from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';
import { expect, it } from 'vitest';
import fs from 'node:fs';
import ts from 'typescript';
import { SotpBreakdownSkeleton } from '@/components/research/SotpBreakdownSkeleton';

it('executes the actual page boundary while SOTP suspends, then replaces the skeleton', async () => {
  // Compile the unmodified JSX boundary from the page, not a handwritten copy.
  // This executes only this subtree, not the rest of the server page or its data calls.
  const file = 'app/(root)/research/[ticker]/page.tsx';
  const source = ts.createSourceFile(file, fs.readFileSync(file, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  let boundary: ts.JsxElement | undefined;
  const visit = (node: ts.Node) => {
    if (ts.isJsxElement(node) && node.openingElement.tagName.getText(source) === 'Suspense' &&
        node.children.some(child => ts.isJsxSelfClosingElement(child) && child.tagName.getText(source) === 'SotpBreakdownSection')) boundary = node;
    ts.forEachChild(node, visit);
  };
  visit(source);
  expect(boundary).toBeDefined();
  const javascript = ts.transpileModule(`return (${boundary!.getText(source)});`, {
    compilerOptions: { jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  let finish!: (value: string) => void;
  const pending = new Promise<string>(resolve => { finish = resolve; });
  let loaded = false;
  const requests: Array<{ ticker: string; variant: string }> = [];
  function SotpBreakdownSection(props: { ticker: string; variant: string }) {
    requests.push(props);
    if (!loaded) throw pending;
    return <p>SOTP loaded</p>;
  }
  const build = new Function('React', 'Suspense', 'SotpBreakdownSkeleton', 'SotpBreakdownSection', 'ticker', 'query', 'sotpVariantParam', javascript);
  const element = build(React, Suspense, SotpBreakdownSkeleton, SotpBreakdownSection, 'BRK/B', { sotp: 'agents' }, (value: string) => value);
  const { container } = render(element);
  expect(container.querySelector('section[aria-hidden="true"]')).not.toBeNull();
  expect(screen.queryByText('SOTP loaded')).toBeNull();
  await act(async () => { loaded = true; finish('SOTP loaded'); await pending; });
  await waitFor(() => expect(screen.getByText('SOTP loaded')).toBeTruthy());
  expect(container.querySelector('section[aria-hidden="true"]')).toBeNull();
  expect(requests.every(props => props.ticker === 'BRK/B' && props.variant === 'agents')).toBe(true);
});
