'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { useT } from '@/lib/i18n/client';
import type { TranslationKey } from '@/lib/i18n/t';
import {
    getPushStatus,
    registerPushDevice,
    removePushDevice,
    setPushPreference,
    type PushEventType,
    type PushStatus,
} from '@/lib/actions/push.actions';

// Etiquetas es enlazadas al diccionario: export de compatibilidad para los
// tests; la vista pinta con useT() via PUSH_TYPE_LABEL_KEYS.
import esAlerts from '@/lib/i18n/messages/es/alerts.json';

export const PUSH_TYPE_LABELS: Record<PushEventType, string> = {
    macro_event: esAlerts.push.types.macroEvent,
    earnings: esAlerts.push.types.earnings,
    dca_levels: esAlerts.push.types.dcaLevels,
    new_filing: esAlerts.push.types.newFiling,
    thesis_broken: esAlerts.push.types.thesisBroken,
    insiders: esAlerts.push.types.insiders,
    shorts_rising: esAlerts.push.types.shortsRising,
    daily_digest: esAlerts.push.types.dailyDigest,
};

const PUSH_TYPE_LABEL_KEYS: Record<PushEventType, TranslationKey> = {
    macro_event: 'alerts.push.types.macroEvent',
    earnings: 'alerts.push.types.earnings',
    dca_levels: 'alerts.push.types.dcaLevels',
    new_filing: 'alerts.push.types.newFiling',
    thesis_broken: 'alerts.push.types.thesisBroken',
    insiders: 'alerts.push.types.insiders',
    shorts_rising: 'alerts.push.types.shortsRising',
    daily_digest: 'alerts.push.types.dailyDigest',
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
    const ti = useT();
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
            setError(ti('alerts.push.errorEnable'));
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
            setError(ti('alerts.push.errorDisable'));
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
            setError(ti('alerts.push.errorSave'));
        } finally {
            setBusy(false);
        }
    }

    const serverReady = status?.enabled === true && Boolean(status.public_key);

    return (
        <section data-testid="push-notifications" className="rounded-lg border border-gray-700/60 bg-surface-1 p-4 space-y-3">
            <h2 className="text-lg font-semibold text-white">{ti('alerts.push.title')}</h2>
            {support === 'checking' ? null : support === 'ios-install' ? (
                <p className="text-sm text-gray-400" data-testid="push-ios">
                    {ti('alerts.push.iosPre')}
                    <span className="text-gray-200">{ti('alerts.push.iosShare')}</span>{ti('alerts.push.iosMid')}
                    <span className="text-gray-200">{ti('alerts.push.iosAdd')}</span>{ti('alerts.push.iosPost')}
                </p>
            ) : support === 'unsupported' ? (
                <p className="text-sm text-gray-400" data-testid="push-unsupported">
                    {ti('alerts.push.unsupported')}
                </p>
            ) : status && !serverReady ? (
                <p className="text-sm text-gray-400" data-testid="push-server-off">
                    {ti('alerts.push.serverOff')}
                </p>
            ) : support === 'denied' ? (
                <p className="text-sm text-gray-400" data-testid="push-denied">
                    {ti('alerts.push.denied')}
                </p>
            ) : !thisDevice ? (
                <>
                    <p className="text-sm text-gray-400">
                        {ti('alerts.push.intro')}
                    </p>
                    <Button type="button" onClick={enableDevice} disabled={busy || !serverReady}>
                        {ti('alerts.push.enable')}
                    </Button>
                </>
            ) : (
                <>
                    <fieldset className="space-y-2" disabled={busy}>
                        <legend className="sr-only">{ti('alerts.push.legend')}</legend>
                        {(status?.preferences ?? []).map((pref) => (
                            <label key={pref.event_type} className="flex min-h-11 items-center gap-3 text-sm text-gray-200">
                                <input
                                    type="checkbox"
                                    className="size-5 shrink-0"
                                    checked={pref.enabled}
                                    onChange={(event) => void toggle(pref.event_type, event.target.checked)}
                                />
                                {PUSH_TYPE_LABELS[pref.event_type] ? ti(PUSH_TYPE_LABEL_KEYS[pref.event_type]) : pref.event_type}
                            </label>
                        ))}
                    </fieldset>
                    <Button type="button" variant="outline" onClick={disableDevice} disabled={busy}>
                        {ti('alerts.push.disable')}
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
