import { withAuthErrors } from '@/lib/auth/route-auth';
import { NextRequest, NextResponse } from 'next/server';
import { researchIdentityHeaders } from '@/lib/auth/research-identity';

const BACKEND_URL = process.env.FMP_BACKEND_URL;

// Proxy firmado del memo Markdown: el navegador no puede firmar la identidad
// research, asi que la descarga pasa por este route handler server-side.
async function getHandler(
  _request: NextRequest,
  { params }: { params: Promise<{ ticker: string }> },
) {
  const { ticker } = await params;
  if (!/^[A-Za-z0-9.^=-]{1,15}$/.test(ticker)) {
    return NextResponse.json({ error: 'Ticker no valido' }, { status: 400 });
  }
  if (!BACKEND_URL) {
    return NextResponse.json({ error: 'Backend no configurado' }, { status: 503 });
  }
  const identity = await researchIdentityHeaders({
    method: 'GET',
    path: `/api/thesis/${encodeURIComponent(ticker.toUpperCase())}/memo.md`,
  });
  const upstream = await fetch(
    `${BACKEND_URL}/api/thesis/${encodeURIComponent(ticker.toUpperCase())}/memo.md`,
    { headers: identity, cache: 'no-store' },
  );
  if (!upstream.ok) {
    return NextResponse.json({ error: 'Memo no disponible' }, { status: upstream.status });
  }
  const body = await upstream.text();
  const disposition =
    upstream.headers.get('content-disposition') ??
    `attachment; filename="tesis-${ticker.toLowerCase()}.md"`;
  return new NextResponse(body, {
    status: 200,
    headers: {
      'Content-Type': 'text/markdown; charset=utf-8',
      'Content-Disposition': disposition,
    },
  });
}

export const GET = withAuthErrors(getHandler);
