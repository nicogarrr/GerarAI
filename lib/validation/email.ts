/**
 * Validación del email en los formularios de acceso (registro e inicio de sesión).
 *
 * Antes cada formulario llevaba su propia regex `/^[\w-.]+@([\w-]+\.)+[\w-]{2,}$/`,
 * que rechazaba direcciones válidas que el servidor sí acepta: alias con `+`
 * (`nico+gerarai@gmail.com`) o con apóstrofo (`o'neill@ejemplo.com`). Además
 * no se recortaban los espacios, y el autocompletado del móvil suele añadir
 * uno al final: el formulario respondía «Introduce un email válido» a un
 * email correcto.
 *
 * La regex es la misma que usa el servidor (`z.email()` de zod 4, que valida
 * los endpoints de better-auth), para que el cliente no rechace nada que el
 * servidor aceptaría ni deje pasar algo que el servidor rechazará.
 *
 * Módulo puro (sin alias `@/`): lo importan los formularios y el guard de
 * `node --test`.
 */

export const EMAIL_PATTERN =
    /^(?!\.)(?!.*\.\.)([A-Za-z0-9_'+\-.]*)[A-Za-z0-9_+-]@([A-Za-z0-9][A-Za-z0-9-]*\.)+[A-Za-z]{2,}$/;

export const EMAIL_INVALID_MESSAGE = 'Introduce un email válido';
export const EMAIL_REQUIRED_MESSAGE = 'El email es obligatorio';

/** Quita los espacios de los extremos (autocompletado móvil, copiar y pegar). */
export function normalizeEmailInput(value: unknown): string {
    return typeof value === 'string' ? value.trim() : '';
}

export function isValidEmail(value: unknown): boolean {
    return EMAIL_PATTERN.test(normalizeEmailInput(value));
}

/**
 * Opciones de `register` (react-hook-form) para el campo email.
 * `setValueAs` recorta antes de validar y antes de enviar, así que la
 * acción de servidor recibe ya el email limpio.
 */
export const emailFieldValidation = {
    required: EMAIL_REQUIRED_MESSAGE,
    setValueAs: normalizeEmailInput,
    pattern: {
        value: EMAIL_PATTERN,
        message: EMAIL_INVALID_MESSAGE,
    },
};
