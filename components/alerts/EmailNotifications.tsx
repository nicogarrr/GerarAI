'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { useT } from '@/lib/i18n/client';
import {
    getEmailAlertStatus,
    setEmailAlertPreference,
    type EmailAlertStatus,
} from '@/lib/actions/email-alerts.actions';
import type { PushEventType } from '@/lib/alerts/push-event-types';
import { PUSH_TYPE_LABEL_KEYS } from '@/lib/alerts/push-type-labels';

/**
 * Avisos por correo a la direccion propia del usuario (la de su sesion), con
 * opt-in por tipo. Sin SMTP en el servidor la seccion avisa y no deja activar.
 */
export default function EmailNotifications() {
    const ti = useT();
    const [status, setStatus] = useState<EmailAlertStatus | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const refresh = useCallback(async () => {
        try {
            setStatus(await getEmailAlertStatus());
            setError(null);
        } catch {
            // Advertir, no ocultar: se conserva el último estado conocido y se
            // avisa del fallo. Antes setStatus(null) dejaba el placeholder
            // invisible para siempre, también tras guardar.
            setError(ti('alerts.email.errorLoad'));
        }
    }, [ti]);

    useEffect(() => {
        queueMicrotask(() => {
            void refresh();
        });
    }, [refresh]);

    async function toggle(eventType: PushEventType, enabled: boolean) {
        setBusy(true);
        setError(null);
        try {
            await setEmailAlertPreference(eventType, enabled);
            await refresh();
        } catch {
            setError(ti('alerts.email.errorSave'));
        } finally {
            setBusy(false);
        }
    }

    return (
        <section data-testid="email-notifications" className="rounded-lg border border-gray-700/60 bg-surface-1 p-4 space-y-3">
            <h2 className="text-lg font-semibold text-white">{ti('alerts.email.title')}</h2>
            {!status && error ? (
                <p role="alert" className="text-sm text-red-300" data-testid="email-load-error">
                    {error}
                </p>
            ) : !status ? (
                <p aria-hidden="true" className="h-5" data-testid="email-loading-space" />
            ) : !status.smtp ? (
                <p className="text-sm text-gray-400" data-testid="email-server-off">
                    {ti('alerts.email.serverOff')}
                </p>
            ) : !status.email ? (
                <p className="text-sm text-gray-400" data-testid="email-no-binding">
                    {ti('alerts.email.noBinding')}
                </p>
            ) : (
                <>
                    <p className="text-sm text-gray-400" data-testid="email-bound-address">
                        {ti('alerts.email.intro')} <span className="text-gray-200">{status.email}</span>
                    </p>
                    <fieldset className="space-y-2" disabled={busy}>
                        <legend className="sr-only">{ti('alerts.email.legend')}</legend>
                        {status.preferences.map((pref) => (
                            <label key={pref.event_type} className="flex min-h-11 items-center gap-3 text-sm text-gray-200">
                                <input
                                    type="checkbox"
                                    className="size-5 shrink-0"
                                    checked={pref.enabled}
                                    onChange={(event) => void toggle(pref.event_type, event.target.checked)}
                                />
                                {ti(PUSH_TYPE_LABEL_KEYS[pref.event_type])}
                            </label>
                        ))}
                    </fieldset>
                </>
            )}
            {status && error ? (
                <p role="alert" className="text-sm text-red-300">
                    {error}
                </p>
            ) : null}
        </section>
    );
}
