'use client';

import { createContext, useContext, useMemo, type ReactNode } from 'react';

import type { NavSection } from '@/lib/constants';

/**
 * Enlaces de navegacion ocultos por una puerta de fase del SERVIDOR. El layout
 * servidor decide la lista (sin variables NEXT_PUBLIC ni secretos en el cliente)
 * y todos los consumidores del catalogo la aplican con `filterHiddenNav`. Ocultar
 * un enlace no sustituye la autorizacion del backend; la URL directa sigue
 * respondiendo con la pagina "no disponible".
 */
const HiddenHrefsContext = createContext<readonly string[]>([]);

export function NavFlagsProvider({ hiddenHrefs, children }: { hiddenHrefs: readonly string[]; children: ReactNode }) {
  return <HiddenHrefsContext.Provider value={hiddenHrefs}>{children}</HiddenHrefsContext.Provider>;
}

export function useHiddenHrefs(): readonly string[] {
  return useContext(HiddenHrefsContext);
}

export function filterHiddenNav(sections: NavSection[], hidden: readonly string[]): NavSection[] {
  if (!hidden.length) return sections;
  return sections.map((section) => ({
    ...section,
    items: section.items
      .filter((item) => !hidden.includes(item.href))
      .map((item) => (item.children ? { ...item, children: item.children.filter((c) => !hidden.includes(c.href)) } : item)),
  }));
}

export function useVisibleSections(sections: NavSection[]): NavSection[] {
  const hidden = useHiddenHrefs();
  return useMemo(() => filterHiddenNav(sections, hidden), [sections, hidden]);
}
