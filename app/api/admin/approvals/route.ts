import { NextRequest, NextResponse } from 'next/server';

import { connectToDatabase } from '@/database/mongoose';
import { AccountApproval } from '@/database/models/account-approval.model';
import { verifyAdminListToken } from '@/lib/auth/account-approval';
import { buildApprovalLinks } from '@/lib/auth/approval-notify';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * Respaldo admin de Nico: listado de cuentas pendientes con sus enlaces
 * aprobar/rechazar. Va enlazado en cada correo de aviso y sirve cuando un
 * aviso concreto se pierde o el SMTP falló después (fail-closed: sin correo
 * nadie entra, pero Nico puede seguir aprobando desde aquí).
 *
 * Sin sesión: lo protege el token HMAC del enlace (7 días por defecto), no
 * una cookie. Cada enlace de decisión que muestra es de un solo uso (ver
 * app/api/admin/approvals/decide/route.ts).
 */

function escapeHtml(value: string): string {
    return value
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function page(title: string, bodyHtml: string, status: number): NextResponse {
    const html = [
        '<!doctype html><html lang="es"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        `<title>${escapeHtml(title)} - GerarAI</title></head>`,
        '<body style="font-family: system-ui, sans-serif; max-width: 40rem; margin: 4rem auto; padding: 0 1rem;">',
        `<h1>${escapeHtml(title)}</h1>`,
        bodyHtml,
        '</body></html>',
    ].join('');
    return new NextResponse(html, {
        status,
        headers: { 'content-type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' },
    });
}

export async function GET(request: NextRequest) {
    const secret = process.env.BETTER_AUTH_SECRET;
    if (!verifyAdminListToken(request.nextUrl.searchParams.get('token'), secret)) {
        return page('Enlace no válido o caducado', '<p>Este enlace del listado no es válido o ha caducado.</p>', 400);
    }
    if (!secret) {
        return page('Servicio no disponible', '<p>Falta la configuración del servidor.</p>', 503);
    }

    await connectToDatabase();
    // Pendientes de decisión Y decididas sin aplicar (ventana de crash: la
    // reconciliación también se ofrece desde aquí).
    const pendings = await AccountApproval.find({ $or: [{ decidedAt: null }, { appliedAt: null }] })
        .sort({ createdAt: -1 })
        .limit(50)
        .lean();

    if (pendings.length === 0) {
        return page('Cuentas pendientes', '<p>No hay cuentas pendientes de aprobación.</p>', 200);
    }
    const items = pendings.map((p) => {
        const links = buildApprovalLinks({ approvalId: String(p._id), secret });
        const email = escapeHtml(p.email);
        const name = escapeHtml(p.name || '(sin nombre)');
        const date = p.createdAt ? new Date(p.createdAt).toISOString().slice(0, 16).replace('T', ' ') : '';
        if (p.decidedAt) {
            const apply = p.decision === 'approved' ? links.approve : links.reject;
            return `<li style="margin-bottom: 1.5rem;"><strong>${email}</strong> (${name}, ${date})<br>` +
                `Ya ${p.decision === 'approved' ? 'aprobada' : 'rechazada'}, falta aplicar: <a href="${apply}">Aplicar la decisión</a></li>`;
        }
        return `<li style="margin-bottom: 1.5rem;"><strong>${email}</strong> (${name}, ${date})<br>` +
            `<a href="${links.approve}">Aprobar</a> &middot; <a href="${links.reject}">Rechazar</a></li>`;
    });
    return page('Cuentas pendientes', `<ul style="list-style: none; padding: 0;">${items.join('')}</ul>`, 200);
}
