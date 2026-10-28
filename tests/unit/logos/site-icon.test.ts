// @vitest-environment node
import { describe, expect, it, vi } from 'vitest';

import { domainFromWebsite, fetchSiteIcon, iconCandidatesFromHtml, imageSide, isSafeIconUrl } from '@/lib/logos/site-icon';

/** PNG mínimo con la cabecera IHDR de lado x lado, relleno hasta superar MIN_IMAGE. */
function png(side: number, pad = 100): Uint8Array {
    const b = new Uint8Array(24 + pad);
    b.set([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
    const put = (o: number, v: number) => { b[o] = (v >>> 24) & 255; b[o + 1] = (v >>> 16) & 255; b[o + 2] = (v >>> 8) & 255; b[o + 3] = v & 255; };
    put(16, side); put(20, side);
    return b;
}
const text = (s: string) => new TextEncoder().encode(s);
const res = (body: Uint8Array | string, init: { url?: string; type?: string; ok?: boolean; headers?: Record<string, string> } = {}) => {
    const r = new Response(typeof body === 'string' ? text(body) : (body as BodyInit), { status: init.ok === false ? 404 : 200, headers: { 'content-type': init.type ?? 'text/html', ...(init.headers ?? {}) } });
    Object.defineProperty(r, 'url', { value: init.url ?? '' });
    return r;
};

describe('isSafeIconUrl (anti-SSRF)', () => {
    it.each([
        ['https://acme.com/x.png', true],
        ['https://sub.acme.co.uk/', true],
        ['https://acme.com:443/x', true],
        ['http://acme.com/x', false],
        ['https://localhost/x', false],
        ['https://intranet/x', false],
        ['https://box.local/x', false],
        ['https://db.internal/x', false],
        ['https://127.0.0.1/x', false],
        ['https://10.0.0.5/x', false],
        ['https://[::1]/x', false],
        ['https://user:pw@acme.com/x', false],
        ['https://acme.com:8443/x', false],
        ['ftp://acme.com/x', false],
        ['no es url', false],
    ])('%s -> %s', (url, expected) => {
        expect(isSafeIconUrl(url)).toBe(expected);
    });
});

describe('domainFromWebsite', () => {
    it('extrae el dominio sin www y descarta hosts inseguros', () => {
        expect(domainFromWebsite('https://www.uber.com/es')).toBe('uber.com');
        expect(domainFromWebsite('Uber.COM')).toBe('uber.com');
        expect(domainFromWebsite(null)).toBeNull();
        expect(domainFromWebsite('')).toBeNull();
        expect(domainFromWebsite('http://192.168.1.1')).toBeNull();
        expect(domainFromWebsite('localhost')).toBeNull();
    });
});

describe('imageSide', () => {
    it('lee el lado de PNG, ICO (mayor entrada, 0 = 256) y GIF; null para formatos sin cabecera útil', () => {
        expect(imageSide(png(180))).toBe(180);
        const ico = new Uint8Array(6 + 32);
        ico.set([0, 0, 1, 0, 2, 0]); // 2 entradas
        ico[6] = 16; ico[7] = 16; ico[22] = 0; ico[23] = 0; // 16x16 y 256x256
        expect(imageSide(ico)).toBe(256);
        const gif = new Uint8Array(12);
        gif.set([0x47, 0x49, 0x46, 0x38, 0x39, 0x61, 48, 0, 32, 0]);
        expect(imageSide(gif)).toBe(32);
        expect(imageSide(text('<svg></svg>'))).toBeNull();
        expect(imageSide(new Uint8Array(3))).toBeNull();
    });
});

describe('iconCandidatesFromHtml', () => {
    const html = `
      <link rel="icon" href="/favicon-32x32.png" sizes="32x32">
      <link rel="apple-touch-icon" href="/touch.png" sizes="180x180">
      <link rel="mask-icon" href="/mask.svg">
      <link rel="icon" type="image/svg+xml" href="https://cdn.acme.com/logo.svg">
      <link rel="stylesheet" href="/a.css">
      <link rel="icon">`;
    it('prioriza apple-touch-icon, trata svg como grande, ignora mask-icon y enlaces sin href', () => {
        const c = iconCandidatesFromHtml(html, 'https://acme.com/');
        expect(c.map((x) => x.href)).toEqual(['https://acme.com/touch.png', 'https://cdn.acme.com/logo.svg', 'https://acme.com/favicon-32x32.png']);
        expect(c[0].size).toBe(180);
        expect(c[1].size).toBe(512);
        expect(c[2].size).toBe(32);
    });
    it('sizes="any" cuenta como 512 y un href con NxN en el nombre infiere el lado', () => {
        const c = iconCandidatesFromHtml('<link rel="icon" sizes="any" href="/a.ico"><link rel=icon href=/i-96x96.png>', 'https://acme.com');
        expect(c.map((x) => x.size)).toEqual([512, 96]);
    });
});

describe('fetchSiteIcon', () => {
    it('devuelve el primer icono válido de la portada con tipo detectado por contenido', async () => {
        const fetchMock = vi.fn(async (url: string, _init?: RequestInit) => {
            if (url === 'https://acme.com/') return res('<link rel="apple-touch-icon" href="/t.png" sizes="180x180">', { url: 'https://acme.com/' });
            if (url === 'https://acme.com/t.png') return res(png(180), { url, type: 'application/octet-stream' });
            return res('', { ok: false });
        });
        const icon = await fetchSiteIcon('acme.com', fetchMock);
        expect(icon).toMatchObject({ contentType: 'image/png', url: 'https://acme.com/t.png', size: 180 });
        expect(fetchMock.mock.calls[0][1]?.headers).toMatchObject({ 'User-Agent': expect.stringContaining('GerarAI-logo') });
    });
    it('rechaza dominios inseguros sin hacer ninguna petición', async () => {
        const fetchMock = vi.fn();
        expect(await fetchSiteIcon('127.0.0.1', fetchMock)).toBeNull();
        expect(await fetchSiteIcon('localhost', fetchMock)).toBeNull();
        expect(fetchMock).not.toHaveBeenCalled();
    });
    it('salta iconos borrosos (<32 px), HTML de error con 200 y imágenes demasiado pequeñas; cae a favicon.ico', async () => {
        const ico = new Uint8Array(6 + 16 + 100);
        ico.set([0, 0, 1, 0, 1, 0]); ico[6] = 64; ico[7] = 64;
        const fetchMock = vi.fn(async (url: string) => {
            if (url === 'https://acme.com/') return res('', { url });
            if (url.endsWith('/apple-touch-icon.png')) return res(png(16), { url, type: 'image/png' }); // borroso
            if (url.endsWith('/favicon.ico')) return res(ico, { url, type: 'image/x-icon' });
            return res('', { ok: false });
        });
        expect(await fetchSiteIcon('acme.com', fetchMock)).toMatchObject({ contentType: 'image/x-icon', size: 64 });
        const htmlError = vi.fn(async (url: string) => res('<html>error</html>'.padEnd(200, ' '), { url, type: 'image/png' }));
        expect(await fetchSiteIcon('acme.com', htmlError)).toBeNull();
    });
    it('una redirección a un host inseguro invalida la respuesta', async () => {
        const fetchMock = vi.fn(async (url: string) => res(png(180), { url: 'https://127.0.0.1/evil.png', type: 'image/png' }));
        expect(await fetchSiteIcon('acme.com', fetchMock)).toBeNull();
    });
    it('respeta el tope de tamaño (content-length) y los errores de red', async () => {
        const big = vi.fn(async (url: string) => res(png(180), { url, type: 'image/png', headers: { 'content-length': String(400 * 1024) } }));
        expect(await fetchSiteIcon('acme.com', big)).toBeNull();
        const boom = vi.fn(async () => { throw new Error('net'); });
        expect(await fetchSiteIcon('acme.com', boom)).toBeNull();
    });
    it('acepta SVG sin medir su lado', async () => {
        const svg = '<svg xmlns="http://www.w3.org/2000/svg">' + ' '.repeat(100) + '</svg>';
        const fetchMock = vi.fn(async (url: string) => (url === 'https://acme.com/' ? res('<link rel="icon" href="/l.svg">', { url }) : res(svg, { url, type: 'image/svg+xml' })));
        expect(await fetchSiteIcon('acme.com', fetchMock)).toMatchObject({ contentType: 'image/svg+xml', size: null });
    });
});
