/**
 * Solicitud de acceso: validacion y reglas puras (sin red ni base de datos).
 *
 * El registro de GerarAI esta cerrado en produccion; quien quiere entrar pide
 * acceso con un formulario. La solicitud se guarda SIEMPRE (ver
 * `lib/actions/access-request.actions.ts`) y el aviso por correo es un paso
 * aparte, configurable por entorno.
 */
export const ACCESS_REQUEST_LIMITS = {
    nameMax: 120,
    noteMax: 500,
    emailMax: 254,
    /** Solicitudes distintas permitidas por IP (hash) en la ventana. */
    perIpPerHour: 5,
    windowMs: 60 * 60 * 1000,
} as const;

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

export type AccessRequestInput = {
    name: string;
    email: string;
    note: string;
};

export type AccessRequestParse =
    | { ok: true; value: AccessRequestInput }
    /** `spam`: el campo trampa vino relleno; se responde como si fuera bien, sin guardar. */
    | { ok: false; reason: 'spam' }
    | { ok: false; reason: 'invalid'; field: 'name' | 'email' | 'note'; code: AccessRequestInvalidCode; message: string };

/** Motivo estable del rechazo: la server action elige con él la copia en el idioma de la petición. */
export type AccessRequestInvalidCode = 'nameMissing' | 'nameTooLong' | 'emailInvalid' | 'noteTooLong';

const str = (v: unknown): string => (typeof v === 'string' ? v.trim() : '');

/** Valida y normaliza lo que llega del formulario. `honeypot` es el campo oculto anti-bots. */
export function parseAccessRequest(raw: unknown): AccessRequestParse {
    const o = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>;
    if (str(o.honeypot)) return { ok: false, reason: 'spam' };

    const name = str(o.name).replace(/\s+/g, ' ');
    const email = str(o.email).toLowerCase();
    const note = str(o.note);

    if (name.length < 2) return { ok: false, reason: 'invalid', field: 'name', code: 'nameMissing', message: 'Escribe tu nombre.' };
    if (name.length > ACCESS_REQUEST_LIMITS.nameMax)
        return { ok: false, reason: 'invalid', field: 'name', code: 'nameTooLong', message: 'El nombre es demasiado largo.' };
    if (email.length > ACCESS_REQUEST_LIMITS.emailMax || !EMAIL_RE.test(email))
        return { ok: false, reason: 'invalid', field: 'email', code: 'emailInvalid', message: 'Introduce un email válido.' };
    if (note.length > ACCESS_REQUEST_LIMITS.noteMax)
        return {
            ok: false,
            reason: 'invalid',
            field: 'note',
            code: 'noteTooLong',
            message: `La nota admite hasta ${ACCESS_REQUEST_LIMITS.noteMax} caracteres.`,
        };
    return { ok: true, value: { name, email, note } };
}

/** Correo donde llegan los avisos, o null si no esta configurado/valido. */
export function notifyTarget(env: Record<string, string | undefined>): string | null {
    const to = (env.ACCESS_REQUEST_NOTIFY_EMAIL ?? '').trim();
    return EMAIL_RE.test(to) ? to : null;
}

export type SmtpConfig = { host: string; port: number; user: string; pass: string; from: string };

/**
 * Credenciales SMTP del entorno (p. ej. Gmail con contrasena de aplicacion), o
 * null si falta usuario o contrasena. Host por defecto: smtp.gmail.com:465.
 */
export function smtpConfig(env: Record<string, string | undefined>): SmtpConfig | null {
    const user = (env.SMTP_USER ?? '').trim();
    const pass = (env.SMTP_PASS ?? '').replace(/\s+/g, '');
    if (!user || !pass) return null;
    const port = Number(env.SMTP_PORT ?? 465);
    return {
        host: (env.SMTP_HOST ?? '').trim() || 'smtp.gmail.com',
        port: Number.isInteger(port) && port > 0 && port < 65536 ? port : 465,
        user,
        pass,
        from: (env.MAIL_FROM ?? '').trim() || user,
    };
}

/** Asunto y cuerpo del aviso. Texto plano; nada del visitante va sin acotar. */
export function buildNotification(req: AccessRequestInput, total: number): { subject: string; text: string } {
    const clean = (s: string) => s.replace(/[\r\n]+/g, ' ').slice(0, 200);
    return {
        subject: `GerarAI: nueva solicitud de acceso (${clean(req.name)})`,
        text: [
            'Nueva solicitud de acceso a GerarAI.',
            '',
            `Nombre: ${clean(req.name)}`,
            `Email: ${req.email}`,
            `Nota: ${req.note ? req.note : '(sin nota)'}`,
            '',
            `Solicitudes guardadas en total: ${total}.`,
            'El registro sigue cerrado: nadie entra hasta que tu lo abras.',
        ].join('\n'),
    };
}
