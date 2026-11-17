import { describe, expect, it } from 'vitest';
import { BRAIN_CHAT_MODEL_KEY, readBrainChatModel, writeBrainChatModel } from '@/lib/brain/chat-model';

describe('lib/brain/chat-model: preferencia local del modelo del chat general', () => {
    it('sin valor guardado devuelve el modelo por defecto', () => {
        expect(readBrainChatModel(undefined)).toBe('');
        const storage = { getItem: () => null };
        expect(readBrainChatModel(storage)).toBe('');
    });

    it('solo reconoce el modelo HY; cualquier otro valor cae al defecto', () => {
        expect(readBrainChatModel({ getItem: () => 'hy4-flash-free' })).toBe('hy4-flash-free');
        expect(readBrainChatModel({ getItem: () => 'gpt-9' })).toBe('');
    });

    it('escribe el modelo HY y borra la clave al volver al defecto', () => {
        const data = new Map<string, string>();
        const storage = {
            getItem: (k: string) => data.get(k) ?? null,
            setItem: (k: string, v: string) => void data.set(k, v),
            removeItem: (k: string) => void data.delete(k),
        };
        writeBrainChatModel(storage, 'hy4-flash-free');
        expect(data.get(BRAIN_CHAT_MODEL_KEY)).toBe('hy4-flash-free');
        writeBrainChatModel(storage, '');
        expect(data.has(BRAIN_CHAT_MODEL_KEY)).toBe(false);
    });

    it('con el almacenamiento bloqueado lee el defecto y la escritura no rompe', () => {
        const blocked = {
            getItem: () => { throw new Error('denied'); },
            setItem: () => { throw new Error('denied'); },
            removeItem: () => { throw new Error('denied'); },
        };
        expect(readBrainChatModel(blocked)).toBe('');
        expect(() => writeBrainChatModel(blocked, 'hy4-flash-free')).not.toThrow();
    });
});
