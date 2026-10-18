import { withAuthErrors } from '@/lib/auth/route-auth';
import { NextResponse } from 'next/server';
import { researchIdentityHeaders } from '@/lib/auth/research-identity';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';

const BACKEND_URL = process.env.FMP_BACKEND_URL ?? 'http://localhost:8000';
type RouteContext = { params: Promise<{ ticker: string }> };

/** Proxy privado: la firma Research OS nunca llega al navegador. */
async function getHandler(_request: Request, { params }: RouteContext) {
  await requireAuthenticatedUser();
  const clean = (await params).ticker.trim().toUpperCase();
  if (!/^[A-Z0-9][A-Z0-9.-]{0,19}$/.test(clean)) {
    return NextResponse.json({ detail: 'Ticker inválido' }, { status: 400 });
  }
  const path = `/api/thesis/${encodeURIComponent(clean)}/obsidian.zip`;
  let upstream: Response;
  try {
    upstream = await fetch(new URL(path, BACKEND_URL), {
      headers: await researchIdentityHeaders({ method: 'GET', path }),
      cache: 'no-store',
    });
  } catch {
    return NextResponse.json({ detail: 'Motor de research no disponible' }, { status: 502 });
  }
  if (upstream.status === 404) {
    return NextResponse.json({ detail: 'No hay tesis para este ticker' }, { status: 404 });
  }
  if (!upstream.ok) {
    return NextResponse.json({ detail: 'No se pudo exportar a Obsidian' }, { status: upstream.status });
  }
  return new NextResponse(await upstream.arrayBuffer(), {
    headers: {
      'content-type': 'application/zip',
      'content-disposition': `attachment; filename="gerarai-obsidian-${clean}.zip"`,
      'cache-control': 'private, no-store',
      'x-content-type-options': 'nosniff',
    },
  });
}

export const GET = withAuthErrors(getHandler);
