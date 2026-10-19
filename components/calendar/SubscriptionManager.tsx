'use client';

import { useState, useTransition } from 'react';

import { Button } from '@/components/ui/button';
import {
    createCalendarFeed,
    revokeCalendarFeed,
    type CalendarFeedScope,
    type CalendarFeedState,
} from '@/lib/actions/calendar-feed.actions';
import { formatUserDateTime } from '@/lib/format';

type Provider = 'apple' | 'google' | 'outlook';

const PROVIDER_STEPS: Record<Provider, string[]> = {
    apple: [
        'Pulsa «Suscribirse con Apple Calendar».',
        'Pulsa «Suscribirse» cuando se abra la app Calendario.',
    ],
    google: [
        'Pulsa «Suscribirse con Google Calendar».',
        'Confirma «Añadir» en Google Calendar.',
    ],
    outlook: [
        'Pulsa «Suscribirse con Outlook».',
        'Confirma «Suscribirse» en Outlook.',
    ],
};

const SCOPE_LABEL: Record<CalendarFeedScope, string> = {
    followed: 'Cartera y watchlist',
    watchlist: 'Solo la watchlist',
};

// Lo que el enlace expone segun el filtro: KO en cartera no aparece con
// 'watchlist' y eso tiene que leerse aqui, no descubrirse en el calendario.
const SCOPE_HINT: Record<CalendarFeedScope, string> = {
    followed: 'Incluye los resultados de las posiciones de tu cartera y de tu watchlist.',
    watchlist: 'Incluye solo los resultados de tu watchlist; tu cartera no se comparte.',
};

function feedUrls(origin: string, token: string) {
    const https = `${origin}/api/calendar-feed/${token}.ics`;
    return {
        https,
        webcal: https.replace(/^https?:\/\//, 'webcal://'),
        google: `https://calendar.google.com/calendar/r?cid=${encodeURIComponent(https.replace(/^https?:\/\//, 'webcal://'))}`,
        outlook: `https://outlook.live.com/calendar/0/addfromweb?url=${encodeURIComponent(https)}&name=${encodeURIComponent('GerarAI · Resultados')}`,
    };
}

export function SubscribeButtons({ origin, token }: { origin: string; token: string }) {
    const [provider, setProvider] = useState<Provider>('apple');
    const [copied, setCopied] = useState(false);
    const urls = feedUrls(origin, token);
    const href = provider === 'apple' ? urls.webcal : provider === 'google' ? urls.google : urls.outlook;
    const buttonLabel = {
        apple: 'Suscribirse con Apple Calendar',
        google: 'Suscribirse con Google Calendar',
        outlook: 'Suscribirse con Outlook',
    }[provider];

    return (
        <div className="flex flex-col gap-4">
            <div role="tablist" aria-label="Proveedor de calendario" className="flex gap-4 border-b border-gray-800 text-sm font-medium">
                {(['apple', 'google', 'outlook'] as const).map((p) => (
                    <button
                        key={p}
                        role="tab"
                        aria-selected={provider === p}
                        onClick={() => setProvider(p)}
                        className={`-mb-px min-h-11 border-b-2 px-1 capitalize ${provider === p ? 'border-gray-100 text-gray-100' : 'border-transparent text-gray-400 hover:text-gray-200'}`}
                    >
                        {p}
                    </button>
                ))}
            </div>
            <ol className="list-decimal space-y-1 pl-5 text-sm text-gray-300">
                {PROVIDER_STEPS[provider].map((step) => (
                    <li key={step}>{step}</li>
                ))}
            </ol>
            <Button asChild className="min-h-[48px] w-full text-base">
                <a href={href} target={provider === 'apple' ? undefined : '_blank'} rel="noopener noreferrer">
                    {buttonLabel}
                </a>
            </Button>
            <div className="flex items-center gap-2">
                <input
                    readOnly
                    value={urls.https}
                    aria-label="Enlace de suscripción"
                    className="min-w-0 flex-1 rounded-lg border border-gray-800 bg-surface-1 px-3 py-2 font-mono text-xs text-gray-400"
                    onFocus={(event) => event.target.select()}
                />
                <Button
                    variant="outline"
                    className="min-h-11 shrink-0"
                    onClick={() => {
                        void navigator.clipboard.writeText(urls.https).then(() => {
                            setCopied(true);
                            setTimeout(() => setCopied(false), 2000);
                        });
                    }}
                >
                    {copied ? 'Copiado' : 'Copiar'}
                </Button>
            </div>
            <p className="text-xs text-gray-500">
                El enlace solo se muestra al crearlo. Quien lo tenga ve tu calendario de resultados: si se pierde,
                genera uno nuevo (el anterior deja de funcionar).
            </p>
        </div>
    );
}

export default function SubscriptionManager({
    initialState,
    origin,
}: {
    initialState: CalendarFeedState;
    origin: string;
}) {
    const [state, setState] = useState(initialState);
    // Default explícito 'watchlist' (decisión del auditor): el enlace ICS es
    // semipúblico y la watchlist expone menos que la cartera; el usuario
    // puede cambiarlo a 'followed' antes de crear.
    const [scope, setScope] = useState<CalendarFeedScope>(initialState.scope ?? 'watchlist');
    const [freshToken, setFreshToken] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [pending, startTransition] = useTransition();

    const create = (nextScope: CalendarFeedScope) => {
        setError(null);
        startTransition(async () => {
            try {
                const created = await createCalendarFeed(nextScope);
                setFreshToken(created.token);
                setState({ active: true, scope: nextScope, created_at: new Date().toISOString(), last_used_at: null });
            } catch {
                setError('No se pudo crear la suscripción. Reintenta en unos segundos.');
            }
        });
    };

    const revoke = () => {
        setError(null);
        startTransition(async () => {
            try {
                await revokeCalendarFeed();
                setState({ active: false, scope: null, created_at: null, last_used_at: null });
                setFreshToken(null);
            } catch {
                setError('No se pudo desactivar. Reintenta en unos segundos.');
            }
        });
    };

    return (
        <div className="flex flex-col gap-6">
            {state.active ? null : (
                <section aria-label="Filtro" className="flex flex-col gap-2">
                    <h2 className="text-base font-semibold text-gray-100">Filtro</h2>
                    <div className="flex flex-col gap-2 sm:flex-row">
                        {(Object.keys(SCOPE_LABEL) as CalendarFeedScope[]).map((option) => (
                            <button
                                key={option}
                                aria-pressed={scope === option}
                                disabled={pending}
                                onClick={() => setScope(option)}
                                className={`min-h-11 flex-1 rounded-xl border px-4 text-sm font-medium transition-colors ${scope === option ? 'border-teal-400/60 bg-teal-400/10 text-teal-200' : 'border-gray-800 bg-surface-1 text-gray-400 hover:border-gray-700 hover:text-gray-200'}`}
                            >
                                {SCOPE_LABEL[option]}
                            </button>
                        ))}
                    </div>
                    <p className="text-xs text-gray-500">{SCOPE_HINT[scope]}</p>
                </section>
            )}

            {error ? <p role="alert" className="rounded-lg border border-red-900/50 bg-red-950/20 p-3 text-sm text-red-200">{error}</p> : null}

            {freshToken ? (
                <section aria-label="Configuración" className="flex flex-col gap-3">
                    <h2 className="text-base font-semibold text-gray-100">Configuración</h2>
                    <SubscribeButtons origin={origin} token={freshToken} />
                </section>
            ) : null}

            {state.active ? (
                <section aria-label="Suscripción activa" className="flex flex-col gap-3 rounded-2xl border border-gray-800 bg-surface-1 p-4">
                    <p className="text-sm text-gray-200">
                        Suscripción activa: <span className="font-medium">{state.scope ? SCOPE_LABEL[state.scope] : ''}</span>
                        {state.created_at ? (
                            <span className="text-gray-500"> · creada el {formatUserDateTime(state.created_at)}</span>
                        ) : null}
                    </p>
                    {state.scope ? <p className="text-xs text-gray-500">{SCOPE_HINT[state.scope]}</p> : null}
                    <div className="flex flex-col gap-2 sm:flex-row">
                        <Button disabled={pending} onClick={() => create(state.scope ?? scope)} className="min-h-11 flex-1">
                            Regenerar enlace
                        </Button>
                        <Button disabled={pending} variant="outline" onClick={revoke} className="min-h-11 flex-1">
                            Desactivar
                        </Button>
                    </div>
                    <p className="text-xs text-gray-500">
                        Por seguridad el enlace no se puede volver a mostrar: regenerarlo crea uno nuevo y el anterior
                        deja de funcionar. Para cambiar el filtro, desactiva y crea una suscripción nueva.
                    </p>
                </section>
            ) : (
                <Button disabled={pending} onClick={() => create(scope)} className="min-h-[48px] w-full text-base">
                    Crear suscripción
                </Button>
            )}
        </div>
    );
}
