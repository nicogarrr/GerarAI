'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { useT } from '@/lib/i18n/client';
import type { TranslationKey } from '@/lib/i18n/t';
import {
    getEmailAlertStatus,
    setEmailAlertPreference,
    type EmailAlertStatus,
} from '@/lib/actions/email-alerts.actions';
import type { PushEventType } from '@/lib/alerts/push-event-types';

const TYPE_LABEL_KEYS: Record<PushEventType, TranslationKey> = {
    macro_event: 'alerts.push.types.macroEvent',
    earnings: 'alerts.push.types.earnings',
    dca_levels: 'alerts.push.types.dcaLevels',
    new_filing: 'alerts.push.types.newFiling',
    thesis_broken: 'alerts.push.types.thesisBroken',
    insiders: 'alerts.push.types.insiders',
    shorts_rising: 'alerts.push.types.shortsRising',
    daily_digest: 'alerts.push.types.dailyDigest',
};

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
        } catch {
            setStatus(null);
        }
    }, []);

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
            {!status ? (
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
                                {ti(TYPE_LABEL_KEYS[pref.event_type])}
                            </label>
                        ))}
                    </fieldset>
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
