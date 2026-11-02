import { withAuthErrors } from '@/lib/auth/route-auth';
import { NextRequest, NextResponse } from 'next/server';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { fetchMemoMarkdown } from '@/lib/thesis/fetch-memo';

// Proxy firmado del memo Markdown: el navegador no puede firmar la identidad
// research, asi que la descarga pasa por este route handler server-side.
async function getHandler(
  _request: NextRequest,
  { params }: { params: Promise<{ ticker: string }> },
) {
  await requireAuthenticatedUser();
  const { ticker } = await params;
  // published=1: la descarga es siempre la ultima version PUBLICADA. Un
  // borrador no enseña cifras ni margen (regla vigente de la app).
  const memo = await fetchMemoMarkdown({
    tickerRaw: ticker,
    query: 'published=1',
    notFoundError: 'Aún no hay ninguna tesis publicada de este ticker',
    unavailableError: 'Memo no disponible',
  });
  if (!memo.ok) return memo.response;
  const disposition =
    memo.contentDisposition ??
    `attachment; filename="tesis-${ticker.toLowerCase()}.md"`;
  return new NextResponse(memo.markdown, {
    status: 200,
    headers: {
      'Content-Type': 'text/markdown; charset=utf-8',
      'Content-Disposition': disposition,
    },
  });
}

export const GET = withAuthErrors(getHandler);
