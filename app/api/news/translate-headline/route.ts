import { withAuthErrors } from '@/lib/auth/route-auth';
import { NextResponse } from 'next/server';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { proxyResearchPost } from '@/lib/research/post-proxy';

async function postHandler(request: Request) {
  await requireAuthenticatedUser();
  let headline: unknown;
  try { headline = (await request.json()).headline; } catch { return NextResponse.json({status:'unavailable'}, {status:400}); }
  if (typeof headline !== 'string' || headline.length < 3 || headline.length > 500) return NextResponse.json({status:'unavailable'}, {status:400});
  return proxyResearchPost({ path: '/api/news/translate-headline', timeoutMs: 12000, body: JSON.stringify({headline}) });
}

export const POST = withAuthErrors(postHandler);
