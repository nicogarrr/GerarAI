'use client';

import { useState, useTransition } from 'react';

import { Button } from '@/components/ui/button';
import {
    createCalendarFeed,
    revokeCalendarFeed,
    type CalendarFeedScope,
    type CalendarFeedState,
} from '@/lib/actions/calendar-feed.actions';
import { useT, useFormat } from '@/lib/i18n/client';
import type { TranslateFn as TFunction } from '@/lib/i18n/translate';

type Provider = 'apple' | 'google' | 'outlook';

// Lo que el enlace expone segun el filtro: KO en cartera no aparece con
// 'watchlist' y eso tiene que leerse aqui, no descubrirse en el calendario.

function feedUrls(origin: string, token: string, feedName: string) {
    const https = `${origin}/api/calendar-feed/${token}.ics`;
    return {
        https,
        webcal: https.replace(/^https?:\/\//, 'webcal://'),
        google: `https://calendar.google.com/calendar/r?cid=${encodeURIComponent(https.replace(/^https?:\/\//, 'webcal://'))}`,
        outlook: `https://outlook.live.com/calendar/0/addfromweb?url=${encodeURIComponent(https)}&name=${encodeURIComponent(feedName)}`,
    };
}

export function SubscribeButtons({ origin, token }: { origin: string; token: string }) {
    const ti = useT();
    const [provider, setProvider] = useState<Provider>('apple');
    const [copied, setCopied] = useState(false);
    const urls = feedUrls(origin, token, ti('calendar.subscription.feedName'));
    const href = provider === 'apple' ? urls.webcal : provider === 'google' ? urls.google : urls.outlook;
    const PROVIDER_STEPS: Record<Provider, string[]> = {
        apple: [ti('calendar.subscription.stepApple1'), ti('calendar.subscription.stepApple2')],
        google: [ti('calendar.subscription.stepGoogle1'), ti('calendar.subscription.stepGoogle2')],
        outlook: [ti('calendar.subscription.stepOutlook1'), ti('calendar.subscription.stepOutlook2')],
    };
    const buttonLabel = {
        apple: ti('calendar.subscription.subscribeApple'),
        google: ti('calendar.subscription.subscribeGoogle'),
        outlook: ti('calendar.subscription.subscribeOutlook'),
    }[provider];

    return (
        <div className="flex flex-col gap-4">
            <div role="tablist" aria-label={ti('calendar.subscription.providerAria')} className="flex gap-4 border-b border-gray-800 text-sm font-medium">
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
                    aria-label={ti('calendar.subscription.linkAria')}
                    className="min-w-0 flex-1 rounded-lg border border-gray-800 bg-surface-1 px-3 py-2 font-mono text-base text-gray-400 sm:text-xs"
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
                    {copied ? ti('calendar.subscription.copied') : ti('calendar.subscription.copy')}
                </Button>
            </div>
            <p className="text-xs text-gray-500">
                {ti('calendar.subscription.linkNote')}
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
    const ti = useT();
    const f = useFormat();
    const SCOPE_LABEL: Record<CalendarFeedScope, string> = {
        followed: ti('calendar.subscription.scopeFollowed'),
        watchlist: ti('calendar.subscription.scopeWatchlist'),
    };
    const SCOPE_HINT: Record<CalendarFeedScope, string> = {
        followed: ti('calendar.subscription.hintFollowed'),
        watchlist: ti('calendar.subscription.hintWatchlist'),
    };
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
                setError(ti('calendar.subscription.errorCreate'));
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
                setError(ti('calendar.subscription.errorRevoke'));
            }
        });
    };

    return (
        <div className="flex flex-col gap-6">
            {state.active ? null : (
                <section aria-label={ti('calendar.subscription.filterLabel')} className="flex flex-col gap-2">
                    <h2 className="text-base font-semibold text-gray-100">{ti('calendar.subscription.filterLabel')}</h2>
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
                <section aria-label={ti('calendar.subscription.configLabel')} className="flex flex-col gap-3">
                    <h2 className="text-base font-semibold text-gray-100">{ti('calendar.subscription.configLabel')}</h2>
                    <SubscribeButtons origin={origin} token={freshToken} />
                </section>
            ) : null}

            {state.active ? (
                <section aria-label={ti('calendar.subscription.activeAria')} className="flex flex-col gap-3 rounded-2xl border border-gray-800 bg-surface-1 p-4">
                    <p className="text-sm text-gray-200">
                        {ti('calendar.subscription.activePre')}<span className="font-medium">{state.scope ? SCOPE_LABEL[state.scope] : ''}</span>
                        {state.created_at ? (
                            <span className="text-gray-500">{ti('calendar.subscription.createdAt', { date: f.formatUserDateTime(state.created_at) })}</span>
                        ) : null}
                    </p>
                    {state.scope ? <p className="text-xs text-gray-500">{SCOPE_HINT[state.scope]}</p> : null}
                    <div className="flex flex-col gap-2 sm:flex-row">
                        <Button disabled={pending} onClick={() => create(state.scope ?? scope)} className="min-h-11 flex-1">
                            {ti('calendar.subscription.regenerate')}
                        </Button>
                        <Button disabled={pending} variant="outline" onClick={revoke} className="min-h-11 flex-1">
                            {ti('calendar.subscription.deactivate')}
                        </Button>
                    </div>
                    <p className="text-xs text-gray-500">
                        {ti('calendar.subscription.regenerateNote')}
                    </p>
                </section>
            ) : (
                <Button disabled={pending} onClick={() => create(scope)} className="min-h-[48px] w-full text-base">
                    {ti('calendar.subscription.create')}
                </Button>
            )}
        </div>
    );
}
