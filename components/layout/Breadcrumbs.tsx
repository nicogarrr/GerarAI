'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { usePathname } from 'next/navigation';
import { ChevronRight } from 'lucide-react';
import { buildCrumbs, type Crumb } from '@/lib/nav/build-crumbs';

/**
 * Migas: la jerarquia se calcula en `lib/nav/build-crumbs.ts` (funcion pura
 * testeable, una sola fuente: ROUTE_CATALOG). Este componente solo anade el
 * override en vivo (`page-breadcrumb-name`, p. ej. el titulo de un screen
 * guardado) y la presentacion.
 */
export default function Breadcrumbs() {
  const pathname = usePathname();
  const [override, setOverride] = useState<{ path: string; name: string } | null>(null);
  useEffect(() => {
    const listener = (event: Event) => setOverride((event as CustomEvent).detail);
    window.addEventListener('page-breadcrumb-name', listener);
    // Child effects may publish before this shell subscribes on first hydration.
    const saved = document.documentElement.dataset.pageBreadcrumb;
    if (saved) { try { const detail = JSON.parse(saved); queueMicrotask(() => setOverride(detail)); } catch { /* Ignore malformed display metadata. */ } }
    return () => window.removeEventListener('page-breadcrumb-name', listener);
  }, []);
  // En la ficha de empresa no hay migas: una sola fila de seis pestañas es
  // toda la navegación (opción 1, 29-oct-2026; el nivel «Análisis» fantasma
  // desaparece). Las subrutas de la ficha (news, sources, assistant) las
  // conservan porque son páginas aparte.
  const fichaMatch = /^\/research\/([^/]+)\/?$/.exec(pathname);
  if (fichaMatch && !['news', 'sources', 'assistant'].includes(fichaMatch[1])) return null;
  const crumbs: Crumb[] = buildCrumbs(pathname);
  if (override?.path === pathname && crumbs.length) crumbs[crumbs.length - 1].label = override.name;
  if (crumbs.length < 2) return null;

  return (
    <nav aria-label="Ruta de navegación" className="mb-4 hidden md:block">
      <ol className="flex flex-wrap items-center gap-1 text-sm text-gray-500">
        {crumbs.map((crumb, index) => {
          const isLast = index === crumbs.length - 1;
          return (
            <li className="flex items-center gap-1" key={`${crumb.label}-${index}`}>
              {index > 0 && <ChevronRight aria-hidden="true" className="h-3.5 w-3.5 shrink-0" />}
              {isLast || !crumb.href ? (
                <span
                  aria-current={isLast ? 'page' : undefined}
                  className="max-w-[24ch] truncate text-gray-300"
                >
                  {crumb.label}
                </span>
              ) : (
                <Link href={crumb.href} className="max-w-[24ch] truncate hover:text-teal-300">{crumb.label}</Link>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
