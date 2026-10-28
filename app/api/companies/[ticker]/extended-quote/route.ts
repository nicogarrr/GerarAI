import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { isE2EMarketFixtureEnabled } from '@/lib/e2e-market-fixture';
import { e2eExtendedQuoteFixture } from '@/lib/e2e-extended-quote-fixture';
import { researchRequest } from '@/lib/research/client';
import { quoteSymbolFor } from '@/lib/market/quote-symbol';
import type { ExtendedQuote } from '@/lib/market/extended-quote';

export async function GET(request: Request, { params }: { params: Promise<{ ticker: string }> }) {
    try {
        await requireAuthenticatedUser();
    } catch {
        return Response.json({ status: 'unavailable' }, { status: 401, headers: { 'Cache-Control': 'no-store' } });
    }
    const { ticker } = await params;
    if (!/^[A-Za-z0-9.^=-]{1,32}$/.test(ticker)) return Response.json({ status: 'unavailable' }, { status: 400 });
    // Same exact gate as the server market/history fixture. No live Yahoo
    // request in deterministic E2E, and no fictitious production fallback.
    if (isE2EMarketFixtureEnabled(process.env, ticker)) {
        return Response.json(e2eExtendedQuoteFixture(ticker), { headers: { 'Cache-Control': 'no-store' } });
    }
    try {
        let symbol = ticker;
        const signal = AbortSignal.timeout(18000);
        if (new URL(request.url).searchParams.get('resolveListing') === '1') {
            // A transient SSR master timeout must not permanently silence the
            // header. Resolve again server-side, never guess a naked US ticker.
            const company = await researchRequest<{ ticker: string; exchange?: string; currency?: string }>(
                `/api/companies/${encodeURIComponent(ticker)}`, { timeoutMs: 6000, signal },
            );
            const resolved = typeof company.ticker === 'string' ? quoteSymbolFor(company, company.ticker) : null;
            // Sin correspondencia de bolsa validada: «no disponible» es la
            // respuesta (200), no un error. Con 404 cada visita a la ficha de
            // un listado así (MC.PA en París) dejaba un error en la consola.
            if (!resolved) return Response.json({ status: 'unavailable' }, { headers: { 'Cache-Control': 'no-store' } });
            symbol = resolved;
        }
        const quote = await researchRequest<ExtendedQuote>(`/api/companies/${encodeURIComponent(symbol)}/extended-quote`, { signal });
        return Response.json(quote, { headers: { 'Cache-Control': 'no-store' } });
    } catch {
        return Response.json({ status: 'unavailable' }, { status: 502, headers: { 'Cache-Control': 'no-store' } });
    }
}
