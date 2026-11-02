import { NextResponse } from 'next/server';

import { researchIdentityHeaders } from '@/lib/auth/research-identity';

const BACKEND_URL = process.env.FMP_BACKEND_URL;

export type MemoMarkdown =
  | { ok: true; markdown: string; contentDisposition: string | null }
  | { ok: false; response: NextResponse };

/** Descarga firmada del memo Markdown canónico del backend (la identidad
 *  research nunca llega al navegador). Las rutas .md y .pdf compartían la
 *  validación del ticker, el 503 sin backend, la firma y el mapeo de
 *  errores; aquí viven una sola vez y cada ruta elige su query
 *  (published/draft) y su salida. */
export async function fetchMemoMarkdown(args: {
  tickerRaw: string;
  query: 'published=1' | 'draft=1';
  notFoundError: string;
  unavailableError: string;
}): Promise<MemoMarkdown> {
  const { tickerRaw, query, notFoundError, unavailableError } = args;
  if (!/^[A-Za-z0-9.^=-]{1,15}$/.test(tickerRaw)) {
    return { ok: false, response: NextResponse.json({ error: 'Ticker no valido' }, { status: 400 }) };
  }
  if (!BACKEND_URL) {
    return { ok: false, response: NextResponse.json({ error: 'Backend no configurado' }, { status: 503 }) };
  }
  const path = `/api/thesis/${encodeURIComponent(tickerRaw.toUpperCase())}/memo.md`;
  const identity = await researchIdentityHeaders({ method: 'GET', path });
  const upstream = await fetch(
    `${BACKEND_URL}/api/thesis/${encodeURIComponent(tickerRaw.toUpperCase())}/memo.md?${query}`,
    { headers: identity, cache: 'no-store' },
  );
  if (!upstream.ok) {
    return {
      ok: false,
      response: NextResponse.json(
        { error: upstream.status === 404 ? notFoundError : unavailableError },
        { status: upstream.status },
      ),
    };
  }
  return { ok: true, markdown: await upstream.text(), contentDisposition: upstream.headers.get('content-disposition') };
}
