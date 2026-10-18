import { withAuthErrors } from '@/lib/auth/route-auth';
import { NextResponse } from 'next/server';
import { researchIdentityHeaders } from '@/lib/auth/research-identity';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';

async function postHandler(request: Request) {
  await requireAuthenticatedUser();
  let headline: unknown;
  try { headline = (await request.json()).headline; } catch { return NextResponse.json({status:'unavailable'}, {status:400}); }
  if (typeof headline !== 'string' || headline.length < 3 || headline.length > 500) return NextResponse.json({status:'unavailable'}, {status:400});
  const path = '/api/news/translate-headline';
  const body = JSON.stringify({headline});
  try {
    const response = await fetch(`${process.env.FMP_BACKEND_URL ?? 'http://localhost:8000'}${path}`, {
      method: 'POST', body, headers: {...await researchIdentityHeaders({method:'POST',path,body}), 'Content-Type':'application/json'},
      cache:'no-store', signal:AbortSignal.timeout(12000),
    });
    if (!response.ok) return NextResponse.json({status:'unavailable'}, {status:response.status});
    return NextResponse.json(await response.json());
  } catch {
    return NextResponse.json({status:'unavailable'}, {status:502});
  }
}

export const POST = withAuthErrors(postHandler);
