import React from 'react';
import { readFileSync } from 'node:fs';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { Stat } from '@/components/ui/stat';

// Pase visual 390 px / 1280 px (30-oct). Sin layout real en jsdom, se fijan
// las clases que resuelven cada caso medido con Playwright.
describe('pase visual: cifras, tablas y columnas que no caben', () => {
  it('Stat sm: cifra más pequeña y menos padding en móvil para que «100.000,00 €» no parta el «€»', () => {
    render(<Stat label="Efectivo EUR" size="sm" value="100.000,00 €" />);
    const value = screen.getByText('100.000,00 €');
    expect(value.className).toContain('text-base');
    expect(value.className).toContain('sm:text-lg');
    expect(value.className).toContain('tabular-nums');
    expect(value.parentElement?.className).toContain('p-3');
    expect(value.parentElement?.className).toContain('sm:p-4');
  });

  it('Stat md conserva la cifra grande de cabecera', () => {
    render(<Stat label="Valor" value="1" />);
    const value = screen.getByText('1');
    expect(value.className).toContain('text-2xl');
    expect(value.parentElement?.className).toContain('p-4');
    expect(value.parentElement?.className).not.toContain('p-3');
  });

  it('Temas: la composición no se sale de la tarjeta en la rejilla de 2-3 columnas', () => {
    const source = readFileSync('app/(root)/temas/page.tsx', 'utf8');
    // «Aporta» dependía del ancho de ventana (sm:) y en la rejilla la tarjeta
    // mide ~315 px: la tabla (~360 px) pisaba la tarjeta vecina a 1280 px.
    expect(source).not.toMatch(/[\s"'`]sm:table-cell/);
    expect(source.match(/@sm:table-cell/g)).toHaveLength(2);
    const wrapper = source.indexOf('<div className="@container overflow-x-auto">');
    expect(wrapper).toBeGreaterThan(-1);
    expect(source.indexOf('<table className="w-full text-left text-xs">', wrapper)).toBeGreaterThan(wrapper);
  });

  it('Biblioteca: las tres cifras van en una fila también en móvil', () => {
    const source = readFileSync('app/(root)/knowledge/page.tsx', 'utf8');
    expect(source).toContain("<section aria-label={t('knowledge.statsAria')} className=\"grid grid-cols-3 gap-2 sm:gap-4\">");
    expect(source).not.toContain('grid grid-cols-1 gap-3 sm:grid-cols-3 sm:gap-4');
  });
});
