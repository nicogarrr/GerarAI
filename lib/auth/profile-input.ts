/**
 * Nombre y perfil inversor que llegan al alta (/sign-up/email) y a
 * /update-user de better-auth. Sin este filtro se guardaba cualquier cosa:
 * un nombre con saltos de línea («Juan\n\nAprobar: https://…») llegaba tal
 * cual al correo de texto plano con el que Nico aprueba cuentas y colaba un
 * enlace «Aprobar» falso encima del de verdad; y un país de 100.000
 * caracteres se guardaba en el documento del usuario.
 *
 * El formulario de alta no puede producir nada de esto (un <input> no lleva
 * saltos de línea); solo lo rechaza una llamada directa a la API.
 *
 * Módulo puro (sin alias `@/`).
 */

export const PROFILE_NAME_MAX = 100;
export const PROFILE_FIELD_MAX = 64;
export const PROFILE_FIELDS = ['country', 'investmentGoals', 'riskTolerance', 'preferredIndustry'] as const;

// Caracteres de control (incluye \n, \r, \t, NUL) y separadores de línea Unicode.
const LINE_BREAKING = /[\p{Cc}\u2028\u2029]/u;
const LINE_BREAKING_RUNS = /[\p{Cc}\u2028\u2029]+/gu;

function badText(value: unknown, max: number): boolean {
    if (typeof value !== 'string') return true;
    return LINE_BREAKING.test(value) || value.trim().length > max;
}

/**
 * Primer campo del cuerpo que no se puede guardar, o null si todo vale.
 * Solo mira los campos presentes: /update-user manda solo lo que cambia.
 */
export function profileInputProblem(body: unknown): string | null {
    if (!body || typeof body !== 'object') return null;
    const record = body as Record<string, unknown>;
    if ('name' in record && record.name !== undefined && badText(record.name, PROFILE_NAME_MAX)) {
        return 'name';
    }
    for (const field of PROFILE_FIELDS) {
        const value = record[field];
        if (value !== undefined && value !== null && badText(value, PROFILE_FIELD_MAX)) {
            return field;
        }
    }
    return null;
}

/** Nombre en una sola línea y con tope, para textos como el correo de aprobación. */
export function singleLineName(name: unknown, max: number = PROFILE_NAME_MAX): string {
    if (typeof name !== 'string') return '';
    const flat = name.replace(LINE_BREAKING_RUNS, ' ').replace(/ {2,}/g, ' ').trim();
    return flat.length > max ? `${flat.slice(0, max)}…` : flat;
}
