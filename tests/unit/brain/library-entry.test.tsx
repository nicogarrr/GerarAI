import {renderToString} from 'react-dom/server';
import {render,screen,waitFor,fireEvent} from '@testing-library/react';
import {expect,it,vi} from 'vitest';
vi.mock('next/navigation',()=>({usePathname:()=>'/knowledge'}));
vi.mock('@/lib/actions/brain.actions',()=>({chatWithPortfolio:vi.fn()}));
vi.mock('@/lib/research/assistant-actions',()=>({askResearchAssistantAction:vi.fn()}));
vi.mock('@/lib/actions/knowledge-chat.actions',()=>({askKnowledge:vi.fn()}));
vi.mock('@/components/search/TickerSearchInput',()=>({TickerSearchInput:()=>null}));
import {LibraryChat} from '@/app/(root)/inversores/_components/LibraryChat';
import {GlobalBrain} from '@/components/brain/GlobalBrain';
it('one embedded region, no modal, close, trigger, focus trap or body lock',async()=>{
 Element.prototype.scrollTo=vi.fn();
 render(<><a href="/portfolio">Cartera</a><LibraryChat scope="letters" authors={['Buffett']}/><GlobalBrain userId="fixture"/></>);
 const region=await screen.findByRole('region',{name:'Cerebro GerarAI'});
 expect(region).not.toHaveAttribute('aria-modal');
 expect(screen.queryByRole('dialog')).toBeNull();
 expect(screen.queryByRole('button',{name:'Cerrar el cerebro'})).toBeNull();
 expect(screen.queryByRole('button',{name:'Preguntar al Cerebro'})).toBeNull();
 expect(document.body.style.overflow).not.toBe('hidden');
 expect(screen.getByRole('link',{name:'Cartera'}).closest('[inert]')).toBeNull();
 fireEvent.click(screen.getByText('Autor y análisis'));
 expect(screen.getByLabelText('Autor')).toBeInTheDocument();
 await waitFor(()=>expect(screen.getAllByLabelText('Pregunta al cerebro')).toHaveLength(1));
});

it('does not emit a portal target in SSR before the page has hydrated',()=>{
 // El SSR trae solo el contenedor con el alto reservado y el esqueleto (CLS),
 // nunca el hueco del portal.
 expect(renderToString(<LibraryChat scope="library"/>)).not.toContain('brain-library-slot');
});
