'use client';

import type { LlmUsage, LlmUsageLeg } from '@/lib/actions/llm-settings.actions';
import { formatDate } from '@/lib/format';
import { useLocale, useT } from '@/lib/i18n/client';
import { createTranslator, type TranslateFn } from '@/lib/i18n/translate';

/** Español por defecto (tests y llamadas sin hook). */
const esT: TranslateFn = createTranslator('es');

const DATE_TIME_OPTS: Intl.DateTimeFormatOptions = {
    day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
};

/** Claves literales: el chequeo de huérfanas de check-i18n no ve plantillas. */
const STATE_KEYS = {
    ok: 'settings.llm.usage.state.ok',
    limited: 'settings.llm.usage.state.limited',
    off: 'settings.llm.usage.state.off',
} as const;

function percent(value: unknown): number | null {
    return typeof value === 'number' && Number.isFinite(value) ? Math.round(value) : null;
}

export function LegCard({ leg, t = esT, locale = 'es' as const }: {
    leg: LlmUsageLeg;
    t?: TranslateFn;
    locale?: 'es' | 'en';
}) {
    const stateKey = leg.active ? leg.state : 'off';
    const stateClass =
        stateKey === 'ok' ? 'bg-emerald-900/50 text-emerald-300' :
        stateKey === 'limited' ? 'bg-amber-900/50 text-amber-300' :
        'bg-gray-800 text-gray-400';
    const until = leg.limited_until
        ? formatDate(leg.limited_until, DATE_TIME_OPTS, undefined, locale)
        : null;
    const weekly = leg.quota?.weekly;
    const monthly = leg.quota?.monthly;
    const weeklyPercent = percent(weekly?.percent);
    const monthlyPercent = percent(monthly?.percent);
    const resetsAt = typeof weekly?.resetsAt === 'string'
        ? formatDate(weekly.resetsAt, DATE_TIME_OPTS, undefined, locale)
        : null;
    const limits = leg.published_limits
        ? Object.values(leg.published_limits).map((l) => l.rpd).filter((v): v is number => typeof v === 'number')
        : [];

    return (
        <div className="rounded-lg border border-gray-800 bg-gray-900/40 p-4" data-testid={`llm-usage-${leg.id}`}>
            <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold text-gray-100">{leg.label}</span>
                <span className={`rounded px-2 py-0.5 text-xs ${stateClass}`}>
                    {t(STATE_KEYS[stateKey])}
                    {stateKey === 'limited' && until ? ` · ${t('settings.llm.usage.limitedUntil', { date: until })}` : ''}
                </span>
                <span className="rounded bg-gray-800 px-2 py-0.5 text-xs text-gray-400">
                    {leg.estimated ? t('settings.llm.usage.estimated') : t('settings.llm.usage.providerData')}
                </span>
            </div>
            {leg.model ? <p className="mt-1 text-xs text-gray-500">{leg.model}</p> : null}
            {leg.active && weeklyPercent !== null ? (
                <div className="mt-3">
                    <div className="flex justify-between text-xs text-gray-400">
                        <span>{t('settings.llm.usage.weekly')}</span>
                        <span>{weeklyPercent}%{resetsAt ? ` · ${t('settings.llm.usage.resetsAt', { date: resetsAt })}` : ''}</span>
                    </div>
                    <div className="mt-1 h-2 rounded bg-gray-800">
                        <div className="h-2 rounded bg-sky-500" style={{ width: `${Math.min(100, weeklyPercent)}%` }} />
                    </div>
                </div>
            ) : null}
            {leg.active && monthlyPercent !== null ? (
                <div className="mt-2">
                    <div className="flex justify-between text-xs text-gray-400">
                        <span>{t('settings.llm.usage.monthly')}</span>
                        <span>{monthlyPercent}%</span>
                    </div>
                    <div className="mt-1 h-2 rounded bg-gray-800">
                        <div className="h-2 rounded bg-indigo-500" style={{ width: `${Math.min(100, monthlyPercent)}%` }} />
                    </div>
                </div>
            ) : null}
            {leg.active && leg.today ? (
                <p className="mt-2 text-xs text-gray-400">
                    {t('settings.llm.usage.today', { calls: leg.today.calls, tokens: leg.today.tokens })}
                </p>
            ) : null}
            {leg.active && limits.length > 0 ? (
                <p className="mt-1 text-xs text-gray-500">
                    {t('settings.llm.usage.publishedLimits', { rpd: Math.max(...limits) })}
                </p>
            ) : null}
        </div>
    );
}

export default function LlmUsagePanel({ usage }: { usage: LlmUsage }) {
    const t = useT();
    const locale = useLocale();
    if (usage.source === 'tenant') {
        return <p className="text-sm text-gray-400">{t('settings.llm.usage.tenant')}</p>;
    }
    return (
        <div className="flex flex-col gap-3">
            <p className="text-sm text-gray-400">{t('settings.llm.usage.subtitle')}</p>
            {usage.legs.map((leg) => (
                <LegCard key={leg.id} leg={leg} t={t} locale={locale} />
            ))}
            <p className="text-xs text-gray-500">
                {t('settings.llm.usage.generatedAt', {
                    date: formatDate(usage.generated_at, DATE_TIME_OPTS, undefined, locale),
                })}
            </p>
        </div>
    );
}
