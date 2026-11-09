// @ts-expect-error TS5097: node --test (--experimental-strip-types) necesita la extensión.
import { t as esT, type TranslationKey, type TranslationVars } from '../i18n/t.ts';

/** Traductor del idioma elegido; por defecto el español de referencia. */
type TiFn = (key: TranslationKey, vars?: TranslationVars) => string;

/**
 * Nota visible cuando la última pasada del motor NO comparó la regla.
 *
 * El motor guarda el motivo en ``last_result.status``. Sin esta nota la tarjeta
 * solo dice «Motor: evaluada …» y parece que la regla se comprobó con datos
 * válidos y no se cumplía.
 * - ``skipped_stale_observation``: el último dato es demasiado antiguo.
 * - ``skipped_session_gap`` (#3274): falta una sesión entre los dos últimos
 *   cierres; comparar daría un movimiento de dos días como si fuera de uno.
 * Un status desconocido no lleva nota (el texto crudo no significa nada para
 * el usuario): no se inventa explicación.
 */
const NOTAS: Record<string, TranslationKey> = {
    skipped_stale_observation: 'alerts.skipNote.stale',
    skipped_session_gap: 'alerts.skipNote.sessionGap',
};

export function alertSkipNote(status: string | null | undefined, ti: TiFn = esT): string | null {
    const key = status && Object.hasOwn(NOTAS, status) ? NOTAS[status] : undefined;
    return key ? ti(key) : null;
}
