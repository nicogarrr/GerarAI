import { withAuthErrors } from '@/lib/auth/route-auth';
import { NextRequest, NextResponse } from 'next/server';
import { researchIdentityHeaders } from '@/lib/auth/research-identity';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';

const BACKEND_URL = process.env.FMP_BACKEND_URL;
const STATES = new Set(['ready', 'pending', 'missing', 'error']);

/** Estado del audio de la tesis: ready | pending | missing | error. */
async function getHandler(_request: NextRequest, { params }: { params: Promise<{ ticker: string }> }) {
  await requireAuthenticatedUser();
  const { ticker } = await params;
  if (!/^[A-Za-z0-9.^=-]{1,15}$/.test(ticker)) {
    return NextResponse.json({ error: 'Ticker no valido' }, { status: 400 });
  }
  if (!BACKEND_URL) {
    return NextResponse.json({ state: 'error' }, { status: 503 });
  }
  const path = `/api/thesis/${encodeURIComponent(ticker.toUpperCase())}/audio/status`;
  const identity = await researchIdentityHeaders({ method: 'GET', path });
  try {
    const upstream = await fetch(`${BACKEND_URL}${path}`, { headers: identity, cache: 'no-store' });
    if (!upstream.ok) return NextResponse.json({ state: 'error' });
    const body = (await upstream.json()) as { state?: string };
    return NextResponse.json({ state: body.state && STATES.has(body.state) ? body.state : 'error' });
  } catch {
    return NextResponse.json({ state: 'error' });
  }
}

export const GET = withAuthErrors(getHandler);
