import React from 'react';
import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { CompanyNavigation } from '@/components/research/CompanyNavigation';
import { MODULES, moduleHref } from '@/lib/research/research-views';
vi.mock('next/link', () => ({ default: ({ children, scroll, ...props }: React.ComponentProps<'a'> & { scroll?: boolean }) => <a data-scroll={scroll === undefined ? 'default' : String(scroll)} {...props}>{children}</a> }));
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
    expect(screen.getByTestId('decision-journal-entry')).toHaveAttribute('href', '/research/ASTS?view=changes#diario-decisiones');
    // agent-qa 28/10: con scroll={false} Next no baja al ancla y el usuario se
    // queda arriba, en «Qué ha cambiado», a ~4.000 px del diario.
    expect(screen.getByTestId('decision-journal-entry')).not.toHaveAttribute('data-scroll', 'false');
    expect(screen.getByTestId('decision-journal-entry').closest('details')).toBe(screen.getByText('Análisis avanzado').closest('details'));
    expect(screen.getByText('Análisis avanzado').closest('details')).not.toHaveAttribute('open');
  });

  it('conserva el scroll en pestañas ?view= y sube al inicio solo en subrutas', () => {
    // Auditoría v1.0 (2026-10-27): la expresión estaba invertida — las
    // pestañas de la misma página saltaban arriba (el bug de Nico del
    // 2026-10-19) y las subrutas se quedaban a media página.
    render(<CompanyNavigation ticker="ASTS" activeView="overview" />);
    // Módulo ?view= (misma página, otro query param): no resetea el scroll.
    expect(screen.getByRole('link', { name: /Vista general/ })).toHaveAttribute('href', '/research/ASTS?view=overview');
    expect(screen.getByRole('link', { name: /Vista general/ })).toHaveAttribute('data-scroll', 'false');
    expect(screen.getByRole('link', { name: /Tesis/ })).toHaveAttribute('href', '/research/ASTS?view=thesis');
    expect(screen.getByRole('link', { name: /Tesis/ })).toHaveAttribute('data-scroll', 'false');
    // Subruta propia (otra página): arranca arriba. Vive en el desplegable
    // "Análisis avanzado" (plegado aquí), así que se busca con hidden: true.
    const subroute = screen
      .getAllByRole('link', { hidden: true })
      .find((link) => link.getAttribute('href') === '/research/ASTS/share-capital');
    expect(subroute).toBeDefined();
    expect(subroute).toHaveAttribute('data-scroll', 'true');
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
