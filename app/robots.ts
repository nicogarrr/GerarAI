import { MetadataRoute } from 'next';

import { siteUrl } from '@/lib/config/site';

/**
 * Público y privado comparten origen, así que `Disallow: /` dejaría fuera
 * también la landing y las páginas públicas. Al revés: se permite el árbol
 * público de `app/(public)` y se bloquean explícitamente las rutas
 * autenticadas, que ya devuelven un muro de sesión en lugar de contenido.
 *
 * En Google manda la regla más específica, así que `disallow: '/research'`
 * gana sobre `allow: '/'` para esa ruta. `'/research'` cubre también
 * `/research/...` y sus subpáginas.
 */
const DISALLOWED = [
  '/api/',
  '/_next/',
  // Acceso: formularios y ajustes de cuenta.
  '/sign-in',
  '/sign-up',
  '/security',
  '/settings',
  // Espacio de trabajo autenticado (grupo de rutas `(root)`).
  '/research',
  '/portfolio',
  '/propicks',
  '/screeners',
  '/screener',
  '/alerts',
  '/insider',
  '/knowledge',
  '/knowledge-graph',
  '/ownership',
  '/corporate-actions',
  '/calendar',
  '/movers',
  '/temas',
  '/taxes',
  '/plan',
  '/risk',
  '/export',
  '/watchlist',
  '/stocks',
];

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: '*',
        allow: ['/', '/metodologia', '/help'],
        disallow: DISALLOWED,
      },
    ],
    sitemap: `${siteUrl()}/sitemap.xml`,
  };
}
