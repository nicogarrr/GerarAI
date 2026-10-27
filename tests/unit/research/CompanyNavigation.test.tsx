import React from 'react';
import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { CompanyNavigation } from '@/components/research/CompanyNavigation';
import { MODULES, moduleHref } from '@/lib/research/research-views';
vi.mock('next/link', () => ({ default: ({ children, scroll: _scroll, ...props }: React.ComponentProps<'a'> & { scroll?: boolean }) => <a {...props}>{children}</a> }));
describe('CompanyNavigation', () => {
  it('keeps all nineteen module destinations available and the journal compact', () => {
    render(<CompanyNavigation ticker="ASTS" activeView="overview" />);
    const links = screen.getAllByRole('link', { hidden: true });
    const hrefs = links.map((link) => link.getAttribute('href'));
    // Primary groups expose their own modules when selected; collect each group.
    for (const view of ['financials', 'documents'] as const) {
      const other = render(<CompanyNavigation ticker="ASTS" activeView={view} />);
      hrefs.push(...within(other.container).getAllByRole('link', { hidden: true }).map((link) => link.getAttribute('href')));
      other.unmount();
    }
    for (const item of MODULES) expect(hrefs).toContain(moduleHref('ASTS', item));
    expect(screen.getByText('Diario de decisiones')).toHaveAttribute('href', '/research/ASTS?view=changes#diario-decisiones');
    expect(screen.getByText('Análisis avanzado').closest('details')).not.toHaveAttribute('open');
  });
  it('opens advanced navigation for an active specialist module', () => {
    render(<CompanyNavigation ticker="ASTS" activeView="holders" />);
    expect(screen.getByText('Análisis avanzado').closest('details')).toHaveAttribute('open');
    expect(screen.getByRole('link', { name: /Superinversores/ })).toHaveAttribute('aria-current', 'page');
  });
  it('only shows orbital tools for ASTS and preserves encoded ticker destinations', () => {
    render(<CompanyNavigation ticker="BRK B" activeView="overview" />);
    expect(screen.queryByText('Satélites AST')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Finanzas' })).toHaveAttribute('href', '/research/BRK%20B?view=financials');
    expect(screen.getByText('Diario de decisiones')).toHaveAttribute('href', '/research/BRK%20B?view=changes#diario-decisiones');
  });
});
