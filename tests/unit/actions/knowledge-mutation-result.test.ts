import { describe, expect, it, vi } from 'vitest';

// La capa de identidad pide sesion de Next (no existe en vitest); se mockea
// para que el test del motor caido llegue al fetch stubeado.
vi.mock('@/lib/auth/research-identity', () => ({
    normalizeResearchBody: async (body: unknown) => ({ body, contentType: null }),
    researchIdentityHeaders: async () => ({}),
}));

import {
    createKnowledgeCollectionResult,
    reviseKnowledgePrincipleResult,
    uploadKnowledgeDocumentResult,
} from '@/lib/actions/research-tools.actions';

// Carril B (30-oct-2026): una validacion de formulario de la Biblioteca
// lanzada desde la server action llegaba a produccion enmascarada por Next
// (mensaje generico + digest) y MutationForm la clasificaba como motor
// caido («El motor de analisis no responde…») cuando el problema era el
// formulario. Ahora vuelve como resultado tipado con su mensaje en español.
describe('knowledge mutation results', () => {
    it('subir sin documento devuelve validacion con mensaje, no un throw', async () => {
        const formData = new FormData();
        await expect(uploadKnowledgeDocumentResult(formData)).resolves.toEqual({
            ok: false,
            cause: 'validation',
            message: 'Elige un documento para subir.',
        });
    });

    it('un documento vacio (0 bytes) tambien es validacion', async () => {
        const formData = new FormData();
        formData.set('file', new File([], 'vacio.pdf'));
        await expect(uploadKnowledgeDocumentResult(formData)).resolves.toEqual({
            ok: false,
            cause: 'validation',
            message: 'Elige un documento para subir.',
        });
    });

    it('crear coleccion sin nombre devuelve el mensaje del campo', async () => {
        const formData = new FormData();
        formData.set('name', '   ');
        await expect(createKnowledgeCollectionResult(formData)).resolves.toEqual({
            ok: false,
            cause: 'validation',
            message: 'Ponle un nombre a la colección.',
        });
    });

    it('revisar principio sin texto devuelve el mensaje del campo', async () => {
        const formData = new FormData();
        formData.set('principle', '');
        formData.set('category', 'Valuación');
        await expect(reviseKnowledgePrincipleResult(1, formData)).resolves.toEqual({
            ok: false,
            cause: 'validation',
            message: 'El principio no puede quedar vacío.',
        });
    });

    it('un fallo que no es de validacion (motor caido) sigue lanzando', async () => {
        // Documento valido: la action pasa la validacion y llama al motor;
        // si ese fetch falla, el error NO se traga (el cliente ofrece
        // reintentar). Se stubea fetch para no depender de red.
        const original = globalThis.fetch;
        globalThis.fetch = (() => Promise.reject(new Error('fetch failed'))) as typeof fetch;
        try {
            const formData = new FormData();
            formData.set('file', new File(['contenido'], 'tesis.md', { type: 'text/markdown' }));
            await expect(uploadKnowledgeDocumentResult(formData)).rejects.toThrow();
        } finally {
            globalThis.fetch = original;
        }
    });
});
