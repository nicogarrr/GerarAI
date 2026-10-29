import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
    status: vi.fn(),
    register: vi.fn(),
    remove: vi.fn(),
    pref: vi.fn(),
}));
vi.mock('@/lib/actions/push.actions', () => ({
    getPushStatus: mocks.status,
    registerPushDevice: mocks.register,
    removePushDevice: mocks.remove,
    setPushPreference: mocks.pref,
}));

import PushNotifications, { PUSH_TYPE_LABELS, urlBase64ToBytes } from '@/components/alerts/PushNotifications';

const PREFS = Object.keys(PUSH_TYPE_LABELS).map((event_type) => ({ event_type, enabled: false }));
const READY = { enabled: true, public_key: 'AQID-g', devices: 0, preferences: PREFS };

type Sub = { endpoint: string; getKey: (n: string) => ArrayBuffer; unsubscribe: () => Promise<boolean> };

function setBrowser(opts: { ua?: string; standalone?: boolean; push?: boolean; permission?: NotificationPermission; sub?: Sub | null }) {
    const state = { sub: opts.sub ?? null };
    const pushManager = {
        getSubscription: vi.fn(async () => state.sub),
        subscribe: vi.fn(async () => {
            state.sub = {
                endpoint: 'https://fcm.googleapis.com/fcm/send/xyz',
                getKey: () => new Uint8Array([1, 2, 3, 250]).buffer,
                unsubscribe: vi.fn(async () => true),
            };
            return state.sub;
        }),
    };
    const registration = { pushManager };
    Object.defineProperty(window.navigator, 'userAgent', { value: opts.ua ?? 'Mozilla/5.0 Chrome', configurable: true });
    window.matchMedia = vi.fn().mockReturnValue({ matches: opts.standalone ?? false }) as never;
    if (opts.push === false) {
        delete (navigator as unknown as Record<string, unknown>).serviceWorker;
        delete (window as unknown as Record<string, unknown>).PushManager;
    } else {
        Object.defineProperty(navigator, 'serviceWorker', {
            value: { ready: Promise.resolve(registration), getRegistration: vi.fn(async () => registration) },
            configurable: true,
        });
        (window as unknown as Record<string, unknown>).PushManager = class {};
    }
    (window as unknown as Record<string, unknown>).Notification = Object.assign(vi.fn(), {
        permission: opts.permission ?? 'default',
        requestPermission: vi.fn(async () => 'granted'),
    });
    return { pushManager, state };
}

beforeEach(() => {
    vi.clearAllMocks();
    mocks.status.mockResolvedValue(READY);
});
afterEach(() => vi.restoreAllMocks());

describe('PushNotifications', () => {
    it('explains the install step on iPhone outside the installed app', async () => {
        setBrowser({ ua: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)', standalone: false });
        render(<PushNotifications />);
        expect(await screen.findByTestId('push-ios')).toHaveTextContent('Añadir a pantalla de inicio');
        expect(screen.queryByRole('button')).not.toBeInTheDocument();
    });

    it('says so when the browser has no push support', async () => {
        setBrowser({ push: false });
        render(<PushNotifications />);
        expect(await screen.findByTestId('push-unsupported')).toHaveTextContent('Telegram');
    });

    it('explains a blocked permission and an unconfigured server', async () => {
        setBrowser({ permission: 'denied' });
        const view = render(<PushNotifications />);
        expect(await screen.findByTestId('push-denied')).toBeVisible();
        view.unmount();
        setBrowser({});
        mocks.status.mockResolvedValue({ ...READY, enabled: false, public_key: null });
        render(<PushNotifications />);
        expect(await screen.findByTestId('push-server-off')).toBeVisible();
    });

    it('enables this device: asks permission, subscribes with the VAPID key and registers', async () => {
        const { pushManager } = setBrowser({});
        render(<PushNotifications />);
        fireEvent.click(await screen.findByRole('button', { name: 'Activar avisos en este dispositivo' }));
        await waitFor(() => expect(mocks.register).toHaveBeenCalledTimes(1));
        expect(pushManager.subscribe).toHaveBeenCalledWith(expect.objectContaining({ userVisibleOnly: true }));
        expect(mocks.register).toHaveBeenCalledWith({
            endpoint: 'https://fcm.googleapis.com/fcm/send/xyz',
            keys: { p256dh: 'AQID-g', auth: 'AQID-g' },
            user_agent: expect.stringContaining('Chrome'),
        });
        expect(await screen.findByRole('checkbox', { name: PUSH_TYPE_LABELS.macro_event })).not.toBeChecked();
    });

    it('does not register when the user refuses the permission prompt', async () => {
        setBrowser({});
        (Notification.requestPermission as unknown as ReturnType<typeof vi.fn>).mockResolvedValue('denied');
        render(<PushNotifications />);
        fireEvent.click(await screen.findByRole('button', { name: 'Activar avisos en este dispositivo' }));
        expect(await screen.findByTestId('push-denied')).toBeVisible();
        expect(mocks.register).not.toHaveBeenCalled();
    });

    it('shows a retryable error when registering fails', async () => {
        setBrowser({});
        mocks.register.mockRejectedValue(new Error('boom'));
        render(<PushNotifications />);
        fireEvent.click(await screen.findByRole('button', { name: 'Activar avisos en este dispositivo' }));
        expect(await screen.findByRole('alert')).toHaveTextContent('No se pudo activar');
        expect(screen.getByRole('button', { name: 'Activar avisos en este dispositivo' })).toBeEnabled();
    });

    it('toggles an event type and can disable the device', async () => {
        const sub: Sub = { endpoint: 'https://fcm.googleapis.com/fcm/send/xyz', getKey: () => new ArrayBuffer(0), unsubscribe: vi.fn(async () => true) };
        setBrowser({ sub });
        mocks.status.mockResolvedValue({ ...READY, devices: 1 });
        render(<PushNotifications />);
        const box = await screen.findByRole('checkbox', { name: PUSH_TYPE_LABELS.dca_levels });
        await act(async () => fireEvent.click(box));
        expect(mocks.pref).toHaveBeenCalledWith('dca_levels', true);
        fireEvent.click(screen.getByRole('button', { name: 'Desactivar en este dispositivo' }));
        await waitFor(() => expect(mocks.remove).toHaveBeenCalledWith(sub.endpoint));
        expect(sub.unsubscribe).toHaveBeenCalled();
    });

    it('reports failures when saving a type or disabling', async () => {
        const sub: Sub = { endpoint: 'https://fcm.googleapis.com/fcm/send/xyz', getKey: () => new ArrayBuffer(0), unsubscribe: vi.fn(async () => true) };
        setBrowser({ sub });
        mocks.status.mockResolvedValue({ ...READY, devices: 1 });
        mocks.pref.mockRejectedValue(new Error('x'));
        mocks.remove.mockRejectedValue(new Error('x'));
        render(<PushNotifications />);
        fireEvent.click(await screen.findByRole('checkbox', { name: PUSH_TYPE_LABELS.macro_event }));
        expect(await screen.findByRole('alert')).toHaveTextContent('No se pudo guardar');
        fireEvent.click(screen.getByRole('button', { name: 'Desactivar en este dispositivo' }));
        await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('No se pudo desactivar'));
    });

    it('survives a status failure', async () => {
        setBrowser({});
        mocks.status.mockRejectedValue(new Error('offline'));
        render(<PushNotifications />);
        expect(await screen.findByRole('button', { name: 'Activar avisos en este dispositivo' })).toBeDisabled();
    });

    it('decodes base64url VAPID keys', () => {
        expect(Array.from(urlBase64ToBytes('AQID-g'))).toEqual([1, 2, 3, 250]);
    });
});
