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

export type KnowledgeBrainContext = { scope: 'letters' | 'library'; authors?: string[]; documentId?: number; documentTitle?: string };

export type OpenBrainDetail = {
    knowledge?: KnowledgeBrainContext;
    ticker?: string;
    question?: string;
    review_id?: number;
};

const READY_ATTR = 'data-brain-ready';

/** GlobalBrain marca el documento cuando ya escucha el evento. */
export function markBrainReady(ready: boolean): void {
    if (typeof document === 'undefined') return;
    if (ready) document.documentElement.setAttribute(READY_ATTR, '1');
    else document.documentElement.removeAttribute(READY_ATTR);
}

/**
 * Abre el Cerebro desde cualquier pantalla. Con el Cerebro ya montado va por
 * evento; si aún no (carga directa), deja el handoff en sessionStorage, que
 * GlobalBrain recoge al montar. Nunca los dos a la vez: no se abre dos veces.
 */
export function openBrain(detail: OpenBrainDetail): void {
    if (typeof window === 'undefined') return;
    if (document.documentElement.hasAttribute(READY_ATTR)) {
        window.dispatchEvent(new CustomEvent<OpenBrainDetail>('gerarai:open-brain', { detail }));
        return;
    }
    try {
        window.sessionStorage.setItem(OPEN_BRAIN_PENDING_KEY, JSON.stringify(detail));
    } catch {
        // sessionStorage bloqueado: el usuario abre el Cerebro a mano.
    }
}

/** El contexto de una apertura nunca hereda ticker ni revisión de otra. */
export function brainHandoffContext(detail?: OpenBrainDetail | null): { ticker: string; reviewId: number | undefined } {
    const ticker = detail?.ticker && /^[A-Z0-9.\-]{1,20}$/i.test(detail.ticker) ? detail.ticker.toUpperCase() : '';
    const id = detail?.review_id;
    return {
        ticker,
        reviewId: ticker && typeof id === 'number' && Number.isSafeInteger(id) && id > 0 ? id : undefined,
    };
}

/** Runtime validation also applies to sessionStorage handoffs. */
export function knowledgeHandoff(detail?: OpenBrainDetail | null): KnowledgeBrainContext | null {
    const k = detail?.knowledge;
    if (!k || (k.scope !== 'letters' && k.scope !== 'library')) return null;
    return { scope: k.scope, ...(Number.isSafeInteger(k.documentId) && k.documentId! > 0 ? { documentId: k.documentId } : {}), ...(typeof k.documentTitle === 'string' ? { documentTitle: k.documentTitle.slice(0, 240) } : {}), authors: Array.isArray(k.authors) ? k.authors.filter((a): a is string => typeof a === 'string' && a.length <= 200).slice(0, 200) : [] };
}
