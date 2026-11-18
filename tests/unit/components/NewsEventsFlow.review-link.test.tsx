import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
vi.mock('next/link',()=>({default:({children,...props}:React.AnchorHTMLAttributes<HTMLAnchorElement>)=><a {...props}>{children}</a>}));
// NewsEventsFlow usa getT(): sin cookie el locale es «es».
vi.mock('next/headers',()=>({cookies:async()=>({get:()=>undefined})}));
import { NewsEventsFlow } from '@/components/research/NewsEventsFlow';
import type { ResearchNewsEvent } from '@/lib/actions/research.actions';

const view=(props:React.ComponentProps<typeof NewsEventsFlow>)=>NewsEventsFlow(props);

const materialEvent=(id:number,ticker:string|null,requiresUpdate=true):ResearchNewsEvent=>({
  id,ticker,date:'2026-11-17T10:00:00Z',title:`Noticia material ${id}`,source:'GDELT',
  url:`https://x.example/${id}`,event_type:'earnings',materiality_score:8,
  impact_direction:'negative',requires_update:requiresUpdate,
});

describe('noticia material → cambio de tesis',()=>{
 it('con ticker, «Revisar» enlaza al seguimiento de la ficha en la tabla responsiva',async()=>{
  render(await view({events:[materialEvent(1,'ASTS')],hasMore:false,lane:null,page:1,portfolioTickers:[],watchlistTickers:[]}));
  // Tras la tabla responsiva única, móvil y escritorio comparten la misma celda.
  const links=screen.getAllByRole('link',{name:/Revisar/});
  expect(links).toHaveLength(1);
  for(const link of links) expect(link).toHaveAttribute('href','/research/ASTS?view=seguimiento');
 });
 it('sin ticker conserva el badge «Revisar» pero no inventa destino',async()=>{
  const {container}=render(await view({events:[materialEvent(2,null)],hasMore:false,lane:null,page:1,portfolioTickers:[],watchlistTickers:[]}));
  expect(screen.queryByRole('link',{name:/Revisar/})).not.toBeInTheDocument();
  expect(container.querySelector('a[href*="view=seguimiento"]')).toBeNull();
  const badges=screen.getAllByText('Revisar');
  expect(badges).toHaveLength(1);
  for(const badge of badges) expect(badge.tagName).toBe('SPAN');
 });
 it('sin requires_update no aparece el badge',async()=>{
  render(await view({events:[materialEvent(3,'ASTS',false)],hasMore:false,lane:null,page:1,portfolioTickers:[],watchlistTickers:[]}));
  expect(screen.queryByText('Revisar')).not.toBeInTheDocument();
 });
});
