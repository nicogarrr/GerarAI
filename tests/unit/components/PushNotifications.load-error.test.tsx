import {writeFileSync} from 'node:fs';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
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

import PushNotifications, { PUSH_TYPE_LABELS } from '@/components/alerts/PushNotifications';

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


describe('PushNotifications · fallos de lectura', () => {
 it('explica el fallo inicial y permite recuperarse sin activar avisos', async () => {
  setBrowser({});
  mocks.status.mockRejectedValueOnce(new Error('backend internal error')).mockResolvedValue(READY);
  render(<PushNotifications />);
  expect(await screen.findByRole('alert')).toHaveTextContent('No se pudo consultar');
  if(process.env.PUSH_PREVIEW) writeFileSync('/tmp/push-load-error.html','<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="/tmp/push-style.css"></head><body style="background:#080808;color:#ddd;padding:16px">'+document.body.innerHTML+'</body></html>');
  expect(screen.queryByText('backend internal error')).toBeNull();
  expect(screen.getByRole('button',{name:'Activar avisos en este dispositivo'})).toBeDisabled();
  fireEvent.click(screen.getByRole('button',{name:'Reintentar consulta'}));
  await waitFor(()=>expect(screen.queryByRole('alert')).toBeNull());
  expect(screen.getByRole('button',{name:'Activar avisos en este dispositivo'})).toBeEnabled();
  expect(mocks.register).not.toHaveBeenCalled();
 });
 it('conserva preferencias conocidas si falla la lectura posterior a guardar', async () => {
  const sub: Sub={endpoint:'https://push.example.test/subscription',getKey:()=>new ArrayBuffer(0),unsubscribe:vi.fn(async()=>true)};
  setBrowser({sub});
  mocks.status.mockResolvedValueOnce({...READY,devices:1}).mockRejectedValue(new Error('offline'));
  render(<PushNotifications />);
  const box=await screen.findByRole('checkbox',{name:PUSH_TYPE_LABELS.macro_event});
  fireEvent.click(box);
  expect(await screen.findByRole('alert')).toHaveTextContent('desactualizados');
  expect(box).not.toBeChecked();
  expect(box).toBeDisabled();
  expect(screen.getByRole('button',{name:'Desactivar en este dispositivo'})).toBeDisabled();
  mocks.status.mockResolvedValue({...READY,devices:1});
  fireEvent.click(screen.getByRole('button',{name:'Reintentar consulta'}));
  await waitFor(()=>expect(box).toBeEnabled());
 });
 it('mantiene el aviso si también falla el reintento', async () => {
  setBrowser({});mocks.status.mockRejectedValue(new Error('offline'));
  render(<PushNotifications />);
  fireEvent.click(await screen.findByRole('button',{name:'Reintentar consulta'}));
  await waitFor(()=>expect(mocks.status).toHaveBeenCalledTimes(2));
  expect(screen.getByRole('alert')).toHaveTextContent('No se pudo consultar');
  await waitFor(()=>expect(screen.getByRole('button',{name:'Reintentar consulta'})).toBeEnabled());
 });
});
