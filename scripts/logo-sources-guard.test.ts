/**
 * Guard: cadena de fuentes de logo y segunda fuente (icono de la web oficial).
 *
 * Contrato (Nico, 27-oct-2026: «¿por qué UBER y UNH no tienen logo? Consíguelo
 * en todas»):
 * - El orden es FMP image-stock -> /api/logo/<ticker> (nuestra ruta) ->
 *   iniciales. Sin proveedores de logos de terceros ni servicios de pago.
 * - Todos los tickers de cartera y watchlist de Nico tienen dominio oficial
 *   en la lista revisada, por si FMP deja de servir alguno.
 * - La ruta solo pide iconos a dominios de la lista (o a la web declarada por
 *   Finnhub): https, sin IPs ni localhost, tamaño y tiempo acotados.
 * - Un 16 px borroso, una página HTML servida con 200 o un SVG de máscara no
 *   cuentan como logo.
 *
 * Ejecutar: node --experimental-strip-types --test scripts/logo-sources-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// @ts-expect-error TS5097: la extension .ts explicita la exige node --experimental-strip-types en runtime
const { logoSources } = await import('../lib/logos/logo-sources.ts');
// @ts-expect-error TS5097: idem
const { COMPANY_DOMAINS, companyDomainFor, normalizeLogoTicker } = await import('../lib/logos/company-domains.ts');
// @ts-expect-error TS5097: idem
const site = await import('../lib/logos/site-icon.ts');

const NICO = ['ASTS', 'BN', 'RKLB', 'UBER', 'ONDS', 'BABA', 'KRKNF', 'CGEO.L', 'CPT', 'KKR', 'POOL', 'CB', 'UNH', 'HIMS', 'RXRX', 'NAUT', 'ABCL', 'IBRX', 'AAPL'];

function png(side: number, extra = 200): Uint8Array {
  const b = new Uint8Array(24 + extra);
  b.set([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 13, 0x49, 0x48, 0x44, 0x52]);
  const dv = new DataView(b.buffer);
  dv.setUint32(16, side);
  dv.setUint32(20, side);
  return b;
}

function ico(side: number): Uint8Array {
  const b = new Uint8Array(200);
  b.set([0, 0, 1, 0, 1, 0, side >= 256 ? 0 : side, side >= 256 ? 0 : side]);
  return b;
}

// DNS simulado: el guard no toca la red; cualquier host resuelve a IP publica.
const publicLookup = async () => [{ address: '93.184.216.34', family: 4 }];

type Route = { status?: number; body: Uint8Array | string; type?: string; url?: string };
function fakeFetch(routes: Record<string, Route>, calls: string[] = []) {
  return async (url: string) => {
    calls.push(url);
    const r = routes[url];
    if (!r) return new Response('no', { status: 404 });
    const body = typeof r.body === 'string' ? new TextEncoder().encode(r.body) : r.body;
    const res = new Response(body as BodyInit, { status: r.status ?? 200, headers: { 'content-type': r.type ?? 'image/png' } });
    Object.defineProperty(res, 'url', { value: r.url ?? url });
    return res;
  };
}

describe('cadena de fuentes', () => {
  it('FMP primero, nuestra ruta después; el ticker va codificado', () => {
    assert.deepEqual(logoSources('UBER'), ['https://financialmodelingprep.com/image-stock/UBER.png', '/api/logo/UBER']);
    assert.deepEqual(logoSources('CGEO.L')[1], '/api/logo/CGEO.L');
    assert.equal(logoSources('A/B')[1], '/api/logo/A%2FB');
    assert.deepEqual(logoSources('  '), []);
  });

  it('todos los tickers de Nico tienen dominio oficial revisado', () => {
    for (const t of NICO) assert.ok(companyDomainFor(t), `sin dominio: ${t}`);
    assert.equal(companyDomainFor('uber'), 'uber.com');
    assert.equal(companyDomainFor('AENA'), 'aena.es');
    assert.equal(companyDomainFor('ZZZZQ'), null);
  });

  it('BRK.B y BRK-B son el mismo valor; los sufijos de bolsa no se tocan', () => {
    assert.equal(normalizeLogoTicker('brk.b'), 'BRK-B');
    assert.equal(normalizeLogoTicker('RR.L'), 'RR.L');
    assert.equal(normalizeLogoTicker('7203.T'), '7203.T');
  });

  it('la lista solo contiene dominios con nombre (sin esquema, ruta ni IP)', () => {
    for (const [t, d] of Object.entries(COMPANY_DOMAINS)) {
      assert.match(d as string, /^[a-z0-9-]+(\.[a-z0-9-]+)+$/, `${t} -> ${d}`);
      assert.ok(site.isSafeIconUrl(`https://${d}/`), `${t} -> ${d}`);
    }
  });
});

describe('icono de la web oficial', () => {
  it('URLs inseguras rechazadas (SSRF)', () => {
    for (const bad of ['http://uber.com/', 'https://127.0.0.1/', 'https://localhost/', 'https://[::1]/', 'https://intranet/', 'https://a:b@uber.com/', 'https://uber.com:8080/', 'https://x.internal/']) {
      assert.equal(site.isSafeIconUrl(bad), false, bad);
    }
    assert.equal(site.isSafeIconUrl('https://www.uber.com/favicon.ico'), true);
  });

  it('elige apple-touch-icon y los tamaños grandes antes que el favicon de 16 px; ignora mask-icon', () => {
    const html = `<link rel="icon" href="/f16.png" sizes="16x16"><link rel="mask-icon" href="/m.svg">
      <link rel='apple-touch-icon' href='/touch-180x180.png'><link rel="icon" href="https://cdn.x.com/i.svg" type="image/svg+xml">`;
    const c = site.iconCandidatesFromHtml(html, 'https://www.x.com/es/');
    assert.equal(c[0].href, 'https://www.x.com/touch-180x180.png');
    assert.ok(!c.some((x: { href: string }) => x.href.endsWith('/m.svg')));
    assert.equal(c[c.length - 1].href, 'https://www.x.com/f16.png');
  });

  it('lee el lado de PNG e ICO por cabecera', () => {
    assert.equal(site.imageSide(png(180)), 180);
    assert.equal(site.imageSide(ico(48)), 48);
    assert.equal(site.imageSide(ico(256)), 256);
    assert.equal(site.imageSide(new TextEncoder().encode('<svg></svg>')), null);
  });

  it('descarga el icono declarado en la portada', async () => {
    const icon = await site.fetchSiteIcon('uber.com', fakeFetch({
      'https://uber.com/': { body: '<link rel="apple-touch-icon" href="/t.png">', type: 'text/html', url: 'https://www.uber.com/' },
      'https://www.uber.com/t.png': { body: png(180) },
    }), publicLookup);
    assert.ok(icon);
    assert.equal(icon.contentType, 'image/png');
    assert.equal(icon.size, 180);
    assert.equal(icon.url, 'https://www.uber.com/t.png');
  });

  it('portada bloqueada (403) -> prueba /apple-touch-icon.png y /favicon.ico', async () => {
    const icon = await site.fetchSiteIcon('hims.com', fakeFetch({
      'https://hims.com/': { status: 403, body: 'denied', type: 'text/html' },
      'https://hims.com/favicon.ico': { body: ico(48), type: 'image/x-icon' },
    }), publicLookup);
    assert.equal(icon?.contentType, 'image/x-icon');
  });

  it('favicon de 16 px, HTML con 200 y redirección a http no cuentan', async () => {
    const calls: string[] = [];
    const icon = await site.fetchSiteIcon('x.com', fakeFetch({
      'https://x.com/': { body: '<link rel="icon" href="/a.png"><link rel="icon" href="/b.png">', type: 'text/html' },
      'https://x.com/a.png': { body: png(16) },
      'https://x.com/b.png': { body: '<!doctype html><html>' + 'x'.repeat(200), type: 'image/png' },
      'https://x.com/apple-touch-icon.png': { body: png(180), url: 'http://x.com/apple-touch-icon.png' },
      'https://x.com/favicon.ico': { body: ico(16), type: 'image/x-icon' },
    }, calls), publicLookup);
    assert.equal(icon, null);
    assert.ok(calls.length <= 7, 'número de peticiones acotado');
  });

  it('dominio desde la web corporativa (Finnhub weburl)', () => {
    assert.equal(site.domainFromWebsite('https://www.uber.com/es/'), 'uber.com');
    assert.equal(site.domainFromWebsite('unitedhealthgroup.com'), 'unitedhealthgroup.com');
    assert.equal(site.domainFromWebsite('http://10.0.0.1'), null);
    assert.equal(site.domainFromWebsite(''), null);
  });
});

describe('ruta /api/logo', () => {
  const route = readFileSync('app/api/logo/[ticker]/route.ts', 'utf8');
  it('valida el ticker, cachea solo en el navegador (privada, exige sesión) y nunca toma el dominio de la petición', () => {
    assert.match(route, /TICKER_RE\.test\(ticker\)/);
    assert.match(route, /'private, max-age=86400'/);
    assert.doesNotMatch(route, /s-maxage|'public/, 'respuesta con sesión: sin caché compartida/CDN');
    assert.match(route, /companyDomainFor\(key\) \?\? \(await finnhubDomain\(key\)\)/);
    assert.doesNotMatch(route, /searchParams/, 'ni ?url= ni ?domain=: sin proxy abierto');
    assert.match(route, /X-Content-Type-Options/);
    assert.match(route, /sandbox/);
  });
});
