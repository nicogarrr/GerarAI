import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
vi.mock('next/link',()=>({default:({children,...props}:React.AnchorHTMLAttributes<HTMLAnchorElement>)=><a {...props}>{children}</a>}));
// NewsEventsFlow usa getT(): sin cookie el locale es «es».
vi.mock('next/headers',()=>({cookies:async()=>({get:()=>undefined})}));
import { NewsEventsFlow } from '@/components/research/NewsEventsFlow';

// El flujo pintaba DOS árboles por evento: tarjetas móvil (<ul> md:hidden) y
// tabla escritorio (hidden md:block). Contrato (decisión de diseño,
// 2026-11-14): UNA tabla nativa responsiva (patrón #5653…#5667): un evento =
// una fila, con etiquetas móviles md:hidden por celda; caption, scope y la
// región de scroll con teclado se conservan.
const event=(id:number,over:Record<string,unknown>={})=>({
  id,ticker:'ASTS',date:'2026-10-24T19:00:00Z',title:`Titular ${id}`,source:`Fuente ${id}`,url:`https://x.example/${id}`,
  event_type:'earnings',materiality_score:5,impact_direction:'positive',requires_update:true,
  news_lane:'empresa',archive:false,...over,
});
const view=(props:React.ComponentProps<typeof NewsEventsFlow>)=>NewsEventsFlow(props);

describe('NewsEventsFlow responsivo (una fila por evento)',()=>{
 it('un evento = una fila (sin <ul> de tarjetas ni tabla duplicada)',async()=>{
  render(await view({events:[event(1),event(2)], hasMore:false, lane:'empresa', page:1, portfolioTickers:[], watchlistTickers:[]}));
  expect(screen.queryByRole('list')).not.toBeInTheDocument();
  const table=screen.getByRole('table');
  // Cabecera + 2 eventos = 3 filas (antes: 3 en la tabla + 2 tarjetas <li>).
  expect(within(table).getAllByRole('row')).toHaveLength(3);
  // Cada titular aparece UNA vez (antes: tarjeta + tabla).
  expect(screen.getAllByText('Titular 1')).toHaveLength(1);
  expect(screen.getAllByText('Fuente 1')).toHaveLength(1);
 });
 it('la fila única conserva etiquetas móviles, badge de revisión y caption',async()=>{
  render(await view({events:[event(1)], hasMore:false, lane:'empresa', page:1, portfolioTickers:['ASTS'], watchlistTickers:[]}));
  const table=screen.getByRole('table');
  const rows=within(table).getAllByRole('row');
  for (const label of ['Ticker','Fecha','Titular','Materialidad','Estado y detalle']) {
    expect(within(rows[1]).getByText(label)).toBeInTheDocument();
  }
  expect(within(rows[1]).getAllByText('Revisar')).toHaveLength(1);
  expect(within(rows[1]).getByRole('link', { name: 'ASTS' })).toHaveAttribute('href', '/research/ASTS');
 });
 it('estado vacío una sola vez (sin div móvil aparte)',async()=>{
  render(await view({events:[], hasMore:false, lane:'empresa', page:1, portfolioTickers:[], watchlistTickers:[]}));
  expect(screen.getAllByText('Sin eventos de noticias todavía.')).toHaveLength(1);
 });
});
