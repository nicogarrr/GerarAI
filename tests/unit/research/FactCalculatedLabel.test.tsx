import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { FactCalculatedLabel } from '@/components/research/FactCalculatedLabel';
describe('FactCalculatedLabel shared by desktop and mobile provenance', () => {
 it('labels non-reported facts as calculated, including ESEF derivations', () => {
  expect(renderToStaticMarkup(<FactCalculatedLabel fact={{is_reported:false}} />)).toContain('Calculado');
 });
 it('does not label a reported fact as calculated', () => {
  expect(renderToStaticMarkup(<FactCalculatedLabel fact={{is_reported:true}} />)).toBe('');
 });
});
