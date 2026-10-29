import React from 'react';
import { act, render } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const scrollToHashAnchor = vi.fn();
vi.mock('@/lib/search/scroll-to-hash', () => ({ scrollToHashAnchor: (...args: unknown[]) => scrollToHashAnchor(...args) }));
vi.mock('next/navigation', () => ({
  usePathname: () => '/research/MSFT',
  useSearchParams: () => new URLSearchParams('view=changes'),
}));

import { ResearchHashScroll } from '@/components/research/ResearchHashScroll';

// Bug (29-oct-2026): «Revisar cambio» de Inicio y los enlaces a
// #diario-decisiones llegaban a la ficha sin scroll: el App Router no
// reintenta cuando el destino aún no existe (Suspense/datos async).
describe('ResearchHashScroll (ancla al llegar a la ficha)', () => {
  beforeEach(() => {
    scrollToHashAnchor.mockClear();
    window.location.hash = '';
  });

  it('al montar con ancla en la URL pide scroll a ese id con ventana amplia', () => {
    window.location.hash = '#diario-decisiones';
    render(<ResearchHashScroll />);
    expect(scrollToHashAnchor).toHaveBeenCalledTimes(1);
    const [hash, deps] = scrollToHashAnchor.mock.calls[0];
    expect(hash).toBe('diario-decisiones');
    expect(deps).toMatchObject({ intervalMs: 150, maxAttempts: 80 });
  });

  it('decodifica el ancla de los CTA de Inicio (#thesis-change-…)', () => {
    window.location.hash = '#thesis-change-cambio%20tesis';
    render(<ResearchHashScroll />);
    expect(scrollToHashAnchor).toHaveBeenCalledWith('thesis-change-cambio tesis', expect.anything());
  });

  it('sin ancla no hace nada', () => {
    render(<ResearchHashScroll />);
    expect(scrollToHashAnchor).not.toHaveBeenCalled();
  });

  it('un hashchange posterior (enlace interno) vuelve a intentar el scroll', () => {
    window.location.hash = '#diario-decisiones';
    render(<ResearchHashScroll />);
    window.location.hash = '#thesis-change-7';
    act(() => { window.dispatchEvent(new HashChangeEvent('hashchange')); });
    expect(scrollToHashAnchor).toHaveBeenCalledTimes(2);
    expect(scrollToHashAnchor.mock.calls[1][0]).toBe('thesis-change-7');
  });

  it('al desmontar, el bucle pendiente ve un hash ajeno y aborta sin secuestrar', () => {
    window.location.hash = '#diario-decisiones';
    const { unmount } = render(<ResearchHashScroll />);
    const deps = scrollToHashAnchor.mock.calls[0][1] as { getCurrentHash: () => string };
    expect(deps.getCurrentHash()).toBe('#diario-decisiones');
    unmount();
    expect(deps.getCurrentHash()).not.toBe('#diario-decisiones');
  });
});
