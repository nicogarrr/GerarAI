'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { usePathname } from 'next/navigation';
import { ChevronRight } from 'lucide-react';
import { flattenNavItems, ROUTE_CATALOG, type NavItem } from '@/lib/constants';

// href opcional: los niveles que no son una ruta real (la seccion del menu)
// se muestran como texto plano - un enlace a `#Seccion` no navega a nada (F141).
type Crumb = { href?: string; label: string };

/**
 * Migas derivadas de `NAV_SECTIONS`: la ruta se ancla al href mas largo que
 * coincida, y los segmentos sobrantes se anaden como migas propias. Asi
 * /research/MSFT/financial-terminal se lee "Analisis > Research > MSFT >
 * Terminal financiero" sin que ninguna pagina tenga que mantener su propia
 * jerarquia, y las rutas huerfanas del menu (que antes no existian en ningun
 * sitio) tienen contexto.
 */

/** Sub-rutas con nombre legible; el resto se muestra tal cual (ticker, screenId). */
const SUBROUTE_LABELS: Record<string, string> = {
  'financial-terminal': 'Terminal financiero',
  'driver-assumptions': 'Supuestos de drivers',
  'decision-lessons': 'Lecciones de decisiones',
  'management-credibility': 'Credibilidad de la directiva',
  // Fuera del nav principal (quick win UX 3); la miga sigue legible.
  // Modulo Inversores: sub-paginas fijas (no son un slug de inversor).
  'carteras': 'Carteras',
  'mas-compradas': 'Más compradas',
};

/** Slug sin etiqueta propia (p. ej. "warren-buffett") -> "Warren Buffett" en vez del slug crudo. */
function humanizeSlug(segment: string): string {
  if (!/^[a-z]+(?:-[a-z]+)+$|^[a-z]{4,}$/.test(segment)) return segment;
  return segment
    .split('-')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

/** El dashboard vive en `/inicio` porque `/` es la landing pública. */
const HOME_HREF = '/inicio';

function buildCrumbs(pathname: string): Crumb[] {
  const items = flattenNavItems();
  const parentOf = new Map<string, NavItem>();
  const sectionOf = new Map<string, string>();
  for (const section of ROUTE_CATALOG) {
    for (const item of section.items) {
      sectionOf.set(item.href, section.title);
      for (const node of [item, ...(item.children ?? [])]) {
        parentOf.set(node.href, item);
        if (!sectionOf.has(node.href)) sectionOf.set(node.href, section.title);
      }
    }
  }

  if (pathname === HOME_HREF) return [{ href: HOME_HREF, label: 'Inicio' }];

  // Ancla: el href mas largo que sea prefijo de la ruta.
  const anchor = items
    .filter((item) => item.href !== HOME_HREF && (pathname === item.href || pathname.startsWith(`${item.href}/`)))
    .sort((a, b) => b.href.length - a.href.length)[0];

  const crumbs: Crumb[] = [{ href: HOME_HREF, label: 'Inicio' }];

  if (!anchor) return crumbs;

  const sectionTitle = sectionOf.get(anchor.href);
  if (sectionTitle && sectionTitle !== 'Principal') {
    crumbs.push({ label: sectionTitle });
  }
  // Si el ancla es un hijo declarado (/research/news), su padre (/research)
  // es un nivel real de la jerarquia: sin el la miga saltaba de la seccion
  // al hijo ("Analisis > Noticias") y el padre dejaba de ser alcanzable.
  const anchorParent = parentOf.get(anchor.href);
  if (anchorParent && anchorParent.href !== anchor.href) {
    crumbs.push({ href: anchorParent.href, label: anchorParent.label });
  }
  crumbs.push({ href: anchor.href, label: anchor.label });

  // Segmentos restantes: hijo declarado del nav, sub-ruta con nombre o el
  // propio identificador (ticker, screenId).
  const rest = pathname.slice(anchor.href.length).split('/').filter(Boolean);
  let parent = parentOf.get(anchor.href);
  rest.forEach((segment, index) => {
    const pathSoFar = `${anchor.href}/${rest.slice(0, index + 1).join('/')}`;
    const declared = parent?.children?.find((child) => child.href === pathSoFar);
    if (declared) {
      crumbs.push({ href: declared.href, label: declared.label });
      parent = declared;
      return;
    }
    crumbs.push({ href: pathSoFar, label: SUBROUTE_LABELS[segment] ?? (anchor.href === '/inversores' ? humanizeSlug(segment) : segment) });
  });

  return crumbs;
}

export default function Breadcrumbs() {
  const pathname = usePathname();
  const [override, setOverride] = useState<{ path: string; name: string } | null>(null);
  useEffect(() => {
    const listener = (event: Event) => setOverride((event as CustomEvent).detail);
    window.addEventListener('page-breadcrumb-name', listener);
    return () => window.removeEventListener('page-breadcrumb-name', listener);
  }, []);
  const crumbs = buildCrumbs(pathname);
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
