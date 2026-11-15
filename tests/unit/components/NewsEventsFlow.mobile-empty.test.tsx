import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
vi.mock('next/link',()=>({default:({children,...props}:React.AnchorHTMLAttributes<HTMLAnchorElement>)=><a {...props}>{children}</a>}));
// NewsEventsFlow usa getT(): sin cookie el locale es «es».
vi.mock('next/headers',()=>({cookies:async()=>({get:()=>undefined})}));
import { NewsEventsFlow } from '@/components/research/NewsEventsFlow';
const view=(props:React.ComponentProps<typeof NewsEventsFlow>)=>NewsEventsFlow(props);
describe('mobile empty news',()=>{
 it('explains an empty lane in the single responsive table without claiming an error',async()=>{
  render(await view({events:[], hasMore:false, lane:'gobierno', page:1, portfolioTickers:[], watchlistTickers:[]}));
  // Tabla responsiva única (2026-11-14): el vacío vive en la fila única, una vez.
  expect(screen.getAllByText('Sin eventos de noticias todavía.')).toHaveLength(1);
  expect(screen.getAllByText('Este carril todavía no tiene noticias disponibles.')).toHaveLength(1);
  expect(screen.getByRole('link', { name: 'Importa una fuente o analiza una noticia manual' })).toHaveAttribute('href','/research/sources');
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
 });
});
