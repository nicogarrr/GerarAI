/**
 * Feedback compartido de los tickets de la cuenta demo manual (OrderTicket y
 * FxTicket): estado de error de validacion ligado al valor de los campos,
 * init del datetime-local y el trio de mensajes (error/aviso/duplicado).
 *
 * La cascada de resultado (filled/duplicate/rejected) y la rotacion del
 * clientOrderId siguen inline en cada ticket: son la parte que conviene leer
 * junto al submit de cada formulario.
 */
import { useState } from 'react';

/** Error de validación local ligado a los valores con los que se calculó:
 *  en cuanto el usuario edita cualquier campo la clave cambia y deja de
 *  mostrarse, sin efectos ni renders en cascada. */
export type FieldInvalid = { key: string; message: string } | null;

/** Mensaje de validacion vigente: solo si la clave de campos no ha cambiado. */
export function invalidMessage(invalid: FieldInvalid, fieldKey: string): string | null {
    return invalid !== null && invalid.key === fieldKey ? invalid.message : null;
}

/** Estado del datetime-local: ahora, sin segundos, en hora local sin zona
 *  (datetime-local espera hora local sin zona). */
export function useExecutedAtLocal(): [string, (value: string) => void] {
    const [executedAtLocal, setExecutedAtLocal] = useState(() => {
        const now = new Date();
        now.setSeconds(0, 0);
        return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
    });
    return [executedAtLocal, setExecutedAtLocal];
}

/** Trio de mensajes del ticket: error (alert), aviso de exito y duplicado. */
export function TicketFeedbackMessages({
    validationError,
    submitError,
    notice,
    duplicate,
}: {
    validationError: string | null;
    submitError: string | null;
    notice: string | null;
    duplicate: string | null;
}) {
    return (
        <>
            {validationError || submitError ? (
                <p role="alert" className="text-sm text-red-400">
                    {validationError ?? submitError}
                </p>
            ) : null}
            {notice ? (
                <p role="status" className="text-sm text-teal-300">
                    {notice}
                </p>
            ) : null}
            {duplicate ? (
                <p role="status" className="text-sm text-warn">
                    {duplicate}
                </p>
            ) : null}
        </>
    );
}
