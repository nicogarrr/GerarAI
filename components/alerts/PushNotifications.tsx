'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import {
    getPushStatus,
    registerPushDevice,
    removePushDevice,
    setPushPreference,
    type PushEventType,
    type PushStatus,
} from '@/lib/actions/push.actions';

export const PUSH_TYPE_LABELS: Record<PushEventType, string> = {
    macro_event: 'Eventos macro (IPC, empleo, FOMC): 24 h y 1 h antes',
    earnings: 'Próximos resultados de cartera y watchlist: 7 días, 1 día y el mismo día',
    dca_levels: 'Niveles DCA de tu watchlist',
    new_filing: 'Nuevos documentos de la SEC',
    thesis_broken: 'Tesis en riesgo',
    insiders: 'Movimientos de directivos',
    shorts_rising: 'Posiciones cortas al alza',
    daily_digest: 'Resumen diario de tu cartera',
};

type Support = 'checking' | 'unsupported' | 'ios-install' | 'denied' | 'ready';

function isIos(): boolean {
    const ua = window.navigator.userAgent;
    return /iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && window.navigator.maxTouchPoints > 1);
}

function isStandalone(): boolean {
    const nav = window.navigator as Navigator & { standalone?: boolean };
    return window.matchMedia('(display-mode: standalone)').matches || nav.standalone === true;
}

/** Clave VAPID (base64url) a bytes, como pide pushManager.subscribe. */
export function urlBase64ToBytes(value: string): Uint8Array {
    const padded = value + '='.repeat((4 - (value.length % 4)) % 4);
    const raw = window.atob(padded.replace(/-/g, '+').replace(/_/g, '/'));
    return Uint8Array.from(raw, (char) => char.charCodeAt(0));
}

function bytesToBase64Url(buffer: ArrayBuffer | null): string {
    if (!buffer) return '';
    let binary = '';
    new Uint8Array(buffer).forEach((byte) => {
        binary += String.fromCharCode(byte);
    });
    return window.btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function detectSupport(): Support {
    // En iPhone, Web Push solo existe con la app añadida a la pantalla de
    // inicio (iOS 16.4 o posterior): sin eso el navegador no expone la API.
    if (isIos() && !isStandalone()) return 'ios-install';
    if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) {
        return 'unsupported';
    }
    return Notification.permission === 'denied' ? 'denied' : 'ready';
}

export default function PushNotifications() {
    const [support, setSupport] = useState<Support>('checking');
    const [status, setStatus] = useState<PushStatus | null>(null);
    const [thisDevice, setThisDevice] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const refresh = useCallback(async () => {
        try {
            setStatus(await getPushStatus());
        } catch {
            setStatus(null);
        }
        if ('serviceWorker' in navigator) {
            const registration = await navigator.serviceWorker.getRegistration('/sw.js').catch(() => undefined);
            const subscription = await registration?.pushManager?.getSubscription().catch(() => null);
            setThisDevice(Boolean(subscription));
        }
    }, []);

    useEffect(() => {
        queueMicrotask(() => {
            setSupport(detectSupport());
            void refresh();
        });
    }, [refresh]);

    async function enableDevice() {
        if (!status?.public_key) return;
        setBusy(true);
        setError(null);
        try {
            const permission = await Notification.requestPermission();
            if (permission !== 'granted') {
                setSupport(permission === 'denied' ? 'denied' : 'ready');
                return;
            }
            const registration = await navigator.serviceWorker.ready;
            const subscription =
                (await registration.pushManager.getSubscription()) ??
                (await registration.pushManager.subscribe({
                    userVisibleOnly: true,
                    applicationServerKey: urlBase64ToBytes(status.public_key) as BufferSource,
                }));
            await registerPushDevice({
                endpoint: subscription.endpoint,
                keys: {
                    p256dh: bytesToBase64Url(subscription.getKey('p256dh')),
                    auth: bytesToBase64Url(subscription.getKey('auth')),
                },
                user_agent: navigator.userAgent.slice(0, 200),
            });
            await refresh();
        } catch {
            setError('No se pudo activar en este dispositivo. Inténtalo de nuevo.');
        } finally {
            setBusy(false);
        }
    }

    async function disableDevice() {
        setBusy(true);
        setError(null);
        try {
            const registration = await navigator.serviceWorker.getRegistration('/sw.js');
            const subscription = await registration?.pushManager.getSubscription();
            if (subscription) {
                await removePushDevice(subscription.endpoint);
                await subscription.unsubscribe();
            }
            await refresh();
        } catch {
            setError('No se pudo desactivar. Inténtalo de nuevo.');
        } finally {
            setBusy(false);
        }
    }

    async function toggle(eventType: PushEventType, enabled: boolean) {
        setBusy(true);
        setError(null);
        try {
            await setPushPreference(eventType, enabled);
            await refresh();
        } catch {
            setError('No se pudo guardar el cambio. Inténtalo de nuevo.');
        } finally {
            setBusy(false);
        }
    }

    const serverReady = status?.enabled === true && Boolean(status.public_key);

    return (
        <section data-testid="push-notifications" className="rounded-lg border border-gray-700/60 bg-surface-1 p-4 space-y-3">
            <h2 className="text-lg font-semibold text-white">Avisos en este dispositivo</h2>
            {support === 'checking' ? null : support === 'ios-install' ? (
                <p className="text-sm text-gray-400" data-testid="push-ios">
                    En iPhone o iPad los avisos solo funcionan con la app instalada (iOS 16.4 o posterior): en Safari toca{' '}
                    <span className="text-gray-200">Compartir</span> y{' '}
                    <span className="text-gray-200">Añadir a pantalla de inicio</span>, y vuelve a abrir esta página desde el icono.
                </p>
            ) : support === 'unsupported' ? (
                <p className="text-sm text-gray-400" data-testid="push-unsupported">
                    Este navegador no admite avisos push. Los avisos por Telegram y por correo siguen funcionando.
                </p>
            ) : status && !serverReady ? (
                <p className="text-sm text-gray-400" data-testid="push-server-off">
                    Los avisos push aún no están activados en el servidor.
                </p>
            ) : support === 'denied' ? (
                <p className="text-sm text-gray-400" data-testid="push-denied">
                    Bloqueaste las notificaciones de GerarAI. Para activarlas, permítelas en los ajustes del navegador o del sistema.
                </p>
            ) : !thisDevice ? (
                <>
                    <p className="text-sm text-gray-400">
                        Recibe avisos aunque no tengas la app abierta. Tú eliges qué tipos; el aviso trae la fuente y la hora.
                    </p>
                    <Button type="button" onClick={enableDevice} disabled={busy || !serverReady}>
                        Activar avisos en este dispositivo
                    </Button>
                </>
            ) : (
                <>
                    <fieldset className="space-y-2" disabled={busy}>
                        <legend className="sr-only">Tipos de aviso push</legend>
                        {(status?.preferences ?? []).map((pref) => (
                            <label key={pref.event_type} className="flex min-h-11 items-center gap-3 text-sm text-gray-200">
                                <input
                                    type="checkbox"
                                    className="size-5 shrink-0"
                                    checked={pref.enabled}
                                    onChange={(event) => void toggle(pref.event_type, event.target.checked)}
                                />
                                {PUSH_TYPE_LABELS[pref.event_type] ?? pref.event_type}
                            </label>
                        ))}
                    </fieldset>
                    <Button type="button" variant="outline" onClick={disableDevice} disabled={busy}>
                        Desactivar en este dispositivo
                    </Button>
                </>
            )}
            {error ? (
                <p role="alert" className="text-sm text-red-300">
                    {error}
                </p>
            ) : null}
        </section>
    );
}
