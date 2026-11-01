'use client';

import React, { useEffect, useState } from 'react';
import { useT } from '@/lib/i18n/client';
import { isIos, isStandalone } from '@/lib/pwa/platform';
import { Button } from '@/components/ui/button';

// Evento no estandarizado de Chromium (Chrome, Edge, Android). Safari/iOS y
// Firefox no lo emiten: ahi solo se puede explicar el paso manual.
type BeforeInstallPromptEvent = Event & {
    prompt: () => Promise<void>;
    userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
};

type Mode = 'checking' | 'installed' | 'prompt' | 'ios' | 'manual';

export default function InstallApp() {
    const t = useT();
    const [mode, setMode] = useState<Mode>('checking');
    const [deferred, setDeferred] = useState<BeforeInstallPromptEvent | null>(null);

    useEffect(() => {
        // Detección de plataforma (APIs solo de navegador) tras montar: el
        // setState no es síncrono dentro del efecto.
        queueMicrotask(() => {
            if (isStandalone()) {
                setMode('installed');
                return;
            }
            setMode(isIos() ? 'ios' : 'manual');
        });
        const onPrompt = (event: Event) => {
            event.preventDefault();
            setDeferred(event as BeforeInstallPromptEvent);
            setMode('prompt');
        };
        const onInstalled = () => {
            setDeferred(null);
            setMode('installed');
        };
        window.addEventListener('beforeinstallprompt', onPrompt);
        window.addEventListener('appinstalled', onInstalled);
        return () => {
            window.removeEventListener('beforeinstallprompt', onPrompt);
            window.removeEventListener('appinstalled', onInstalled);
        };
    }, []);

    async function install() {
        if (!deferred) return;
        await deferred.prompt();
        const choice = await deferred.userChoice;
        // El navegador solo deja usar el evento una vez.
        setDeferred(null);
        setMode(choice.outcome === 'accepted' ? 'installed' : 'manual');
    }

    return (
        <section
            data-testid="install-app"
            className="rounded-lg border border-gray-700/60 bg-surface-1 p-4 space-y-3"
        >
            <h2 className="text-lg font-semibold text-white">{t('ui.pwa.title')}</h2>
            {mode === 'checking' ? null : mode === 'installed' ? (
                <p className="text-sm text-gray-300">{t('ui.pwa.installed')}</p>
            ) : mode === 'prompt' ? (
                <>
                    <p className="text-sm text-gray-400">
                        {t('ui.pwa.description')}
                    </p>
                    <Button type="button" onClick={install}>
                        {t('ui.pwa.installButton')}
                    </Button>
                </>
            ) : mode === 'ios' ? (
                <p className="text-sm text-gray-400" data-testid="install-ios">
                    {t('ui.pwa.iosPre')} <span className="text-gray-200">{t('ui.pwa.iosShare')}</span>{t('ui.pwa.iosMid')}{' '}
                    <span className="text-gray-200">{t('ui.pwa.iosAddHome')}</span>{t('ui.pwa.iosPost')}
                </p>
            ) : (
                <p className="text-sm text-gray-400" data-testid="install-manual">
                    {t('ui.pwa.manualInstructions')}
                </p>
            )}
        </section>
    );
}
