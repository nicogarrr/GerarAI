/**
 * Apertura del Cerebro desde otras pantallas.
 *
 * Dos caminos, mismo destino:
 *  - evento `gerarai:open-brain` (CustomEvent<OpenBrainDetail>) cuando el
 *    Cerebro ya está montado — lo escucha GlobalBrain;
 *  - handoff por sessionStorage cuando hay navegación de por medio (la
 *    página-redirect del antiguo /research/assistant): se escribe ANTES de
 *    navegar y GlobalBrain lo recoge ya montado, sin carrera de efectos.
 *
 * El detalle `{ ticker, question, review_id }` unifica la antigua guía de
 * investigación: con ticker el Cerebro pregunta al asistente de research
 * (solo lectura); con review_id la pregunta queda anclada a esa revisión.
 */
export const OPEN_BRAIN_PENDING_KEY = 'gerarai:open-brain:pending';

export type OpenBrainDetail = {
    ticker?: string;
    question?: string;
    review_id?: number;
};
