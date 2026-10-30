import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { CompanyNavigation } from '@/components/research/CompanyNavigation';
import { TABS } from '@/lib/research/research-views';
vi.mock('next/link', () => ({ default: ({ children, scroll, ...props }: React.ComponentProps<'a'> & { scroll?: boolean }) => <a data-scroll={scroll === undefined ? 'default' : String(scroll)} {...props}>{children}</a> }));
describe('CompanyNavigation', () => {
  it('una sola fila con las seis pestañas, cada una a un toque', () => {
    render(<CompanyNavigation ticker="ASTS" activeView="overview" />);
    const nav = screen.getByTestId('company-navigation');
    const links = nav.querySelectorAll('a');
    expect(links).toHaveLength(6);
    expect([...links].map((link) => link.textContent)).toEqual(TABS.map((tab) => tab.label));
    // Destinos canónicos: el Resumen es la ficha desnuda; el resto ?view=.
    expect(screen.getByRole('link', { name: 'Resumen' })).toHaveAttribute('href', '/research/ASTS');
    expect(screen.getByRole('link', { name: 'Tesis' })).toHaveAttribute('href', '/research/ASTS?view=tesis');
    expect(screen.getByRole('link', { name: 'Finanzas' })).toHaveAttribute('href', '/research/ASTS?view=finanzas');
    expect(screen.getByRole('link', { name: 'Valoración' })).toHaveAttribute('href', '/research/ASTS?view=valoracion');
    expect(screen.getByRole('link', { name: 'Seguimiento' })).toHaveAttribute('href', '/research/ASTS?view=seguimiento');
    expect(screen.getByRole('link', { name: 'Fuentes' })).toHaveAttribute('href', '/research/ASTS?view=fuentes');
  });

  it('marca la pestaña activa, incluida cuando la vista es un módulo suyo', () => {
    const first = render(<CompanyNavigation ticker="ASTS" activeView="overview" />);
    expect(screen.getByRole('link', { name: 'Resumen' })).toHaveAttribute('aria-current', 'page');
    first.unmount();
    render(<CompanyNavigation ticker="ASTS" activeView="changes" />);
    expect(screen.getByRole('link', { name: 'Seguimiento' })).toHaveAttribute('aria-current', 'page');
  });

  it('todas las pestañas conservan el scroll (misma ruta, otro ?view=)', () => {
    render(<CompanyNavigation ticker="ASTS" activeView="overview" />);
    for (const tab of TABS) {
      expect(screen.getByRole('link', { name: tab.label })).toHaveAttribute('data-scroll', 'false');
    }
  });

  it('codifica el ticker en todos los destinos', () => {
    render(<CompanyNavigation ticker="BRK B" activeView="overview" />);
    expect(screen.getByRole('link', { name: 'Finanzas' })).toHaveAttribute('href', '/research/BRK%20B?view=finanzas');
    expect(screen.getByRole('link', { name: 'Resumen' })).toHaveAttribute('href', '/research/BRK%20B');
  });
});
