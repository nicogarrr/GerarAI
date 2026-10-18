import { withAuthErrors } from '@/lib/auth/route-auth';
import { NextResponse } from 'next/server';
import { researchIdentityHeaders } from '@/lib/auth/research-identity';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';

const BACKEND_URL = process.env.FMP_BACKEND_URL ?? 'http://localhost:8000';

type RouteContext = { params: Promise<{ ticker: string }> };

/**
 * Proxy same-origin para descargar el EPUB de la tesis.
 * El navegador no puede firmar la identidad Research OS, así que esta
 * route la firma en servidor y retransmite el binario del data-engine.
 */
async function getHandler(_request: Request, { params }: RouteContext) {
  await requireAuthenticatedUser();
  const { ticker } = await params;
  const clean = ticker.trim().toUpperCase();
  if (!clean || clean.length > 20) {
    return NextResponse.json({ detail: 'Ticker inválido' }, { status: 400 });
  }
  const encoded = encodeURIComponent(clean);

  let upstream: Response;
  try {
    upstream = await fetch(`${BACKEND_URL}/api/thesis/${encoded}/epub`, {
      headers: await researchIdentityHeaders({
        method: 'GET',
        path: `/api/thesis/${encoded}/epub`,
      }),
      cache: 'no-store',
    });
  } catch {
    return NextResponse.json({ detail: 'Motor de research no disponible' }, { status: 502 });
  }

  if (upstream.status === 404) {
    return NextResponse.json({ detail: 'No thesis for ticker' }, { status: 404 });
  }
  if (!upstream.ok) {
    return NextResponse.json(
      { detail: `EPUB export failed (${upstream.status})` },
      { status: upstream.status },
    );
  }

  const buffer = await upstream.arrayBuffer();
  // La marca visible del fichero la fija el frontend (override), no el backend.
  const disposition = `attachment; filename="gerarai-thesis-${encoded}.epub"`;
  return new NextResponse(buffer, {
    headers: {
      'content-type': 'application/epub+zip',
      'content-disposition': disposition,
    },
  });
}

export const GET = withAuthErrors(getHandler);
