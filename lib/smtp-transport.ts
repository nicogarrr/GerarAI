import nodemailer from 'nodemailer';

import type { SmtpConfig } from '@/lib/access-request';

/** Transporte SMTP único de la app: mismas credenciales (smtpConfig) y
 *  mismos tiempos de espera en los cuatro correos que envía el servidor
 *  (solicitud de acceso, reset de contraseña y los dos avisos de aprobación
 *  de cuentas). Antes el bloque createTransport estaba copiado en los
 *  cuatro sitios y los timeouts solo se podían ajustar de cuatro en cuatro. */
export function createSmtpTransport(smtp: SmtpConfig) {
    return nodemailer.createTransport({
        host: smtp.host,
        port: smtp.port,
        secure: smtp.port === 465,
        auth: { user: smtp.user, pass: smtp.pass },
        connectionTimeout: 8000,
        greetingTimeout: 8000,
        socketTimeout: 10000,
    });
}
