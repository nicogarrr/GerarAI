import { NextResponse } from 'next/server';

import { researchIdentityHeaders } from '@/lib/auth/research-identity';

/** Proxy privado de un POST JSON del backend Research OS (la firma nunca
 *  llega al navegador). Las tres rutas de traducción de noticias copiaban
 *  esta mecánica: fetch firmado con deadline, {status:'unavailable'} con el
 *  status del motor cuando responde no-OK, y 502 honesto si no responde o el
 *  JSON llega roto. Aquí vive una sola vez; cada ruta valida su entrada y
 *  aporta su path, su timeout y su body opcional. */
export async function proxyResearchPost(args: { path: string; timeoutMs: number; body?: string }): Promise<NextResponse> {
  const { path, timeoutMs, body } = args;
  try {
    const response = await fetch(`${process.env.FMP_BACKEND_URL ?? 'http://localhost:8000'}${path}`, {
      method: 'POST', body, headers: {...await researchIdentityHeaders({method:'POST',path,body}), ...(body ? {'Content-Type':'application/json'} : {})},
      cache:'no-store', signal:AbortSignal.timeout(timeoutMs),
    });
    if (!response.ok) return NextResponse.json({status:'unavailable'}, {status:response.status});
    return NextResponse.json(await response.json());
  } catch {
    return NextResponse.json({status:'unavailable'}, {status:502});
  }
}
