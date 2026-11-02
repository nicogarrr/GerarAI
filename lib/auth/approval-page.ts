import { NextResponse } from 'next/server';

import type { Locale } from '@/lib/i18n/locale';

/** Escapa texto interpolado en las páginas HTML de administración. */
export function escapeHtml(value: string): string {
    return value
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

/** Esqueleto HTML de las páginas de aprobación de cuentas (listado admin y
 *  decisión): mismo head, mismo título escapado y mismas cabeceras; cada
 *  página solo elige su ancho. */
export function approvalPage(title: string, bodyHtml: string, status: number, locale: Locale, maxWidth: string): NextResponse {
    const html = [
        `<!doctype html><html lang="${locale}"><head><meta charset="utf-8">`,
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        `<title>${escapeHtml(title)} - GerarAI</title></head>`,
        `<body style="font-family: system-ui, sans-serif; max-width: ${maxWidth}; margin: 4rem auto; padding: 0 1rem;">`,
        `<h1>${escapeHtml(title)}</h1>`,
        bodyHtml,
        '</body></html>',
    ].join('');
    return new NextResponse(html, {
        status,
        headers: { 'content-type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' },
    });
}
