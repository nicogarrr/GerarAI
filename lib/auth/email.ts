
import { smtpConfig } from '@/lib/access-request';
import { createSmtpTransport } from '@/lib/smtp-transport';
import { getT } from '@/lib/i18n/server';

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
    // i18n B: el correo sale en el idioma de la peticion (cookie gerarai_locale).
    const t = await getT();
    const greeting = args.name?.trim()
        ? t('emails.passwordReset.greetingNamed', { name: args.name.trim() })
        : t('emails.passwordReset.greeting');
    const transport = createSmtpTransport(smtp);
    await transport.sendMail({
        from: smtp.from,
        to: args.to,
        subject: t('emails.passwordReset.subject'),
        text: [
            greeting,
            '',
            t('emails.passwordReset.body'),
            t('emails.passwordReset.linkIntro'),
            args.url,
            '',
            t('emails.passwordReset.ignore'),
            '',
            t('emails.passwordReset.noAsk'),
        ].join('\n'),
    });
}
