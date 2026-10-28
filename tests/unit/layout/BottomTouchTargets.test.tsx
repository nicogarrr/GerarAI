import React from 'react';
import {fireEvent,render,screen} from '@testing-library/react';
import {describe,it,expect,vi} from 'vitest';
import {readFileSync} from 'node:fs';
import BottomNav from '@/components/layout/BottomNav';
vi.mock('next/navigation',()=>({usePathname:()=>'/portfolio'}));
vi.mock('next/link',()=>({default:({children,...p}:React.ComponentProps<'a'>)=><a {...p}>{children}</a>}));
describe('compact mobile targets',()=>{
 it('preserves all six destinations and brain action',()=>{
  render(<BottomNav/>);expect(screen.getAllByRole('link')).toHaveLength(5);
  expect(screen.getByText('Research')).toBeVisible();
  const spy=vi.fn();window.addEventListener('gerarai:open-brain',spy);fireEvent.click(screen.getByRole('button',{name:'Abrir el cerebro'}));expect(spy).toHaveBeenCalledOnce();window.removeEventListener('gerarai:open-brain',spy);
 });
 it('keeps controls at44px and wraps chart ranges rather than overflowing',()=>{
  const source=(p:string)=>readFileSync(p,'utf8');
  expect(source('app/(root)/temas/page.tsx')).toContain('min-h-11 min-w-11');
  expect(source('components/paper-trading/ManualDemoPanel.tsx').match(/TabsTrigger className="min-h-11"/g)).toHaveLength(4);
  for(const n of ['OrderTicket','FxTicket'])expect(source(`components/paper-trading/${n}.tsx`)).toContain('style={{ minHeight: 44 }}');
  expect(source('components/research/CompanyTechnicalChart.tsx')).toContain('min-h-11 min-w-11');
  expect(source('components/portfolio/PortfolioTabs.tsx')).toContain('min-h-[44px] min-w-11');
 });
});
