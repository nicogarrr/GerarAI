import nodemailer from 'nodemailer';

import { smtpConfig } from '@/lib/access-request';

/**
 * SMTP es opcional: mientras no haya SMTP_USER/SMTP_PASS, /sign-in y
 * /security muestran un estado honesto y no prometen un correo que no sale.
 */
export function isPasswordResetEmailConfigured(
    env: Record<string, string | undefined> = process.env,
): boolean {
    return smtpConfig(env) !== null;
}

export async function sendPasswordResetEmail(args: {
    to: string;
    name?: string | null;
    url: string;
}): Promise<void> {
    const smtp = smtpConfig(process.env);
    if (!smtp) {
        throw new Error('SMTP is not configured');
    }
    const greeting = args.name?.trim() ? `Hola ${args.name.trim()},` : 'Hola,';
    const transport = nodemailer.createTransport({
        host: smtp.host,
        port: smtp.port,
        secure: smtp.port === 465,
        auth: { user: smtp.user, pass: smtp.pass },
        connectionTimeout: 8000,
        greetingTimeout: 8000,
        socketTimeout: 10000,
    });
    await transport.sendMail({
        from: smtp.from,
        to: args.to,
        subject: 'Restablece tu contraseña de GerarAI',
        text: [
            greeting,
            '',
            'Hemos recibido una solicitud para restablecer la contraseña de tu cuenta de GerarAI.',
            'Abre este enlace (caduca pronto y solo se puede usar una vez):',
            args.url,
            '',
            'Si no has pedido el cambio, ignora este correo: tu contraseña actual sigue siendo válida.',
            '',
            'GerarAI no te pedirá la contraseña por correo.',
        ].join('\n'),
    });
}
