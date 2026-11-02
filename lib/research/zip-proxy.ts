import { NextResponse } from 'next/server';

import { researchIdentityHeaders } from '@/lib/auth/research-identity';

const BACKEND_URL = process.env.FMP_BACKEND_URL ?? 'http://localhost:8000';

/** Proxy privado de una descarga .zip del backend Research OS: la firma
 *  nunca llega al navegador. Las dos rutas .zip (vault completo y tesis por
 *  ticker) compartían esta mecánica copiada: fetch firmado con deadline,
 *  502 honesto si el motor no responde o la descarga se corta, y cabeceras
 *  de adjunto privado. Aquí vive una sola vez; cada ruta aporta su path, su
 *  nombre de archivo y sus mensajes de error. */
export async function proxyZipDownload(args: {
    /** Ruta del backend (literal en la ruta, nunca del cliente: sin SSRF). */
    path: string;
    filename: string;
    /** Detalle cuando el backend responde no-OK (salvo el 404 con mensaje propio). */
    exportErrorDetail: string;
    /** Si se indica, un 404 del backend se responde con este detalle en 404. */
    notFoundDetail?: string;
}): Promise<NextResponse> {
    const { path, filename, exportErrorDetail, notFoundDetail } = args;
    let upstream: Response;
    try {
        upstream = await fetch(new URL(path, BACKEND_URL), {
            headers: await researchIdentityHeaders({ method: 'GET', path }),
            cache: 'no-store',
            signal: AbortSignal.timeout(45_000),
        });
    } catch {
        return NextResponse.json({ detail: 'Motor de research no disponible' }, { status: 502 });
    }
    if (upstream.status === 404 && notFoundDetail) {
        return NextResponse.json({ detail: notFoundDetail }, { status: 404 });
    }
    if (!upstream.ok) {
        return NextResponse.json({ detail: exportErrorDetail }, { status: upstream.status });
    }
    let content: ArrayBuffer;
    try {
        content = await upstream.arrayBuffer();
    } catch {
        return NextResponse.json({ detail: 'La descarga se interrumpió. Vuelve a intentarlo.' }, { status: 502 });
    }
    return new NextResponse(content, {
        headers: {
            'content-type': 'application/zip',
            'content-disposition': `attachment; filename="${filename}"`,
            'cache-control': 'private, no-store',
            'x-content-type-options': 'nosniff',
        },
    });
}
