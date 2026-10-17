/**
 * Origen canonico del sitio (una sola fuente para sitemap.xml, robots.txt y
 * cualquier URL absoluta publica).
 *
 * Antes cada fichero repetia `process.env.BETTER_AUTH_URL ||
 * 'http://localhost:3000'`, y los tres acababan con barras distintas segun
 * quien los escribiera (`/sitemap.xml` vs `//sitemap.xml`). Se resuelve y se
 * normaliza aqui, sin barra final.
 *
 * Solo usar desde servidor (sitemap y robots se evaluan en el servidor).
 */
const RAW_SITE_URL =
    process.env.NEXT_PUBLIC_SITE_URL || process.env.BETTER_AUTH_URL || 'http://localhost:3000';

export function siteUrl(): string {
    return RAW_SITE_URL.replace(/\/+$/, '');
}
