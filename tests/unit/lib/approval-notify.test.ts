import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { createTransport, sendMail } = vi.hoisted(() => ({
    createTransport: vi.fn(),
    sendMail: vi.fn(),
}));
vi.mock('nodemailer', () => ({ default: { createTransport } }));

import {
    buildApprovalLinks,
    notifyAccountApproved,
    notifyPendingAccount,
    publicBaseUrl,
} from '@/lib/auth/approval-notify';
import { verifyAdminListToken, verifyDecisionToken } from '@/lib/auth/account-approval';

const SECRET = 'test-secret-de-al-menos-32-caracteres';
const ENV_KEYS = ['BETTER_AUTH_URL', 'VERCEL_URL', 'ACCESS_REQUEST_NOTIFY_EMAIL', 'SMTP_USER', 'SMTP_PASS', 'SMTP_HOST', 'SMTP_PORT', 'MAIL_FROM'];
let saved: Record<string, string | undefined> = {};

beforeEach(() => {
    vi.clearAllMocks();
    saved = Object.fromEntries(ENV_KEYS.map((k) => [k, process.env[k]]));
    for (const k of ENV_KEYS) delete process.env[k];
    createTransport.mockReturnValue({ sendMail });
    sendMail.mockResolvedValue({});
});

afterEach(() => {
    for (const k of ENV_KEYS) {
        if (saved[k] === undefined) delete process.env[k];
        else process.env[k] = saved[k];
    }
});

describe('publicBaseUrl', () => {
    it('BETTER_AUTH_URL manda; VERCEL_URL recibe protocolo; localhost de último recurso', () => {
        expect(publicBaseUrl({ BETTER_AUTH_URL: 'https://app.gerarai.com/' })).toBe('https://app.gerarai.com');
        expect(publicBaseUrl({ VERCEL_URL: 'gerarai.vercel.app' })).toBe('https://gerarai.vercel.app');
        expect(publicBaseUrl({})).toBe('http://localhost:3000');
    });
});

describe('buildApprovalLinks', () => {
    it('los tres enlaces llevan tokens verificables con el secreto', () => {
        process.env.BETTER_AUTH_URL = 'https://app.gerarai.com';
        const links = buildApprovalLinks({ approvalId: '507f1f77bcf86cd799439011', secret: SECRET });
        const tokenOf = (url: string) => new URL(url).searchParams.get('token');
        expect(links.approve).toMatch(/^https:\/\/app\.gerarai\.com\/api\/admin\/approvals\/decide\?token=/);
        expect(verifyDecisionToken(tokenOf(links.approve), SECRET)?.action).toBe('approve');
        expect(verifyDecisionToken(tokenOf(links.reject), SECRET)?.action).toBe('reject');
        expect(verifyAdminListToken(tokenOf(links.list), SECRET)).toBe(true);
        expect(new URL(links.list).pathname).toBe('/api/admin/approvals');
    });
});

describe('notifyPendingAccount (fail-closed honesto)', () => {
    it('sin correo destino configurado: false y ni intenta enviar', async () => {
        process.env.SMTP_USER = 'u@gmail.com';
        process.env.SMTP_PASS = 'pass-de-app';
        const sent = await notifyPendingAccount({ approvalId: 'x', email: 'nuevo@e.co', name: 'N', secret: SECRET });
        expect(sent).toBe(false);
        expect(createTransport).not.toHaveBeenCalled();
    });

    it('sin SMTP_PASS (estado actual de la VM): false y ni intenta enviar', async () => {
        process.env.ACCESS_REQUEST_NOTIFY_EMAIL = 'nico@e.co';
        process.env.SMTP_USER = 'u@gmail.com';
        const sent = await notifyPendingAccount({ approvalId: 'x', email: 'nuevo@e.co', name: 'N', secret: SECRET });
        expect(sent).toBe(false);
        expect(createTransport).not.toHaveBeenCalled();
    });

    it('con todo configurado: envía a Nico con el email del registrado y devuelve true', async () => {
        process.env.ACCESS_REQUEST_NOTIFY_EMAIL = 'nico@e.co';
        process.env.SMTP_USER = 'u@gmail.com';
        process.env.SMTP_PASS = 'pass-de-app';
        process.env.BETTER_AUTH_URL = 'https://app.gerarai.com';
        const sent = await notifyPendingAccount({ approvalId: '507f1f77bcf86cd799439011', email: 'nuevo@e.co', name: 'Nuevo', secret: SECRET });
        expect(sent).toBe(true);
        expect(sendMail).toHaveBeenCalledTimes(1);
        const mail = sendMail.mock.calls[0][0];
        expect(mail.to).toBe('nico@e.co');
        expect(mail.subject).toContain('nuevo@e.co');
        expect(mail.text).toContain('/api/admin/approvals/decide?token=');
        expect(mail.text).toContain('/api/admin/approvals?token=');
    });

    it('si el servidor de correo falla: false, nunca una excepción que tumbe el alta', async () => {
        process.env.ACCESS_REQUEST_NOTIFY_EMAIL = 'nico@e.co';
        process.env.SMTP_USER = 'u@gmail.com';
        process.env.SMTP_PASS = 'pass-de-app';
        sendMail.mockRejectedValue(new Error('SMTP caído'));
        vi.spyOn(console, 'error').mockImplementation(() => {});
        const sent = await notifyPendingAccount({ approvalId: 'x', email: 'nuevo@e.co', name: 'N', secret: SECRET });
        expect(sent).toBe(false);
    });
});

describe('notifyAccountApproved (el copy de pending promete avisar al usuario)', () => {
    it('sin SMTP configurado: false honesto, ni intenta enviar', async () => {
        const sent = await notifyAccountApproved({ email: 'nuevo@e.co', name: 'Nuevo' });
        expect(sent).toBe(false);
        expect(createTransport).not.toHaveBeenCalled();
    });

    it('con SMTP: avisa al USUARIO (no a Nico) con el enlace de entrada', async () => {
        process.env.SMTP_USER = 'u@gmail.com';
        process.env.SMTP_PASS = 'pass-de-app';
        process.env.BETTER_AUTH_URL = 'https://app.gerarai.com';
        const sent = await notifyAccountApproved({ email: 'nuevo@e.co', name: 'Nuevo' });
        expect(sent).toBe(true);
        const mail = sendMail.mock.calls[0][0];
        expect(mail.to).toBe('nuevo@e.co');
        expect(mail.text).toContain('https://app.gerarai.com/sign-in');
    });

    it('si el envío falla: false, nunca excepción que tumbe la aprobación', async () => {
        process.env.SMTP_USER = 'u@gmail.com';
        process.env.SMTP_PASS = 'pass-de-app';
        sendMail.mockRejectedValue(new Error('SMTP caído'));
        vi.spyOn(console, 'error').mockImplementation(() => {});
        expect(await notifyAccountApproved({ email: 'nuevo@e.co', name: 'N' })).toBe(false);
    });
});
