import { withAuthErrors } from '@/lib/auth/route-auth';
import { NextRequest, NextResponse } from 'next/server';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { buildMemoPdf } from '@/lib/thesis/memo-pdf';
import { fetchMemoMarkdown } from '@/lib/thesis/fetch-memo';

/**
 * PDF de lectura de la tesis PUBLICADA. Mismo contrato que el .md: el
 * backend compone el memo canonico (published=1) y aqui solo se maqueta;
 * un borrador nunca lleva cifras ni margen (404 si no hay publicada).
 */
async function getHandler(
  request: NextRequest,
  { params }: { params: Promise<{ ticker: string }> },
) {
  await requireAuthenticatedUser();
  const { ticker } = await params;
  const draft = request.nextUrl.searchParams.get('draft') === '1';
  const memo = await fetchMemoMarkdown({
    tickerRaw: ticker,
    query: draft ? 'draft=1' : 'published=1',
    notFoundError: draft ? 'Aún no hay ninguna tesis de este ticker' : 'Aún no hay ninguna tesis publicada de este ticker',
    unavailableError: 'PDF no disponible',
  });
  if (!memo.ok) return memo.response;
  const markdown = memo.markdown;
  const pdf = await buildMemoPdf(markdown);
  // «Versión N» (castellano) o «Version N» (memo en inglés, Ajustes).
  const version = markdown.match(/^Versi[oó]n (\d+)/m)?.[1];
  // Memo en inglés (Ajustes): el nombre del fichero también («thesis-…-draft»).
  const english = markdown.startsWith('# Thesis memo');
  const prefix = english ? 'thesis' : 'tesis';
  const draftSuffix = draft ? (english ? '-draft' : '-borrador') : '';
  const filename = `${prefix}-${ticker.toLowerCase()}${version ? `-v${version}` : ''}${draftSuffix}.pdf`;
  return new NextResponse(new Uint8Array(pdf), {
    status: 200,
    headers: {
      'Content-Type': 'application/pdf',
      'Content-Disposition': `attachment; filename="${filename}"`,
      'Cache-Control': 'no-store',
    },
  });
}

export const GET = withAuthErrors(getHandler);
