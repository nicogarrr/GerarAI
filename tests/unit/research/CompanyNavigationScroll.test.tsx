import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { beforeAll, describe, expect, it, vi } from 'vitest';
import { CompanyNavigationScroll } from '@/components/research/CompanyNavigationScroll';

// jsdom no implementa scrollIntoView: se espía para verificar la llamada.
beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn();
});

function Nav({ active }: { active: 'resumen' | 'seguimiento' }) {
  return (
    <nav data-testid="company-navigation" className="scrollbar-hide overflow-x-auto">
      <CompanyNavigationScroll />
      <a aria-current={active === 'resumen' ? 'page' : undefined} href="#summary">Resumen</a>
      <a aria-current={active === 'seguimiento' ? 'page' : undefined} href="#follow-up">Seguimiento</a>
    </nav>
  );
}

describe('CompanyNavigationScroll', () => {
  it('centra la pestaña activa al montar y al cambiar de vista (misma ruta, scroll conservado)', async () => {
    const spy = vi.mocked(Element.prototype.scrollIntoView);
    spy.mockClear();
    const { rerender } = render(<Nav active="resumen" />);
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    expect(spy).toHaveBeenLastCalledWith({ block: 'nearest', inline: 'nearest' });

    // Navegación Resumen -> Seguimiento: el enlace activo cambia sin remontar.
    spy.mockClear();
    rerender(<Nav active="seguimiento" />);
    await waitFor(() => expect(spy).toHaveBeenCalled());
    const active = screen.getByRole('link', { name: 'Seguimiento' });
    expect(spy.mock.instances[0]).toBe(active);
  });
});
