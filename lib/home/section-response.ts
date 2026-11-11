import { NextResponse } from 'next/server';
import { sectionErrorKey } from '@/lib/section-error';

/**
 * Respuesta JSON {data, error} de una sección del inicio.
 *
 * Cada sección tiene su route handler propio (app/api/home/*) porque las
 * server actions de un cliente se ejecutan en SERIE y un único POST
 * agrupado devolvía las tres secciones a la vez: la más rápida esperaba a
 * la más lenta (medido en prod, 11-nov-2026: cartera lista a los 64 ms,
 * respuesta a los 344 ms por la watchlist). Con fetch paralelos cada
 * sección pinta en cuanto llega y un fallo se queda en su sección (misma
 * clave genérica por categoría que antes; el texto lo resuelve el cliente
 * con t()).
 */
export async function sectionResponse<T>(read: () => Promise<T>, fallback: T): Promise<NextResponse> {
    const headers = { 'Cache-Control': 'no-store' };
    try {
        return NextResponse.json({ data: await read(), error: null }, { headers });
    } catch (error) {
        return NextResponse.json({ data: fallback, error: sectionErrorKey(error) }, { headers });
    }
}
