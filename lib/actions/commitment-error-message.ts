/**
 * Traducción de los rechazos 422 del seguimiento de compromisos a
 * explicaciones accionables en español. Los literales se leen del contrato
 * backend (commitment_tracking_service.py): son validaciones conocidas, no
 * texto arbitrario. Cualquier error NO reconocido devuelve null y sigue el
 * camino genérico de errores: nunca se convierte un fallo externo en una
 * instrucción nueva.
 */
const KNOWN_422: Array<[pattern: RegExp, message: string]> = [
    [
        /exigen URL de evidencia y extracto/i,
        'Cumplido, parcial o no cumplido exigen URL https de evidencia y un extracto literal que pruebe el criterio. Completa esos campos y vuelve a registrar la comprobación.',
    ],
    [
        /La evidencia debe ser una URL https/i,
        'La evidencia debe ser una URL https completa.',
    ],
    [
        /Define primero el criterio de cumplimiento/i,
        'Este compromiso no tiene criterio de cumplimiento definido: la revisión debe fijarlo antes de registrar un veredicto.',
    ],
    [
        /Revisa primero el candidato/i,
        'Este candidato aún no está en seguimiento: primero revisa cita, contexto, fecha y fuente y pásalo a seguimiento.',
    ],
    [
        /Indica por que no se puede concluir/i,
        'Sin veredicto hace falta un resumen: indica por qué no se puede concluir.',
    ],
    [
        /Solo se revisan candidatos sugeridos/i,
        'Solo se pueden revisar candidatos sugeridos; este compromiso ya está en seguimiento.',
    ],
    [
        /Confirma que has revisado/i,
        'Falta la confirmación: marca que has revisado cita, contexto, fecha y fuente en el documento original.',
    ],
    [
        /Define un criterio de cumplimiento concreto/i,
        'El criterio de cumplimiento es demasiado corto: describe qué hecho concreto y fecha lo probaría.',
    ],
];

/** Devuelve la explicación en español de un 422 conocido, o null si no aplica. */
export function commitmentErrorMessage(error: unknown): string | null {
    if (!(error instanceof Error)) return null;
    for (const [pattern, message] of KNOWN_422) {
        if (pattern.test(error.message)) return message;
    }
    return null;
}
