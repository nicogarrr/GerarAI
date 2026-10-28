'use client';

import React, { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';

// Evento no estandarizado de Chromium (Chrome, Edge, Android). Safari/iOS y
// Firefox no lo emiten: ahi solo se puede explicar el paso manual.
type BeforeInstallPromptEvent = Event & {
    prompt: () => Promise<void>;
    userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
};

type Mode = 'checking' | 'installed' | 'prompt' | 'ios' | 'manual';

function isStandalone(): boolean {
    const nav = window.navigator as Navigator & { standalone?: boolean };
    return window.matchMedia('(display-mode: standalone)').matches || nav.standalone === true;
}

function isIos(): boolean {
    const ua = window.navigator.userAgent;
    // iPadOS 13+ se presenta como Mac: se distingue por la pantalla tactil.
    return /iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && window.navigator.maxTouchPoints > 1);
}

export default function InstallApp() {
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
            <h2 className="text-lg font-semibold text-white">Instalar GerarAI</h2>
            {mode === 'checking' ? null : mode === 'installed' ? (
                <p className="text-sm text-gray-300">GerarAI ya está instalada en este dispositivo.</p>
            ) : mode === 'prompt' ? (
                <>
                    <p className="text-sm text-gray-400">
                        Ábrela como una app, sin barra del navegador. Necesita conexión: no guarda tus tesis
                        ni datos para leer sin red.
                    </p>
                    <Button type="button" onClick={install}>
                        Instalar la aplicación
                    </Button>
                </>
            ) : mode === 'ios' ? (
                <p className="text-sm text-gray-400" data-testid="install-ios">
                    En iPhone o iPad: toca <span className="text-gray-200">Compartir</span> y después{' '}
                    <span className="text-gray-200">Añadir a pantalla de inicio</span>. Hazlo desde Safari.
                </p>
            ) : (
                <p className="text-sm text-gray-400" data-testid="install-manual">
                    Tu navegador no ofrece el botón de instalar aquí. En Chrome o Edge abre el menú y elige
                    «Instalar GerarAI» (o «Añadir a la pantalla de inicio» en el móvil).
                </p>
            )}
        </section>
    );
}
