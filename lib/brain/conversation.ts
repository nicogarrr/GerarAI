// Persistencia de la conversación del cerebro global en sessionStorage.
// Sin imports: se prueba con node --test (scripts/brain-conversation.test.ts).

export type StoredBrainMessage = {
    role: 'user' | 'assistant';
    content: string;
    citations?: unknown[];
};

export const BRAIN_SUGGESTED_QUESTIONS = [
    '¿Cómo va mi cartera?',
    '¿Qué noticias hay de mis empresas?',
    '¿Qué tesis tengo activas?',
    '¿Qué riesgos tiene mi cartera?',
] as const;

const STORAGE_PREFIX = 'gerarai:brain:';
const MAX_MESSAGES = 30;
const MAX_CONTENT = 4000;

export function brainStorageKey(userId: string): string {
    return `${STORAGE_PREFIX}${userId}`;
}

/** Recorta a lo guardable: últimos MAX_MESSAGES, contenido acotado por mensaje. */
export function trimConversation(messages: StoredBrainMessage[]): StoredBrainMessage[] {
    return messages.slice(-MAX_MESSAGES).map((message) => ({
        ...message,
        content: message.content.slice(0, MAX_CONTENT),
    }));
}

export function serializeConversation(messages: StoredBrainMessage[]): string {
    return JSON.stringify(trimConversation(messages));
}

/**
 * Lo guardado vuelve a mensajes válidos o a null. Un JSON roto o una forma
 * inesperada nunca revienta el panel: se descarta y vuelve el saludo.
 */
export function restoreConversation(raw: string | null): StoredBrainMessage[] | null {
    if (!raw) return null;
    let parsed: unknown;
    try {
        parsed = JSON.parse(raw);
    } catch {
        return null;
    }
    if (!Array.isArray(parsed)) return null;
    const messages: StoredBrainMessage[] = [];
    for (const item of parsed) {
        if (typeof item !== 'object' || item === null) continue;
        const candidate = item as Record<string, unknown>;
        const role = candidate.role;
        const content = candidate.content;
        if ((role !== 'user' && role !== 'assistant') || typeof content !== 'string' || !content.trim()) {
            continue;
        }
        const message: StoredBrainMessage = { role, content };
        if (Array.isArray(candidate.citations)) message.citations = candidate.citations;
        messages.push(message);
    }
    return messages.length ? messages : null;
}
