import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const m = vi.hoisted(() => ({ revoke: vi.fn(), create: vi.fn(), toastError: vi.fn() }));
vi.mock('@/lib/actions/calendar-feed.actions', () => ({ createCalendarFeed: m.create, revokeCalendarFeed: m.revoke }));
vi.mock('sonner', () => ({ toast: { error: m.toastError } }));

import SubscriptionManager, { SubscribeButtons } from '@/components/calendar/SubscriptionManager';

const active = { active: true, scope: 'followed' as const, created_at: null, last_used_at: null };

beforeEach(() => {
    vi.clearAllMocks();
    m.revoke.mockResolvedValue(undefined);
    m.create.mockResolvedValue({ token: 'nuevo-token' });
});

describe('SubscriptionManager', () => {
    it('revocar el feed ICS exige confirmación y se puede cancelar', async () => {
        render(<SubscriptionManager initialState={active} origin="https://gerarai.com" />);
        fireEvent.click(screen.getByRole('button', { name: 'Desactivar' }));
        expect(screen.getByRole('dialog')).toHaveTextContent('¿Desactivar la suscripción?');
        expect(screen.getByRole('dialog')).toHaveTextContent('El enlace actual dejará de funcionar');
        expect(m.revoke).not.toHaveBeenCalled();

        fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancelar' }));
        expect(m.revoke).not.toHaveBeenCalled();

        fireEvent.click(screen.getByRole('button', { name: 'Desactivar' }));
        fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Desactivar' }));
        await waitFor(() => expect(m.revoke).toHaveBeenCalledOnce());
    });

    it('si el portapapeles está bloqueado, avisa en vez de no hacer nada', async () => {
        const writeText = vi.fn().mockRejectedValue(new Error('blocked'));
        Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
        render(<SubscribeButtons origin="https://gerarai.com" token="abc" />);
        fireEvent.click(screen.getByRole('button', { name: 'Copiar' }));
        await waitFor(() => expect(m.toastError).toHaveBeenCalledWith('No se pudo copiar el enlace. Cópialo manualmente desde el campo.'));
        expect(writeText).toHaveBeenCalledWith('https://gerarai.com/api/calendar-feed/abc.ics');
        expect(screen.queryByRole('button', { name: 'Copiado' })).not.toBeInTheDocument();
    });

    it('el temporizador que revierte «Copiado» se limpia al desmontar', async () => {
        vi.useFakeTimers();
        try {
            const writeText = vi.fn().mockResolvedValue(undefined);
            Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
            const { unmount } = render(<SubscribeButtons origin="https://gerarai.com" token="abc" />);
            await act(async () => {
                fireEvent.click(screen.getByRole('button', { name: 'Copiar' }));
            });
            expect(screen.getByRole('button', { name: 'Copiado' })).toBeInTheDocument();
            unmount();
            await act(async () => {
                vi.advanceTimersByTime(2500);
            });
            expect(vi.getTimerCount()).toBe(0);
        } finally {
            vi.useRealTimers();
        }
    });
});
