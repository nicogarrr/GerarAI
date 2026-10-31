import { withAuthErrors } from '@/lib/auth/route-auth';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { companyDomainFor, normalizeLogoTicker } from '@/lib/logos/company-domains';
import { domainFromWebsite, fetchSiteIcon, type SiteIcon } from '@/lib/logos/site-icon';
import { LOGO_TOTAL_BUDGET_MS } from '@/lib/logos/logo-budget';

/**
 * Segunda fuente de logos (la primera es FMP image-stock en el navegador):
 * el icono oficial de la web de la empresa, servido desde NUESTRO origen y
 * cacheado (CDN 7 días + memoria del proceso). Así un ticker que FMP no
 * tiene (404, p. ej. AENA sin sufijo) sigue mostrando su logo y no las
 * iniciales. Gratis: ni proveedores de logos de terceros ni claves de pago.
 *
 * El dominio NUNCA viene de la petición: sale de la lista revisada
 * (lib/logos/company-domains.ts) o, si hay FINNHUB_API_KEY (ya opcional en
 * la app), de la web que Finnhub declara para ese símbolo. Sin dominio o sin
 * icono válido -> 404 cacheado y la UI pinta las iniciales.
 *
 * Exige sesión (401 sin ella): sin ella un anónimo podía disparar peticiones
 * salientes con el token de Finnhub del servidor. La caché es `private` para
 * que ningún CDN sirva a un anónimo una respuesta pedida con sesión.
 */
export const runtime = 'nodejs';

const TICKER_RE = /^[A-Za-z0-9.^=-]{1,32}$/;
const HIT_CACHE = 'private, max-age=86400';
const MISS_CACHE = 'private, max-age=3600';
const MEMORY_TTL_MS = 24 * 60 * 60 * 1000;
const MEMORY_MAX = 500;

type Entry = { at: number; icon: SiteIcon | null };
const memory = new Map<string, Entry>();

function remember(key: string, icon: SiteIcon | null) {
    if (memory.size >= MEMORY_MAX) {
        const oldest = memory.keys().next().value;
        if (oldest !== undefined) memory.delete(oldest);
    }
    memory.set(key, { at: Date.now(), icon });
}

async function getHandler(_request: Request, { params }: { params: Promise<{ ticker: string }> }) {
    await requireAuthenticatedUser();
    const { ticker } = await params;
    if (!TICKER_RE.test(ticker)) return miss(400);
    const icon = await resolveLogo(ticker);
    if (!icon) return miss(404);
    return new Response(icon.bytes as BodyInit, {
        headers: {
            'Content-Type': icon.contentType,
            'Cache-Control': HIT_CACHE,
            'X-Content-Type-Options': 'nosniff',
            // Un SVG abierto directamente no puede ejecutar nada en nuestro origen.
            'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; sandbox",
        },
    });
}

const FINNHUB_TIMEOUT_MS = 2500;

async function finnhubDomain(ticker: string, outer?: AbortSignal): Promise<string | null> {
    const token = process.env.FINNHUB_API_KEY;
    if (!token) return null;
    const base = process.env.FINNHUB_BASE_URL || 'https://finnhub.io/api/v1';
    const own = AbortSignal.timeout(FINNHUB_TIMEOUT_MS);
    const signal = outer && typeof AbortSignal.any === 'function' ? AbortSignal.any([own, outer]) : own;
    try {
        const res = await fetch(`${base}/stock/profile2?symbol=${encodeURIComponent(ticker)}&token=${encodeURIComponent(token)}`, {
            signal,
        });
        if (!res.ok) return null;
        const profile = (await res.json()) as { weburl?: unknown };
        return typeof profile.weburl === 'string' ? domainFromWebsite(profile.weburl) : null;
    } catch {
        return null;
    }
}

// Medido en prod (31-oct-2026): /api/logo/AENA llegó a 10.3s y Vercel la
// mató con 504 (función Hobby de 10s) porque fetchSiteIcon encadena home +
// candidatos, cada uno con su propio timeout de 8s. Con 4s el peor caso
// cabe con margen y el fallo queda cacheado (memoria 24h + Cache-Control 1h).
async function resolveLogo(ticker: string): Promise<SiteIcon | null> {
    const key = normalizeLogoTicker(ticker);
    const cached = memory.get(key);
    if (cached && Date.now() - cached.at < MEMORY_TTL_MS) return cached.icon;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), LOGO_TOTAL_BUDGET_MS);
    try {
        const domain = companyDomainFor(key) ?? (await finnhubDomain(key, controller.signal));
        const boundedFetch: typeof fetch = (input, init) =>
            fetch(input, {
                ...init,
                signal:
                    init?.signal && typeof AbortSignal.any === 'function'
                        ? AbortSignal.any([init.signal, controller.signal])
                        : controller.signal,
            });
        const icon = domain ? await fetchSiteIcon(domain, boundedFetch).catch(() => null) : null;
        remember(key, icon);
        return icon;
    } catch {
        remember(key, null);
        return null;
    } finally {
        clearTimeout(timer);
    }
}

function miss(status: number) {
    return new Response(null, { status, headers: { 'Cache-Control': MISS_CACHE } });
}

export const GET = withAuthErrors(getHandler);
