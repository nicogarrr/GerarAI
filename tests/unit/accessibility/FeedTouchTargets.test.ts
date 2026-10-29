import {readFileSync} from 'node:fs';
import {describe,it,expect} from 'vitest';
const read=(p:string)=>readFileSync(p,'utf8');
describe('feed mobile targets',()=>{
 it('gives news filter and paging targets44px without changing destinations',()=>{
  const s=read('components/research/NewsEventsFlow.tsx');expect(s).toContain("const PAGER_LINK = 'inline-flex min-h-11");expect(s).toContain('items-center rounded-full border px-4');expect(s).toContain('min-h-11 min-w-11');expect(s).toContain('newsPageHref(lane, target, ticker)');expect(s).toContain('href(page + 1)');
 });
 it('gives context, ticker and market tabs44px and scopes corporate list styling',()=>{
  expect(read('components/research/NewsSecondOrder.tsx')).toContain('min-h-11 cursor-pointer');expect(read('components/insider/InsiderFeed.tsx')).toContain('min-h-11 min-w-11');expect(read('components/markets/LiveMarketsPanel.tsx')).toContain('<TabsTrigger className="min-h-11"');expect(read('components/corporate-actions/CorporateActionsView.tsx')).toContain('[&_a.font-mono]:min-h-11');
 });
});
