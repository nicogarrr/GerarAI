import { withAuthErrors } from '@/lib/auth/route-auth';
import { NextResponse } from 'next/server';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { proxyResearchPost } from '@/lib/research/post-proxy';

async function postHandler(_request: Request, { params }: { params: Promise<{ eventId: string }> }) {
  await requireAuthenticatedUser();
  const { eventId } = await params;
  if (!/^[1-9]\d*$/.test(eventId) || !Number.isSafeInteger(Number(eventId))) return NextResponse.json({status:'unavailable'}, {status:400});
  // El resumen es más largo que el titular: margen acorde al timeout del motor (12s).
  return proxyResearchPost({ path: `/api/news/${eventId}/translation/summary`, timeoutMs: 15000 });
}

export const POST = withAuthErrors(postHandler);
