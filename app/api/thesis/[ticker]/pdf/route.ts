import { withAuthErrors } from '@/lib/auth/route-auth';
import { NextRequest, NextResponse } from 'next/server';
import { researchIdentityHeaders } from '@/lib/auth/research-identity';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { buildMemoPdf } from '@/lib/thesis/memo-pdf';

const BACKEND_URL = process.env.FMP_BACKEND_URL;

/**
 * Borrador: sin cifras ni margen (regla vigente). Se quita la seccion de
 * valoracion y se marca el documento como borrador sin publicar.
 */
function asDraftMemo(markdown: string): string {
  const lines = markdown.split('\n');
  const out: string[] = [];
  let skipping = false;
  for (const line of lines) {
    if (line.startsWith('## ')) skipping = line.trim() === '## Valoración y escenarios';
    if (!skipping) out.push(line);
  }
  const titleEnd = out.findIndex((line) => line.startsWith('# '));
  out.splice(titleEnd + 1, 0, '', '> BORRADOR sin publicar. No incluye cifras de valoración ni margen de seguridad.');
  return out.join('\n');
}

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
  if (!/^[A-Za-z0-9.^=-]{1,15}$/.test(ticker)) {
    return NextResponse.json({ error: 'Ticker no valido' }, { status: 400 });
  }
  if (!BACKEND_URL) {
    return NextResponse.json({ error: 'Backend no configurado' }, { status: 503 });
  }
  const draft = request.nextUrl.searchParams.get('draft') === '1';
  const upper = ticker.toUpperCase();
  const identity = await researchIdentityHeaders({
    method: 'GET',
    path: `/api/thesis/${encodeURIComponent(upper)}/memo.md`,
  });
  const upstream = await fetch(
    `${BACKEND_URL}/api/thesis/${encodeURIComponent(upper)}/memo.md${draft ? '' : '?published=1'}`,
    { headers: identity, cache: 'no-store' },
  );
  if (!upstream.ok) {
    return NextResponse.json(
      { error: upstream.status === 404 ? (draft ? 'Aún no hay ninguna tesis de este ticker' : 'Aún no hay ninguna tesis publicada de este ticker') : 'PDF no disponible' },
      { status: upstream.status },
    );
  }
  const markdown = draft ? asDraftMemo(await upstream.text()) : await upstream.text();
  const pdf = await buildMemoPdf(markdown);
  const version = markdown.match(/^Versión (\d+)/m)?.[1];
  const filename = `tesis-${ticker.toLowerCase()}${version ? `-v${version}` : ''}${draft ? '-borrador' : ''}.pdf`;
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
