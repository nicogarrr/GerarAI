import {renderToString} from 'react-dom/server';
import {act,render,screen,waitFor,fireEvent} from '@testing-library/react';
import {expect,it,vi} from 'vitest';
vi.mock('next/navigation',()=>({usePathname:()=>'/knowledge'}));
vi.mock('@/lib/actions/brain.actions',()=>({chatWithPortfolio:vi.fn()}));
vi.mock('@/lib/research/assistant-actions',()=>({askResearchAssistantAction:vi.fn()}));
vi.mock('@/lib/actions/knowledge-chat.actions',()=>({askKnowledge:vi.fn()}));
vi.mock('@/components/search/TickerSearchInput',()=>({TickerSearchInput:()=>null}));
import {LibraryChat} from '@/app/(root)/inversores/_components/LibraryChat';
import {GlobalBrain} from '@/components/brain/GlobalBrain';

// El panel es un chunk diferido: bajo carga (suite completa) tarda; plazos amplios.
// Nico (30-oct): en la Biblioteca el Cerebro sigue el patrón del resto de la
// app: pequeño abajo a la derecha, plegado, y se abre a demanda.
it('starts collapsed: no embedded panel, only the docked trigger, which asks the library',async()=>{
 Element.prototype.scrollTo=vi.fn();
 render(<><a href="/portfolio">Cartera</a><LibraryChat scope="letters" authors={['Buffett']}/><GlobalBrain userId="fixture"/></>);
 const trigger=await screen.findByRole('button',{name:'Abrir el cerebro'});
 await waitFor(()=>expect(trigger).toHaveAttribute('title','Pregunta a la biblioteca'));
 expect(screen.queryByRole('region',{name:'Cerebro GerarAI'})).toBeNull();
 expect(screen.queryByRole('dialog')).toBeNull();
 expect(document.body.style.overflow).not.toBe('hidden');
 fireEvent.click(trigger);
 const dialog=await screen.findByRole('dialog',{name:'Cerebro GerarAI'},{timeout:10000});
 expect(dialog).toHaveAttribute('aria-modal','true');
 expect(dialog).toHaveTextContent('Cartas · Doctrina, no datos actuales de empresas');
 fireEvent.click(screen.getByText('Autor y análisis'));
 expect(screen.getByLabelText('Autor')).toBeInTheDocument();
 fireEvent.click(screen.getByRole('button',{name:'Cerrar el cerebro'}));
 await waitFor(()=>expect(screen.queryByRole('dialog')).toBeNull());
},20000);

it('the page button and the BottomNav open the same floating panel with the library context',async()=>{
 Element.prototype.scrollTo=vi.fn();
 render(<><LibraryChat scope="library"/><GlobalBrain userId="fixture"/></>);
 await screen.findByRole('button',{name:'Abrir el cerebro'});
 fireEvent.click(screen.getByRole('button',{name:'Preguntar a la biblioteca'}));
 expect(await screen.findByRole('dialog',{name:'Cerebro GerarAI'},{timeout:10000})).toHaveTextContent('Biblioteca · Doctrina');
 fireEvent.click(screen.getByRole('button',{name:'Cerrar el cerebro'}));
 await waitFor(()=>expect(screen.queryByRole('dialog')).toBeNull());
 // BottomNav (móvil): evento sin detalle; conserva el contexto de la página.
 act(()=>{window.dispatchEvent(new Event('gerarai:open-brain'));});
 expect(await screen.findByRole('dialog',{name:'Cerebro GerarAI'},{timeout:10000})).toHaveTextContent('Biblioteca · Doctrina');
 await waitFor(()=>expect(screen.getAllByLabelText('Pregunta al cerebro')).toHaveLength(1));
},20000);

it('SSR carries no portal target or reserved panel height',()=>{
 const html=renderToString(<LibraryChat scope="library"/>);
 expect(html).not.toContain('brain-library-slot');
 expect(html).not.toContain('h-[min(780px,80dvh)]');
});
