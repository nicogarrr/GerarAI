import { NextResponse } from 'next/server';

/**
 * Red de seguridad para rutas de API inexistentes. Sin ella, Next sirve el
 * not-found HTML de las páginas y un cliente de API (sondas, el backend,
 * integraciones) recibe kilobytes de HTML en vez de un error parseable.
 * Las rutas reales (app/api/<ruta>/route.ts) tienen prioridad sobre esta
 * catch-all, así que solo responde a lo que no existe.
 */
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

function notFound() {
    return NextResponse.json(
        { error: 'Ruta de API no encontrada.' },
        { status: 404, headers: { 'Cache-Control': 'no-store' } },
    );
}

// HEAD lo atiende el propio Next reutilizando GET. Se declaran los métodos
// habituales: sin ellos una ruta inexistente diría 405 como si existiera.
export { notFound as GET, notFound as POST, notFound as PUT, notFound as PATCH, notFound as DELETE };
