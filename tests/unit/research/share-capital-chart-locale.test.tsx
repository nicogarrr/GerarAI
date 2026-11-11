import { render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { LocaleProvider } from '@/lib/i18n/client';
import Chart from '@/components/research/ShareCapitalChart';
let y:Record<string,unknown>, x:Record<string,unknown>, tooltip:Record<string,unknown>;
vi.mock('recharts',()=>({
 ResponsiveContainer:({children}:{children:ReactNode})=><div>{children}</div>,
 LineChart:({children}:{children:ReactNode})=><div>{children}</div>,
 CartesianGrid:()=>null,Line:()=>null,
 XAxis:(props:Record<string,unknown>)=>{x=props;return null;},
 YAxis:(props:Record<string,unknown>)=>{y=props;return null;},
 Tooltip:(props:Record<string,unknown>)=>{tooltip=props;return null;},
}));
describe('share capital chart locale',()=>{
 it.each(['es','en'] as const)('%s translates shares and uses the locale formatters',locale=>{
 render(<LocaleProvider locale={locale}><Chart series={[]}/></LocaleProvider>);
 const formatter=tooltip.formatter as (value:number)=>[string,string];
 expect(formatter(1234.5)[1]).toBe(locale==='en'?'Shares':'Acciones');
 expect(formatter(1234.5)[0]).toContain(locale==='en'?'1.23':'1,23');
 expect((y.tickFormatter as (value:number)=>string)(1234.5)).toContain(locale==='en'?'1.23':'1,23');
 expect((tooltip.labelFormatter as (value:string)=>string)('2026-08-01')).toContain(locale==='en'?'Aug':'ago');
 expect((x.tickFormatter as (value:string)=>string)('2026-08-01')).toContain(locale==='en'?'Aug':'ago');
 });
});
