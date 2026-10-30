import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { LibrarySearchForm } from '@/components/knowledge/LibrarySearchForm';

describe('Biblioteca: formulario de búsqueda', () => {
  it('sin búsqueda es un GET a /knowledge sin «Quitar búsqueda» ni recuento', () => {
    render(<LibrarySearchForm query="" total={null} />);
    const form = screen.getByRole('search');
    expect(form).toHaveAttribute('action', '/knowledge');
    expect(form).toHaveAttribute('method', 'get');
    const input = screen.getByLabelText('Buscar en la biblioteca');
    expect(input).toHaveAttribute('name', 'q');
    expect(input).toHaveAttribute('type', 'search');
    expect(input).toHaveValue('');
    expect(screen.queryByRole('link', { name: 'Quitar búsqueda' })).not.toBeInTheDocument();
    expect(screen.queryByText(/coincide/)).not.toBeInTheDocument();
  });

  it('con búsqueda conserva el término y ofrece quitarla', () => {
    render(<LibrarySearchForm query="buffett" total={5} />);
    expect(screen.getByLabelText('Buscar en la biblioteca')).toHaveValue('buffett');
    expect(screen.getByRole('link', { name: 'Quitar búsqueda' })).toHaveAttribute('href', '/knowledge#documentos');
  });

  it('recuento en singular y plural, con formato español de miles', () => {
    const { unmount } = render(<LibrarySearchForm query="marks" total={1} />);
    expect(screen.getByText('1 documento coincide con «marks».')).toBeInTheDocument();
    unmount();
    render(<LibrarySearchForm query="marks" total={1234} />);
    expect(screen.getByText('1.234 documentos coinciden con «marks».')).toBeInTheDocument();
  });

  it('cero resultados ofrece buscar el mismo término en el texto completo, codificado', () => {
    render(<LibrarySearchForm query="ben graham" total={0} />);
    expect(screen.getByText(/Ningún documento coincide con «ben graham»/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Buscar «ben graham» dentro del texto' }))
      .toHaveAttribute('href', '/search?q=ben%20graham');
  });

  it('con total desconocido (null) no muestra recuento pero sí «Quitar búsqueda»', () => {
    render(<LibrarySearchForm query="buffett" total={null} />);
    expect(screen.getByRole('link', { name: 'Quitar búsqueda' })).toBeInTheDocument();
    expect(screen.queryByText(/coincide/)).not.toBeInTheDocument();
  });
});
