import { withAuthErrors } from '@/lib/auth/route-auth';
import { NextRequest, NextResponse } from 'next/server';
import { researchIdentityHeaders } from '@/lib/auth/research-identity';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';

const BACKEND_URL = process.env.FMP_BACKEND_URL;

type Ctx = { params: Promise<{ ticker: string }> };

type Resolved = { error: NextResponse; path?: undefined; identity?: undefined } | { error?: undefined; path: string; identity: Record<string, string> };

async function resolve(ctx: Ctx, method: 'GET' | 'POST'): Promise<Resolved> {
  await requireAuthenticatedUser();
  const { ticker } = await ctx.params;
  if (!/^[A-Za-z0-9.^=-]{1,15}$/.test(ticker)) {
    return { error: NextResponse.json({ error: 'Ticker no valido' }, { status: 400 }) };
  }
  if (!BACKEND_URL) {
    return { error: NextResponse.json({ error: 'Backend no configurado' }, { status: 503 }) };
  }
  const path = `/api/thesis/${encodeURIComponent(ticker.toUpperCase())}/audio`;
  return { path, identity: await researchIdentityHeaders({ method, path }) };
}

/**
 * Proxy firmado del mp3 de la tesis. El navegador no puede firmar la identidad
 * research, así que el `<audio>` pasa por aquí. Reenvía Range (avanzar y
 * retroceder). `v` solo invalida la caché del navegador al cambiar de versión.
 */
async function getHandler(request: NextRequest, ctx: Ctx) {
  const r = await resolve(ctx, 'GET');
  if (r.error) return r.error;
  const range = request.headers.get('range');
  const upstream = await fetch(`${BACKEND_URL}${r.path}`, {
    headers: range ? { ...r.identity, Range: range } : r.identity,
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

/** Pide generar el audio (202). 503 si el sintetizador no responde. */
async function postHandler(_request: NextRequest, ctx: Ctx) {
  const r = await resolve(ctx, 'POST');
  if (r.error) return r.error;
  const upstream = await fetch(`${BACKEND_URL}${r.path}`, { method: 'POST', headers: r.identity, cache: 'no-store' });
  return NextResponse.json({ ok: upstream.ok }, { status: upstream.ok ? 202 : upstream.status === 503 ? 503 : 502 });
}

export const GET = withAuthErrors(getHandler);
export const POST = withAuthErrors(postHandler);
