import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
vi.mock('next/navigation', () => ({ useRouter: () => ({refresh:vi.fn()}) }));
vi.mock('@/lib/actions/portfolio.actions', () => ({ deleteTransaction: vi.fn() }));
vi.mock('@/components/portfolio/EditTransactionDialog', () => ({ default: () => null }));
vi.mock('@/components/portfolio/ImportIBKRButton', () => ({ default: () => null }));
vi.mock('@/components/calendar/CompanyLogo', () => ({CompanyLogo:()=>null}));
import PortfolioTransactions from '@/components/portfolio/PortfolioTransactions';
const tx={_id:'201',symbol:'OLD',type:'buy' as const,quantity:3,price:10,date:'2020-01-01',currency:'EUR'};
describe('transaction history page navigation',()=>{
 it('shows actual total and access to earlier rows without implying recent-only history',()=>{
  render(<PortfolioTransactions transactions={[tx]} userId="one" page={{total:201,offset:200}}/>);
  expect(screen.getByText('Historial de movimientos')).toBeInTheDocument();
  expect(screen.getByText('201-201 de 201')).toBeInTheDocument();
  expect(screen.getByRole('link',{name:'Anteriores'})).toHaveAttribute('href','/portfolio?tab=movimientos&transactionOffset=150');
  expect(screen.queryByRole('link',{name:'Siguientes'})).not.toBeInTheDocument();
 });
 it('offers older pages on a full first page and no previous link',()=>{
  render(<PortfolioTransactions transactions={[tx]} userId="one" page={{total:201,offset:0}}/>);
  expect(screen.getByRole('link',{name:'Siguientes'})).toHaveAttribute('href','/portfolio?tab=movimientos&transactionOffset=50');
  expect(screen.queryByRole('link',{name:'Anteriores'})).not.toBeInTheDocument();
 });
});
