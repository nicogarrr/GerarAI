import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
vi.mock('next/link',()=>({default:({children,...props}:React.AnchorHTMLAttributes<HTMLAnchorElement>)=><a {...props}>{children}</a>}));
import { NewsEventsFlow } from '@/components/research/NewsEventsFlow';
describe('mobile empty news',()=>{
 it('explains an empty lane outside the hidden desktop table without claiming an error',()=>{
  const {container}=render(<NewsEventsFlow events={[]} hasMore={false} lane="gobierno" page={1} portfolioTickers={[]} watchlistTickers={[]}/>);
  const mobile=container.querySelector('div.md\\:hidden');
  expect(mobile).toHaveTextContent('Sin eventos de noticias todavía.');
  expect(mobile).toHaveTextContent('Este carril todavía no tiene noticias disponibles.');
  expect(mobile?.querySelector('a')).toHaveAttribute('href','/research/sources');
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
 });
});
