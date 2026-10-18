import { NextResponse } from 'next/server';
import { withAuthErrors } from '@/lib/auth/route-auth';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { AppError } from '@/lib/types/errors';
import { researchRequest } from '@/lib/research/client';

async function getHandler(_request: Request, { params }: { params: Promise<{ eventId: string }> }) {
  await requireAuthenticatedUser();
  const { eventId } = await params;
  if (!/^[1-9]\d*$/.test(eventId) || !Number.isSafeInteger(Number(eventId))) {
    return NextResponse.json({ status: 'unavailable' }, { status: 400 });
  }
  try {
    const data = await researchRequest<unknown>(`/api/news/${eventId}/second-order?use_llm=true`, {
      cache: 'no-store',
      timeoutMs: 55_000,
    });
    return NextResponse.json(data);
  } catch (error) {
    if (error instanceof AppError && error.statusCode === 404) {
      return NextResponse.json({ status: 'not_found', detail: 'Noticia no encontrada' }, { status: 404 });
    }
    return NextResponse.json({ status: 'unavailable' }, { status: 502 });
  }
}

export const GET = withAuthErrors(getHandler);
