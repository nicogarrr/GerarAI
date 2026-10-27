/**
 * Icono oficial de una empresa sacado de SU PROPIA web (sin proveedores de
 * logos de terceros, sin claves de pago). Es lo mismo que hace un navegador
 * al pintar la pestaña: leer los <link rel="apple-touch-icon|icon"> de la
 * portada y, si no hay, /apple-touch-icon.png y /favicon.ico.
 *
 * Puro y con `fetch` inyectable para poder probarlo sin red. Límites duros:
 * solo https, hosts con nombre (nunca IPs ni localhost), 8 s por petición,
 * 1 MB de HTML, 300 KB por imagen, como mucho 6 candidatos.
 */

export type SiteIcon = { bytes: Uint8Array; contentType: string; url: string; size: number | null };
type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

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

async function get(fetchImpl: FetchLike, url: string, accept: string): Promise<Response | null> {
    if (!isSafeIconUrl(url)) return null;
    try {
        const res = await fetchImpl(url, {
            headers: { 'User-Agent': UA, Accept: accept },
            redirect: 'follow',
            signal: AbortSignal.timeout(TIMEOUT_MS),
        });
        // La redirección también tiene que acabar en un host seguro.
        if (!res.ok || (res.url && !isSafeIconUrl(res.url))) return null;
        return res;
    } catch {
        return null;
    }
}

export async function fetchSiteIcon(domain: string, fetchImpl: FetchLike = fetch): Promise<SiteIcon | null> {
    const home = `https://${domain}/`;
    if (!isSafeIconUrl(home)) return null;
    const candidates: Candidate[] = [];
    const page = await get(fetchImpl, home, 'text/html,application/xhtml+xml');
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
        const res = await get(fetchImpl, c.href, 'image/avif,image/webp,image/png,image/svg+xml,image/*;q=0.8');
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
