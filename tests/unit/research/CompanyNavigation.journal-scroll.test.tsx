import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const scrollToHashAnchor = vi.fn();
vi.mock('@/lib/search/scroll-to-hash', () => ({ scrollToHashAnchor: (...args: unknown[]) => scrollToHashAnchor(...args) }));
vi.mock('next/link', () => ({
  default: ({ children, scroll: _scroll, ...props }: React.ComponentProps<'a'> & { scroll?: boolean }) => {
    void _scroll;
    return <a {...props} onClick={(event) => { props.onClick?.(event); event.preventDefault(); }}>{children}</a>;
  },
}));

import { DecisionJournalEntryLink } from '@/components/research/DecisionJournalEntryLink';

// Suite E2E de flujos (28-oct-2026): con la página desplazada (siempre en
// móvil), el App Router cambiaba la URL a #diario-decisiones sin mover la
// vista. El enlace tiene que desplazar él mismo hasta el ancla. Desde la
// navegación de una fila (29-oct-2026) vive en el menú de cabecera y su
// ancla cuelga de la pestaña Seguimiento.
describe('«Diario de decisiones» en la ficha', () => {
  beforeEach(() => scrollToHashAnchor.mockClear());

  it('al pulsarlo desplaza la vista hasta #diario-decisiones', () => {
    render(<DecisionJournalEntryLink ticker="MSFT" />);
    const link = screen.getByTestId('decision-journal-entry');
    expect(link).toHaveAttribute('href', '/research/MSFT?view=seguimiento#diario-decisiones');
    fireEvent.click(link);
    expect(scrollToHashAnchor).toHaveBeenCalledWith('diario-decisiones');
  });

  it('cmd/ctrl-clic (nueva pestaña) no secuestra el scroll de esta', () => {
    render(<DecisionJournalEntryLink ticker="MSFT" />);
    fireEvent.click(screen.getByTestId('decision-journal-entry'), { metaKey: true });
    fireEvent.click(screen.getByTestId('decision-journal-entry'), { ctrlKey: true });
    expect(scrollToHashAnchor).not.toHaveBeenCalled();
  });
});
