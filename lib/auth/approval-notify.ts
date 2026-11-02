
import { notifyTarget, smtpConfig } from '@/lib/access-request';
import { createSmtpTransport } from '@/lib/smtp-transport';
import {
    adminListTokenTtlMs,
    approvalTokenTtlMs,
    createAdminListToken,
    createDecisionToken,
} from '@/lib/auth/account-approval';
import { singleLineName } from '@/lib/auth/profile-input';

/**
 * Base pública para los enlaces del correo. Replica la preferencia de
 * lib/better-auth/auth.ts (BETTER_AUTH_URL > VERCEL_URL > localhost); a
 * VERCEL_URL le falta el protocolo, así que se lo ponemos.
 */
export function publicBaseUrl(env: Record<string, string | undefined>): string {
    const configured = (env.BETTER_AUTH_URL ?? '').trim();
    if (configured) return configured.replace(/\/$/, '');
    const vercel = (env.VERCEL_URL ?? '').trim();
    if (vercel) return `https://${vercel.replace(/^https?:\/\//, '').replace(/\/$/, '')}`;
    return 'http://localhost:3000';
}

export function buildApprovalLinks(args: {
    approvalId: string;
    secret: string;
    env?: Record<string, string | undefined>;
}): { approve: string; reject: string; list: string } {
    const env = args.env ?? process.env;
    const base = publicBaseUrl(env);
    const decisionTtl = approvalTokenTtlMs(env);
    const approve = createDecisionToken({
        approvalId: args.approvalId, action: 'approve', secret: args.secret, ttlMs: decisionTtl,
    });
    const reject = createDecisionToken({
        approvalId: args.approvalId, action: 'reject', secret: args.secret, ttlMs: decisionTtl,
    });
    const list = createAdminListToken({ secret: args.secret, ttlMs: adminListTokenTtlMs(env) });
    return {
        approve: `${base}/api/admin/approvals/decide?token=${approve}`,
        reject: `${base}/api/admin/approvals/decide?token=${reject}`,
        list: `${base}/api/admin/approvals?token=${list}`,
    };
}

/**
 * Avisa a Nico de una cuenta nueva pendiente. Devuelve true solo si el
 * correo SALIO. Sin destinatario o sin SMTP devuelve false y nada finge un
 * envío: la cuenta sigue pendiente (fail-closed) y el respaldo es el listado
 * /api/admin/approvals (notifiedAt queda null en account_approvals).
 */
export async function notifyPendingAccount(args: {
    approvalId: string;
    email: string;
    name?: string | null;
    secret: string;
}): Promise<boolean> {
    const to = notifyTarget(process.env);
    const smtp = smtpConfig(process.env);
    if (!to || !smtp) return false;
    const links = buildApprovalLinks({ approvalId: args.approvalId, secret: args.secret });
    // Una sola línea: un nombre con saltos colaba un «Aprobar:» falso en este correo.
    const displayName = singleLineName(args.name) || '(sin nombre)';
    try {
        const transport = createSmtpTransport(smtp);
        await transport.sendMail({
            from: smtp.from,
            to,
            subject: `GerarAI: nueva cuenta pendiente (${args.email})`,
            text: [
                `Nueva cuenta pendiente de aprobación:`,
                '',
                `Nombre: ${displayName}`,
                `Email: ${args.email}`,
                '',
                `Aprobar: ${links.approve}`,
                `Rechazar: ${links.reject}`,
                '',
                `Los enlaces son de un solo uso y caducan. Listado de pendientes (respaldo):`,
                links.list,
            ].join('\n'),
        });
        return true;
    } catch (error) {
        console.error('Pending account notification failed:', error instanceof Error ? error.message : error);
        return false;
    }
}

/**
 * Aviso al usuario cuando Nico APRUEBA su cuenta (el copy de cuenta pendiente
 * promete "te avisaremos por email": hay que cumplirlo). Mismo SMTP y mismo
 * fail-closed honesto: sin configuración devuelve false y la aprobación
 * cuenta igualmente (quien aprueba ve en la página si el aviso salió).
 */
export async function notifyAccountApproved(args: {
    email: string;
    name?: string | null;
}): Promise<boolean> {
    const smtp = smtpConfig(process.env);
    if (!smtp) return false;
    const base = publicBaseUrl(process.env);
    const name = singleLineName(args.name);
    const greeting = name ? `Hola, ${name}:` : 'Hola:';
    try {
        const transport = createSmtpTransport(smtp);
        await transport.sendMail({
            from: smtp.from,
            to: args.email,
            subject: 'Tu cuenta de GerarAI ya está activa',
            text: [
                greeting,
                '',
                'Tu cuenta de GerarAI ha sido aprobada. Ya puedes entrar:',
                `${base}/sign-in`,
                '',
                'Si no pediste esta cuenta, ignora este correo.',
            ].join('\n'),
        });
        return true;
    } catch (error) {
        console.error('Approved account notification failed:', error instanceof Error ? error.message : error);
        return false;
    }
}
