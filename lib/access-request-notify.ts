import { buildNotification, notifyTarget, smtpConfig, type AccessRequestInput } from '@/lib/access-request';
import { createSmtpTransport } from '@/lib/smtp-transport';

/**
 * Avisa por correo de una solicitud nueva. Devuelve true solo si el correo SALIO.
 *
 * Sin destino o sin credencial SMTP devuelve false: la solicitud ya esta guardada
 * (coleccion `access_requests`, `notifiedAt` nulo) y nada finge que se haya
 * enviado un correo. Un fallo del servidor de correo tambien devuelve false.
 */
export async function notifyAccessRequest(req: AccessRequestInput, total: number): Promise<boolean> {
    const to = notifyTarget(process.env);
    const smtp = smtpConfig(process.env);
    if (!to || !smtp) return false;
    const { subject, text } = buildNotification(req, total);
    try {
        const transport = createSmtpTransport(smtp);
        await transport.sendMail({ from: smtp.from, to, replyTo: req.email, subject, text });
        return true;
    } catch (error) {
        console.error('Access request notification failed:', error instanceof Error ? error.message : error);
        return false;
    }
}
