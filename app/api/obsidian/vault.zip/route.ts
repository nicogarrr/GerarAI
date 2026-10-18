import { withAuthErrors } from '@/lib/auth/route-auth';
import { NextResponse } from 'next/server';
import { researchIdentityHeaders } from '@/lib/auth/research-identity';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';

const BACKEND_URL = process.env.FMP_BACKEND_URL ?? 'http://localhost:8000';

/** Proxy privado: la firma Research OS nunca llega al navegador. */
async function getHandler() {
  await requireAuthenticatedUser();
  const path = '/api/obsidian/vault.zip';
  let upstream: Response;
  try {
    upstream = await fetch(new URL(path, BACKEND_URL), {
      headers: await researchIdentityHeaders({ method: 'GET', path }),
      cache: 'no-store',
    });
  } catch {
    return NextResponse.json({ detail: 'Motor de research no disponible' }, { status: 502 });
  }
  if (!upstream.ok) {
    return NextResponse.json({ detail: 'No se pudo exportar el vault de Obsidian' }, { status: upstream.status });
  }
  return new NextResponse(await upstream.arrayBuffer(), {
    headers: {
      'content-type': 'application/zip',
      'content-disposition': 'attachment; filename="gerarai-obsidian-vault.zip"',
      'cache-control': 'private, no-store',
      'x-content-type-options': 'nosniff',
    },
  });
}

export const GET = withAuthErrors(getHandler);
