import {readFileSync} from 'node:fs';import {describe,it,expect} from 'vitest';
const src=(p:string)=>readFileSync(p,'utf8');
describe('secondary mobile controls',()=>{
 it('keeps filing and source destinations with44px controls',()=>{
  expect(src('app/(root)/research/[ticker]/filings/page.tsx')).toContain('inline-flex min-h-11 min-w-11');
  expect(src('app/(root)/research/sources/page.tsx')).toContain('className="h-11 rounded-lg');
  expect(src('app/(root)/research/sources/page.tsx')).toContain('min-h-11 min-w-11 items-center text-teal-300');
 });
 it('enlarges only interactive source, disclosure, portfolio and brain controls',()=>{
  for(const path of ['app/(root)/macro-calendar/page.tsx','app/(root)/ownership/page.tsx','app/(root)/cuellos/page.tsx','app/(root)/portfolio/stress/page.tsx','app/(root)/portfolio/intelligence/page.tsx','components/brain/GlobalBrain.tsx'])expect(src(path)).toContain('min-h-11');
  expect(src('components/brain/GlobalBrain.tsx')).toContain('min-h-11 bg-slate-950 border-slate-700');
 });
});
