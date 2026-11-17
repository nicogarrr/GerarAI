/**
 * Preferencia del modelo del chat general del Cerebro. Se edita en
 * Ajustes > LLM y el panel la lee al abrirse. Persistencia local del
 * navegador (preferencia de cliente, no de cuenta): antes el selector
 * vivia en el pie del propio panel y se reiniciaba en cada apertura
 * (producto, 17-nov-2026).
 */
export type BrainChatModel = '' | 'hy4-flash-free';

export const BRAIN_CHAT_MODEL_KEY = 'gerarai.brain.chatModel';

export function readBrainChatModel(storage: Pick<Storage, 'getItem'> | undefined): BrainChatModel {
    try {
        return storage?.getItem(BRAIN_CHAT_MODEL_KEY) === 'hy4-flash-free' ? 'hy4-flash-free' : '';
    } catch {
        // Almacenamiento bloqueado (modo privado estricto): modelo por defecto.
        return '';
    }
}

export function writeBrainChatModel(storage: Pick<Storage, 'getItem' | 'setItem' | 'removeItem'> | undefined, value: BrainChatModel): void {
    try {
        if (value === 'hy4-flash-free') storage?.setItem(BRAIN_CHAT_MODEL_KEY, value);
        else storage?.removeItem(BRAIN_CHAT_MODEL_KEY);
    } catch {
        // Almacenamiento bloqueado: la preferencia simplemente no persiste.
    }
}
