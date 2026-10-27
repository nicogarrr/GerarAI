import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// Solo se simula el borde (sonner); classifyError y getFriendlyErrorMessage
// son los reales: el test comprueba qué ve el usuario para cada causa.
vi.mock('sonner', () => ({
    toast: { error: vi.fn(), info: vi.fn(), success: vi.fn() },
}));

import { toast } from 'sonner';
import { showErrorToast } from '@/lib/toast';
import { AppError, DuplicateError, ExternalAPIError, ValidationError } from '@/lib/types/errors';

type Action = { label: string; onClick: () => void };

function lastErrorAction(): Action | undefined {
    const calls = vi.mocked(toast.error).mock.calls;
    const opts = calls.at(-1)?.[1] as { action?: Action } | undefined;
    return opts?.action;
}

async function flush() {
    for (let i = 0; i < 5; i += 1) await Promise.resolve();
}

describe('showErrorToast', () => {
    beforeEach(() => {
        vi.mocked(toast.error).mockClear();
        vi.mocked(toast.info).mockClear();
        vi.mocked(toast.success).mockClear();
    });
    afterEach(() => {
        vi.unstubAllGlobals();
    });

    it('duplicado: toast informativo (no error) con el mensaje propio', () => {
        const cause = showErrorToast(new DuplicateError(), { duplicateMessage: 'AAPL ya está en tu watchlist' });
        expect(cause).toBe('duplicate');
        expect(toast.info).toHaveBeenCalledWith('AAPL ya está en tu watchlist');
        expect(toast.error).not.toHaveBeenCalled();
    });

    it('cliente desfasado tras un despliegue: acción «Recargar»', () => {
        const reload = vi.fn();
        vi.stubGlobal('location', { ...window.location, reload });
        const cause = showErrorToast(new Error('Failed to find Server Action "abc"'));
        expect(cause).toBe('stale');
        const action = lastErrorAction();
        expect(action?.label).toBe('Recargar');
        action?.onClick();
        expect(reload).toHaveBeenCalledTimes(1);
    });

    it('motor caído con onRetry: acción «Reintentar» y éxito tras reintentar', async () => {
        const onRetry = vi.fn().mockResolvedValue(undefined);
        const cause = showErrorToast(new ExternalAPIError('fetch failed', 'research'), {
            onRetry,
            successMessage: 'Añadido',
        });
        expect(cause).toBe('offline');
        const action = lastErrorAction();
        expect(action?.label).toBe('Reintentar');
        action?.onClick();
        await flush();
        expect(onRetry).toHaveBeenCalledTimes(1);
        expect(toast.success).toHaveBeenCalledWith('Añadido');
    });

    it('motor caído SIN onRetry: toast de error sin acción', () => {
        showErrorToast(new Error('fetch failed'));
        expect(toast.error).toHaveBeenCalledTimes(1);
        expect(vi.mocked(toast.error).mock.calls[0][1]).toBeUndefined();
    });

    it('validación: nunca ofrece reintentar aunque haya onRetry', () => {
        const cause = showErrorToast(new ValidationError('Cantidad inválida'), { onRetry: vi.fn() });
        expect(cause).toBe('validation');
        expect(lastErrorAction()).toBeUndefined();
    });

    it('el mensaje del toast nunca es el genérico de Next en inglés', () => {
        showErrorToast(new Error('An error occurred in the Server Components render. digest: 123'));
        const message = String(vi.mocked(toast.error).mock.calls[0][0]);
        expect(message).not.toMatch(/Server Components/);
    });

    it('si el reintento vuelve a fallar: nuevo toast de error, sin éxito falso ni rechazo sin capturar', async () => {
        const onRetry = vi.fn().mockRejectedValue(new Error('fetch failed'));
        const unhandled = vi.fn();
        process.on('unhandledRejection', unhandled);
        try {
            showErrorToast(new AppError('fetch failed', 'EXTERNAL_API_ERROR', 502), {
                onRetry,
                successMessage: 'Guardado',
            });
            lastErrorAction()?.onClick();
            await flush();
            await new Promise((resolve) => setTimeout(resolve, 0));
            expect(toast.success).not.toHaveBeenCalled();
            expect(toast.error).toHaveBeenCalledTimes(2);
            // El segundo toast vuelve a ofrecer reintentar.
            expect(lastErrorAction()?.label).toBe('Reintentar');
            expect(unhandled).not.toHaveBeenCalled();
        } finally {
            process.off('unhandledRejection', unhandled);
        }
    });

    it('si onRetry lanza de forma síncrona, el clic no revienta', async () => {
        const onRetry = vi.fn(() => {
            throw new Error('fetch failed');
        });
        showErrorToast(new Error('fetch failed'), { onRetry });
        expect(() => lastErrorAction()?.onClick()).not.toThrow();
        await flush();
        expect(toast.error).toHaveBeenCalledTimes(2);
    });
});
