/**
 * Nota visible cuando la última pasada del motor NO comparó la regla.
 *
 * El motor guarda el motivo en ``last_result.status``. Sin esta nota la tarjeta
 * solo dice «Motor: evaluada …» y parece que la regla se comprobó con datos
 * válidos y no se cumplía.
 * - ``skipped_stale_observation``: el último dato es demasiado antiguo.
 * - ``skipped_session_gap`` (#3274): falta una sesión entre los dos últimos
 *   cierres; comparar daría un movimiento de dos días como si fuera de uno.
 */
export function alertSkipNote(status: string | null | undefined): string | null {
    switch (status) {
        case 'skipped_stale_observation':
            return 'dato desactualizado';
        case 'skipped_session_gap':
            return 'falta una sesión de cotización: no se compara hasta tener dos cierres seguidos';
        default:
            return null;
    }
}
