import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.FMP_BACKEND_URL;

// Mismo formato exacto que emite el backend (calendar_feed_service):
// "gfc_" + 43 caracteres urlsafe de secrets.token_urlsafe(32).
// Un token con otro formato recibe el mismo 404 que uno revocado (no se distingue).
const TOKEN_RE = /^gfc_[A-Za-z0-9_-]{43}\.ics$/;

/**
 * Proxy PÚBLICO del feed ICS de resultados. Las apps de calendario (Apple,
 * Google, Outlook) lo descargan directamente, sin sesión: el token de la URL
 * es la credencial. Reenvía tal cual la respuesta del backend
 * (/api/calendar/feed/<token>.ics), incluido su 404 uniforme.
 */
export async function GET(
    _request: NextRequest,
    { params }: { params: Promise<{ token: string }> },
) {
    const { token } = await params;
    if (!TOKEN_RE.test(token)) {
        return new NextResponse('No encontrado', { status: 404 });
    }
    if (!BACKEND_URL) {
        return NextResponse.json({ error: 'Backend no configurado' }, { status: 503 });
    }
    let upstream: Response;
    try {
        upstream = await fetch(`${BACKEND_URL}/api/calendar/feed/${token}`, { cache: 'no-store' });
    } catch {
        return NextResponse.json({ error: 'Backend no disponible' }, { status: 503 });
    }
    if (!upstream.ok) {
        // Solo el 404 del backend (token desconocido o revocado) se traduce a
        // 404; un 5xx/401 del backend o un fallo de red son un 502/503, nunca
        // un 404 que haría parecer revocado un feed sano.
        return upstream.status === 404
            ? new NextResponse('No encontrado', { status: 404 })
            : NextResponse.json({ error: 'Backend no disponible' }, { status: 502 });
    }
    const body = await upstream.text();
    return new NextResponse(body, {
        status: 200,
        headers: {
            'Content-Type': 'text/calendar; charset=utf-8',
            // El feed solo cambia con el refresco de fechas; nada de caché
            // agresiva para que una fecha corregida se vea pronto.
            'Cache-Control': 'no-cache',
            // URL con credencial implícita: fuera de buscadores y sin referrer.
            'X-Robots-Tag': 'noindex',
            'Referrer-Policy': 'no-referrer',
        },
    });
}
