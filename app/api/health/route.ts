import { NextResponse } from 'next/server';

/**
 * Sonda de vida del frontend en Vercel (liveness): 200 con un JSON mínimo
 * mientras el proceso sirva peticiones. Sin sesión, sin base de datos, sin
 * secretos ni llamadas a terceros: cualquier dependencia haría que una caída
 * ajena tumbase también la sonda. Pública a propósito (el middleware ya deja
 * fuera /api/*): la usan el balanceador y la monitorización.
 */
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export function GET() {
    return NextResponse.json(
        { estado: 'ok', marca: new Date().toISOString() },
        { headers: { 'Cache-Control': 'no-store' } },
    );
}
