/**
 * Icono oficial de una empresa sacado de SU PROPIA web (sin proveedores de
 * logos de terceros, sin claves de pago). Es lo mismo que hace un navegador
 * al pintar la pestaña: leer los <link rel="apple-touch-icon|icon"> de la
 * portada y, si no hay, /apple-touch-icon.png y /favicon.ico.
 *
 * Puro y con `fetch` inyectable para poder probarlo sin red. Límites duros:
 * solo https, hosts con nombre (nunca IPs ni localhost), 8 s por petición,
 * 1 MB de HTML, 300 KB por imagen, como mucho 6 candidatos.
 *
 * Anti-SSRF en dos capas (el dominio sale de una lista revisada o de la web
 * que declara Finnhub, pero ambas pueden apuntar a DNS hostiles):
 *  1. `isSafeIconUrl` exige https, host con nombre y sin IPs literales.
 *  2. Antes de CADA petición (incluidos los saltos de redirección, que se
 *     siguen a mano) el host se resuelve con DNS y TODAS las direcciones
 *     tienen que ser públicas (lib/logos/public-ip.ts): un nombre que
 *     resuelve a 127.0.0.1, 169.254.169.254 o una RFC 1918 no llega a
 *     conectarse. Queda la ventana TOCTOU propia de resolver y conectar en
 *     dos pasos (Node fetch no permite fijar la IP de conexión); el backend
 *     Python sí fija la IP (app/services/public_fetch.py).
 */

import { lookup as dnsLookup } from 'node:dns/promises';

// Ruta relativa con .ts a proposito: scripts/logo-sources-guard.test.ts
// importa este modulo con node --test, sin el alias `@/`.
// @ts-expect-error TS5097
import { isPublicIp } from './public-ip.ts';

export type SiteIcon = { bytes: Uint8Array; contentType: string; url: string; size: number | null };
type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;
/** Resolución DNS inyectable (los tests no tocan la red). */
export type LookupLike = (hostname: string) => Promise<{ address: string; family: number }[]>;
const realLookup: LookupLike = (hostname) => dnsLookup(hostname, { all: true, verbatim: true });

const UA = 'Mozilla/5.0 (compatible; GerarAI-logo/1.0; +https://gerarai.vercel.app)';
const TIMEOUT_MS = 8000;
const MAX_HTML = 1024 * 1024;
const MAX_IMAGE = 300 * 1024;
const MIN_IMAGE = 64;
const MAX_CANDIDATES = 6;
/** Por debajo de 32 px el icono se ve borroso en las cajas de 40-56 px. */
const MIN_SIDE = 32;

export function isSafeIconUrl(raw: string): boolean {
    let url: URL;
    try {
        url = new URL(raw);
    } catch {
        return false;
    }
    if (url.protocol !== 'https:' || url.username || url.password || (url.port && url.port !== '443')) return false;
    const host = url.hostname.toLowerCase();
    if (!host.includes('.') || host.endsWith('.local') || host.endsWith('.internal') || host === 'localhost') return false;
    // IPv4 literal o IPv6 entre corchetes: nunca.
    if (/^\d{1,3}(\.\d{1,3}){3}$/.test(host) || host.startsWith('[')) return false;
    return true;
}

type Candidate = { href: string; rank: number; size: number | null };

function attr(tag: string, name: string): string | null {
    const m = tag.match(new RegExp(`\\b${name}\\s*=\\s*("([^"]*)"|'([^']*)'|([^\\s>]+))`, 'i'));
    return m ? (m[2] ?? m[3] ?? m[4] ?? '').trim() : null;
}

/** Candidatos <link rel=icon> de la portada, mejor primero. */
export function iconCandidatesFromHtml(html: string, baseUrl: string): Candidate[] {
    const out: Candidate[] = [];
    for (const tag of html.match(/<link\b[^>]*>/gi) ?? []) {
        const rel = (attr(tag, 'rel') ?? '').toLowerCase();
        const href = attr(tag, 'href');
        if (!href || !/(^|\s)(apple-touch-icon(-precomposed)?|icon|shortcut icon)(\s|$)/.test(rel)) continue;
        if (rel.includes('mask-icon')) continue; // máscara monocroma de Safari: no es el logo en color
        let abs: string;
        try {
            abs = new URL(href, baseUrl).toString();
        } catch {
            continue;
        }
        const sizes = (attr(tag, 'sizes') ?? '').toLowerCase();
        const fromHref = Number(abs.match(/[-_](\d{2,3})x\1(?=[^\d]|$)/)?.[1] ?? 0);
        const side =
            sizes === 'any' ? 512 : Math.max(fromHref, ...sizes.split(/\s+/).map((s) => Number(s.split('x')[0]) || 0));
        const isSvg = /\.svg(\?|$)/i.test(abs) || (attr(tag, 'type') ?? '').includes('svg');
        const size = isSvg ? 512 : side || null;
        // apple-touch-icon suele ser 180 px y en color; un svg escala sin límite.
        const rank = (rel.includes('apple-touch-icon') ? 1000 : 0) + (size ?? (rel.includes('apple') ? 180 : 16));
        out.push({ href: abs, rank, size });
    }
    return out.sort((a, b) => b.rank - a.rank);
}

/** Lado (px) de un PNG/ICO/GIF/JPEG por cabecera, sin decodificar. null = desconocido (SVG, WebP…). */
export function imageSide(bytes: Uint8Array): number | null {
    const b = bytes;
    if (b.length >= 24 && b[0] === 0x89 && b[1] === 0x50 && b[2] === 0x4e && b[3] === 0x47) {
        const w = (b[16] << 24) | (b[17] << 16) | (b[18] << 8) | b[19];
        const h = (b[20] << 24) | (b[21] << 16) | (b[22] << 8) | b[23];
        return Math.min(w, h);
    }
    if (b.length >= 6 && b[0] === 0 && b[1] === 0 && b[2] === 1 && b[3] === 0) {
        // ICO: la mayor de las entradas (0 = 256 px).
        const count = b[4] | (b[5] << 8);
        let best = 0;
        for (let i = 0; i < count && 6 + i * 16 + 1 < b.length; i++) {
            const w = b[6 + i * 16] || 256;
            const h = b[6 + i * 16 + 1] || 256;
            best = Math.max(best, Math.min(w, h));
        }
        return best || null;
    }
    if (b.length >= 10 && b[0] === 0x47 && b[1] === 0x49 && b[2] === 0x46) {
        return Math.min(b[6] | (b[7] << 8), b[8] | (b[9] << 8));
    }
    return null;
}

function sniffType(bytes: Uint8Array, declared: string): string | null {
    const b = bytes;
    if (b[0] === 0x89 && b[1] === 0x50) return 'image/png';
    if (b[0] === 0 && b[1] === 0 && b[2] === 1 && b[3] === 0) return 'image/x-icon';
    if (b[0] === 0xff && b[1] === 0xd8) return 'image/jpeg';
    if (b[0] === 0x47 && b[1] === 0x49 && b[2] === 0x46) return 'image/gif';
    if (b[0] === 0x52 && b[1] === 0x49 && b[2] === 0x46 && b[8] === 0x57) return 'image/webp';
    const head = new TextDecoder().decode(b.slice(0, 512)).trimStart().toLowerCase();
    if (head.startsWith('<svg') || (head.startsWith('<?xml') && head.includes('<svg'))) return 'image/svg+xml';
    // Una página HTML de error servida con 200 no es un icono.
    return declared.startsWith('image/') && !head.startsWith('<') ? declared : null;
}

async function readCapped(res: Response, cap: number): Promise<Uint8Array | null> {
    const len = Number(res.headers.get('content-length') ?? '0');
    if (len > cap) return null;
    const buf = new Uint8Array(await res.arrayBuffer());
    return buf.length > cap ? null : buf;
}

const MAX_REDIRECTS = 3;

/**
 * El host solo es válido si DNS lo resuelve y TODAS sus direcciones son
 * públicas: con una mezcla pública/privada el round-robin podría conectar a
 * la interna.
 */
async function resolvesPublic(hostname: string, lookup: LookupLike): Promise<boolean> {
    try {
        const addresses = await lookup(hostname);
        return addresses.length > 0 && addresses.every((a) => isPublicIp(a.address));
    } catch {
        return false;
    }
}

/**
 * GET con redirecciones seguidas a mano: cada salto vuelve a pasar
 * `isSafeIconUrl` y la comprobación DNS. Con `redirect: 'follow'` el cliente
 * conectaría con un host interno ANTES de que pudiéramos inspeccionar la URL
 * final (SSRF ciego), y un salto a http:// pasaría inadvertido hasta el final.
 */
async function get(fetchImpl: FetchLike, url: string, accept: string, lookup: LookupLike): Promise<Response | null> {
    let current = url;
    for (let hop = 0; hop <= MAX_REDIRECTS; hop++) {
        if (!isSafeIconUrl(current)) return null;
        let hostname: string;
        try {
            hostname = new URL(current).hostname;
        } catch {
            return null;
        }
        if (!(await resolvesPublic(hostname, lookup))) return null;
        let res: Response;
        try {
            res = await fetchImpl(current, {
                headers: { 'User-Agent': UA, Accept: accept },
                redirect: 'manual',
                signal: AbortSignal.timeout(TIMEOUT_MS),
            });
        } catch {
            return null;
        }
        if (res.status >= 300 && res.status < 400) {
            const location = res.headers.get('location');
            if (!location || hop === MAX_REDIRECTS) return null;
            try {
                current = new URL(location, current).toString();
            } catch {
                return null;
            }
            continue;
        }
        // La URL final (si el cliente la informa) también tiene que ser segura.
        if (!res.ok || (res.url && !isSafeIconUrl(res.url))) return null;
        return res;
    }
    return null;
}

export async function fetchSiteIcon(domain: string, fetchImpl: FetchLike = fetch, lookup: LookupLike = realLookup): Promise<SiteIcon | null> {
    const home = `https://${domain}/`;
    if (!isSafeIconUrl(home)) return null;
    const candidates: Candidate[] = [];
    const page = await get(fetchImpl, home, 'text/html,application/xhtml+xml', lookup);
    if (page) {
        const html = await readCapped(page, MAX_HTML).catch(() => null);
        if (html) candidates.push(...iconCandidatesFromHtml(new TextDecoder().decode(html), page.url || home));
    }
    const origin = page?.url ? new URL(page.url).origin : `https://${domain}`;
    candidates.push(
        { href: `${origin}/apple-touch-icon.png`, rank: 0, size: 180 },
        { href: `${origin}/favicon.ico`, rank: 0, size: null },
    );
    const seen = new Set<string>();
    for (const c of candidates) {
        if (seen.has(c.href) || seen.size >= MAX_CANDIDATES) continue;
        seen.add(c.href);
        const res = await get(fetchImpl, c.href, 'image/avif,image/webp,image/png,image/svg+xml,image/*;q=0.8', lookup);
        if (!res) continue;
        const bytes = await readCapped(res, MAX_IMAGE).catch(() => null);
        if (!bytes || bytes.length < MIN_IMAGE) continue;
        const contentType = sniffType(bytes, (res.headers.get('content-type') ?? '').toLowerCase());
        if (!contentType) continue;
        const side = contentType === 'image/svg+xml' ? null : imageSide(bytes);
        if (side !== null && side < MIN_SIDE) continue;
        return { bytes, contentType, url: res.url || c.href, size: side };
    }
    return null;
}

/** Dominio registrable de una URL de web corporativa (https://www.uber.com/es -> uber.com). */
export function domainFromWebsite(raw: string | null | undefined): string | null {
    if (!raw) return null;
    try {
        const url = new URL(/^https?:\/\//i.test(raw) ? raw : `https://${raw}`);
        const host = url.hostname.toLowerCase().replace(/^www\./, '');
        return isSafeIconUrl(`https://${host}/`) ? host : null;
    } catch {
        return null;
    }
}
