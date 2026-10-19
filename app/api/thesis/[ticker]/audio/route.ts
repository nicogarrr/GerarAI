import { withAuthErrors } from '@/lib/auth/route-auth';
import { NextRequest, NextResponse } from 'next/server';
import { researchIdentityHeaders } from '@/lib/auth/research-identity';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';

const BACKEND_URL = process.env.FMP_BACKEND_URL;

/**
 * Proxy firmado del audio de la tesis por (ticker, versión). El navegador no
 * puede firmar la identidad research, así que el `<audio>` pasa por aquí.
 * Reenvía Range para poder avanzar y retroceder. Si el backend no tiene audio
 * para esa versión devuelve 404 y el reproductor lo dice.
 */
async function getHandler(
  request: NextRequest,
  { params }: { params: Promise<{ ticker: string }> },
) {
  await requireAuthenticatedUser();
  const { ticker } = await params;
  if (!/^[A-Za-z0-9.^=-]{1,15}$/.test(ticker)) {
    return NextResponse.json({ error: 'Ticker no valido' }, { status: 400 });
  }
  const version = request.nextUrl.searchParams.get('v') ?? '';
  if (!/^\d{1,6}$/.test(version)) {
    return NextResponse.json({ error: 'Versión no válida' }, { status: 400 });
  }
  if (!BACKEND_URL) {
    return NextResponse.json({ error: 'Backend no configurado' }, { status: 503 });
  }
  const path = `/api/thesis/${encodeURIComponent(ticker.toUpperCase())}/audio`;
  const identity = await researchIdentityHeaders({ method: 'GET', path });
  const range = request.headers.get('range');
  const upstream = await fetch(`${BACKEND_URL}${path}?version=${version}`, {
    headers: range ? { ...identity, Range: range } : identity,
    cache: 'no-store',
  });
  if (!upstream.ok && upstream.status !== 206) {
    return NextResponse.json({ error: 'Audio no disponible' }, { status: upstream.status === 404 ? 404 : 502 });
  }
  const headers = new Headers({
    'Content-Type': upstream.headers.get('content-type') ?? 'audio/mpeg',
    'Cache-Control': 'private, max-age=3600',
    'Accept-Ranges': 'bytes',
  });
  for (const name of ['content-length', 'content-range']) {
    const value = upstream.headers.get(name);
    if (value) headers.set(name, value);
  }
  return new NextResponse(upstream.body, { status: upstream.status, headers });
}

export const GET = withAuthErrors(getHandler);
