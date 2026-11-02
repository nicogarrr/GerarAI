import { withAuthErrors } from '@/lib/auth/route-auth';
import { NextResponse } from 'next/server';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { proxyZipDownload } from '@/lib/research/zip-proxy';

type RouteContext = { params: Promise<{ ticker: string }> };

/** Proxy privado: la firma Research OS nunca llega al navegador. */
async function getHandler(_request: Request, { params }: RouteContext) {
  await requireAuthenticatedUser();
  const clean = (await params).ticker.trim().toUpperCase();
  if (!/^[A-Z0-9][A-Z0-9.-]{0,19}$/.test(clean)) {
    return NextResponse.json({ detail: 'Ticker inválido' }, { status: 400 });
  }
  return proxyZipDownload({
    path: `/api/thesis/${encodeURIComponent(clean)}/obsidian.zip`,
    filename: `gerarai-obsidian-${clean}.zip`,
    exportErrorDetail: 'No se pudo exportar a Obsidian',
    notFoundDetail: 'No hay tesis para este ticker',
  });
}

export const GET = withAuthErrors(getHandler);
