import { withAuthErrors } from '@/lib/auth/route-auth';
import { NextResponse } from 'next/server';
import { researchIdentityHeaders } from '@/lib/auth/research-identity';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';

async function postHandler(_request: Request, { params }: { params: Promise<{ eventId: string }> }) {
  await requireAuthenticatedUser();
  const { eventId } = await params;
  if (!/^[1-9]\d*$/.test(eventId) || !Number.isSafeInteger(Number(eventId))) return NextResponse.json({status:'unavailable'}, {status:400});
  const path = `/api/news/${eventId}/translation/summary`;
  try {
    // El resumen es más largo que el titular: margen acorde al timeout del motor (12s).
    const response = await fetch(`${process.env.FMP_BACKEND_URL ?? 'http://localhost:8000'}${path}`, {
      method: 'POST', headers: await researchIdentityHeaders({method:'POST',path}),
      cache:'no-store', signal:AbortSignal.timeout(15000),
    });
    if (!response.ok) return NextResponse.json({status:'unavailable'}, {status:response.status});
    return NextResponse.json(await response.json());
  } catch {
    return NextResponse.json({status:'unavailable'}, {status:502});
  }
}

export const POST = withAuthErrors(postHandler);
