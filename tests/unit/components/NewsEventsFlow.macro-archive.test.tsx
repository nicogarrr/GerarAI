import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
vi.mock('next/link',()=>({default:({children,...props}:React.AnchorHTMLAttributes<HTMLAnchorElement>)=><a {...props}>{children}</a>}));
// NewsEventsFlow usa getT(): sin cookie el locale es «es».
vi.mock('next/headers',()=>({cookies:async()=>({get:()=>undefined})}));
import { NewsEventsFlow } from '@/components/research/NewsEventsFlow';

const macroEvent=(id:number,archive:boolean,date:string)=>({
  id,ticker:null,date,title:`Evento macro ${id}`,source:'GDELT',url:`https://x.example/${id}`,
  event_type:'general_news',materiality_score:5,impact_direction:'neutral',requires_update:false,
  news_lane:'macro',archive,
});

const view=(props:React.ComponentProps<typeof NewsEventsFlow>)=>NewsEventsFlow(props);
describe('carril macro sin frescura',()=>{
 it('anuncia el archivo con la fecha real cuando todos los eventos son archive',async()=>{
  render(await view({events:[macroEvent(1,true,'2026-10-24T19:00:00Z'),macroEvent(2,true,'2026-10-23T10:00:00Z')], hasMore:false, lane:'macro', page:1, portfolioTickers:[], watchlistTickers:[]}));
  expect(screen.getByText(/no aporta datos nuevos desde el/)).toBeInTheDocument();
  expect(screen.getByText(/archivo reciente con su fecha real/)).toBeInTheDocument();
  const banner=screen.getByText(/archivo reciente con su fecha real/);
  expect(banner.textContent).toContain('24 oct 2026');
 });
 it('no anuncia archivo cuando hay frescura',async()=>{
  render(await view({events:[macroEvent(1,false,'2026-10-30T01:00:00Z')], hasMore:false, lane:'macro', page:1, portfolioTickers:[], watchlistTickers:[]}));
  expect(screen.queryByText(/archivo reciente/)).not.toBeInTheDocument();
 });
 it('estado vacío macro honesto: fuente caída, no error ni vacío genérico',async()=>{
  render(await view({events:[], hasMore:false, lane:'macro', page:1, portfolioTickers:[], watchlistTickers:[]}));
  // Tabla responsiva única (2026-11-14): el vacío se anuncia una sola vez.
  expect(screen.getAllByText('Sin eventos macro disponibles.')).toHaveLength(1);
  expect(screen.getAllByText(/La fuente macro no aporta datos nuevos ahora mismo/)).toHaveLength(1);
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
 });
});
