'use client';

import { useMemo, useState } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select';
import {
    saveLlmSettings,
    testLlmConnection,
    type LlmSettings,
    type LlmTestResult,
} from '@/lib/actions/llm-settings.actions';
import { useT } from '@/lib/i18n/client';
import { createTranslator, type TranslateFn } from '@/lib/i18n/translate';
import { showErrorToast } from '@/lib/toast';

/** Español por defecto (tests y llamadas sin hook). */
const esT: TranslateFn = createTranslator('es');

const REASONING_OPTIONS = [
    { value: '__unset__', label: 'settings.llm.reasoning.unset' },
    { value: 'none', label: 'settings.llm.reasoning.none' },
    { value: 'minimal', label: 'settings.llm.reasoning.minimal' },
    { value: 'low', label: 'settings.llm.reasoning.low' },
    { value: 'medium', label: 'settings.llm.reasoning.medium' },
    { value: 'high', label: 'settings.llm.reasoning.high' },
    { value: 'max', label: 'settings.llm.reasoning.max' },
] as const;

export function statusLabel(settings: LlmSettings, t: TranslateFn = esT): string {
    if (!settings.encryption_available) {
        return t('settings.llm.status.noEncryption');
    }
    if (settings.source === 'platform') {
        return t('settings.llm.status.platform');
    }
    if (settings.status === 'tenant') {
        return settings.api_key_last4
            ? t('settings.llm.status.tenantLast4', { last4: settings.api_key_last4 })
            : t('settings.llm.status.tenant');
    }
    if (settings.status === 'missing_key') {
        return t('settings.llm.status.missingKey');
    }
    return t('settings.llm.status.disabled');
}

/** Frase de estado en el idioma de la interfaz. El servidor la manda solo en
 *  castellano; se deriva de origen/estado y, si no se reconoce, se usa la suya. */
export function statusMessage(settings: LlmSettings, t: TranslateFn = esT): string {
    if (settings.source === 'platform') {
        if (settings.status === 'platform') return t('settings.llm.statusMessage.platformOn');
        if (settings.status === 'disabled') return t('settings.llm.statusMessage.platformOff');
    } else if (settings.source === 'tenant') {
        if (settings.status === 'tenant') return t('settings.llm.statusMessage.tenant');
        if (settings.status === 'missing_key') return t('settings.llm.statusMessage.missingKey');
        if (settings.status === 'disabled') return t('settings.llm.statusMessage.disabled');
    }
    return settings.message;
}

/** Nombre del proveedor: el «otro compatible» viene del servidor en castellano. */
export function providerLabel(entry: { id: string; label: string }, t: TranslateFn = esT): string {
    return entry.id === 'custom' ? t('settings.llm.providerCustom') : entry.label;
}

export default function LlmSettingsForm({ initial }: { initial: LlmSettings }) {
    const t = useT();
    const providerIds = useMemo(
        () => new Set(initial.providers.map((provider) => provider.id)),
        [initial.providers],
    );
    const initialProvider = providerIds.has(initial.provider) ? initial.provider : 'opencode-go';
    const initialSpec = initial.providers.find((provider) => provider.id === initialProvider);
    const [status, setStatus] = useState(initial);
    const [provider, setProvider] = useState(initialProvider);
    const [baseUrl, setBaseUrl] = useState(
        initial.base_url ?? initialSpec?.base_url ?? '',
    );
    const [model, setModel] = useState(initial.model ?? initialSpec?.default_model ?? '');
    const [fallbackModel, setFallbackModel] = useState(initial.fallback_model ?? '');
    const [reasoningEffort, setReasoningEffort] = useState(
        initial.reasoning_effort ?? '__unset__',
    );
    const [apiKey, setApiKey] = useState('');
    const [clearApiKey, setClearApiKey] = useState(false);
    const [enabled, setEnabled] = useState(initial.enabled);
    const [busy, setBusy] = useState(false);
    const [testing, setTesting] = useState(false);
    const [testResult, setTestResult] = useState<LlmTestResult | null>(null);

    const spec = status.providers.find((entry) => entry.id === provider);
    const isCustom = spec?.requires_custom_url === true;
    const canStoreKey = status.encryption_available;
    // The tenant test cannot use platform credentials. A saved key is bound
    // to its provider and URL; changing either requires a new key.
    const hasTestKey = Boolean(apiKey.trim()) || Boolean(
        status.api_key_configured && !clearApiKey && provider === status.provider
        && (!isCustom || baseUrl.trim() === status.base_url),
    );

    function changeProvider(next: string) {
        setProvider(next);
        const nextSpec = status.providers.find((entry) => entry.id === next);
        if (nextSpec && !nextSpec.requires_custom_url) {
            setBaseUrl(nextSpec.base_url);
            setModel(nextSpec.default_model);
        } else {
            setBaseUrl('');
            setModel('');
        }
        setTestResult(null);
    }

    async function submit(event: React.FormEvent<HTMLFormElement>) {
        event.preventDefault();
        setBusy(true);
        try {
            const saved = await saveLlmSettings({
                provider,
                model: model.trim(),
                base_url: isCustom ? baseUrl.trim() : null,
                fallback_model: fallbackModel.trim() || null,
                reasoning_effort: reasoningEffort === '__unset__' ? null : reasoningEffort,
                enabled,
                ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
                ...(clearApiKey ? { clear_api_key: true } : {}),
            });
            setStatus(saved);
            setApiKey('');
            setClearApiKey(false);
            setTestResult(null);
            toast.success(t('settings.llm.saved'));
        } catch (cause) {
            showErrorToast(cause);
        } finally {
            setBusy(false);
        }
    }

    async function testConnection() {
        if (!hasTestKey) return;
        setTesting(true);
        setTestResult(null);
        try {
            const result = await testLlmConnection({
                provider,
                model: model.trim(),
                base_url: isCustom ? baseUrl.trim() : null,
                ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
            });
            setTestResult(result);
            if (result.ok) {
                toast.success(result.message);
            } else {
                toast.error(result.message);
            }
        } catch {
            // Never reflect an upstream URL/key. Keep recovery in the form,
            // including production Server Action errors whose text is masked.
            const message = t('settings.llm.testFailed');
            setTestResult({ ok: false, status_code: null, provider, base_url: '', model, message });
            toast.error(message);
        } finally {
            setTesting(false);
        }
    }

    return (
        <form aria-label={t('settings.llm.formAria')} className="space-y-4" onSubmit={submit}>
            <div className="rounded-lg border border-gray-700/50 bg-gray-900/40 p-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-gray-100">{statusLabel(status, t)}</span>
                    <span className="rounded-full border border-gray-600 px-2 py-0.5 text-xs text-gray-400">
                        {status.billing_scope === 'tenant' ? t('settings.llm.billingTenant') : t('settings.llm.billingPlatform')}
                    </span>
                </div>
                <p className="mt-1 text-gray-400">{statusMessage(status, t)}</p>
                {status.source !== 'tenant' ? (
                    <p className="mt-2 rounded-lg border border-teal-800/50 bg-teal-950/30 p-3 text-gray-300">
                        {t('settings.llm.byokPitch')}
                    </p>
                ) : null}
                {!status.encryption_available ? (
                    <p className="mt-2 text-amber-300">
                        {t('settings.llm.noEncryptionBody')}
                    </p>
                ) : null}
            </div>

            <div className="grid gap-4 md:grid-cols-2">
                <label className="space-y-1 text-sm text-gray-300" htmlFor="llm-provider">
                    <span>{t('settings.llm.provider')}</span>
                    <Select disabled={busy} onValueChange={changeProvider} value={provider}>
                        <SelectTrigger className="w-full data-[size=default]:h-11" id="llm-provider">
                            <SelectValue placeholder={t('settings.llm.providerPlaceholder')} />
                        </SelectTrigger>
                        <SelectContent>
                            {status.providers.map((entry) => (
                                <SelectItem key={entry.id} value={entry.id}>
                                    {providerLabel(entry, t)}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </label>

                <label className="space-y-1 text-sm text-gray-300" htmlFor="llm-model">
                    <span>{t('settings.llm.model')}</span>
                    <Input
                        className="h-11"
                        autoComplete="off"
                        disabled={busy}
                        id="llm-model"
                        onChange={(event) => setModel(event.target.value)}
                        placeholder={t('settings.llm.modelPlaceholder')}
                        value={model}
                    />
                </label>

                {isCustom ? (
                    <label className="space-y-1 text-sm text-gray-300 md:col-span-2" htmlFor="llm-base-url">
                        <span>{t('settings.llm.baseUrl')}</span>
                        <Input
                            className="h-11"
                            autoComplete="off"
                            disabled={busy}
                            id="llm-base-url"
                            inputMode="url"
                            onChange={(event) => setBaseUrl(event.target.value)}
                            placeholder={t('settings.llm.baseUrlPlaceholder')}
                            value={baseUrl}
                        />
                        <span className="block text-xs text-gray-500">
                            {t('settings.llm.baseUrlHint')}
                        </span>
                    </label>
                ) : (
                    <p className="text-sm text-gray-400 md:col-span-2">
                        {t('settings.llm.providerUrl')} <span className="text-gray-300">{spec?.base_url}</span>
                    </p>
                )}

                <label className="space-y-1 text-sm text-gray-300" htmlFor="llm-fallback">
                    <span>{t('settings.llm.fallback')}</span>
                    <Input
                        className="h-11"
                        autoComplete="off"
                        disabled={busy}
                        id="llm-fallback"
                        onChange={(event) => setFallbackModel(event.target.value)}
                        placeholder={t('settings.llm.optional')}
                        value={fallbackModel}
                    />
                </label>

                <label className="space-y-1 text-sm text-gray-300" htmlFor="llm-reasoning">
                    <span>{t('settings.llm.reasoningLabel')}</span>
                    <Select
                        disabled={busy}
                        onValueChange={setReasoningEffort}
                        value={reasoningEffort}
                    >
                        <SelectTrigger className="w-full data-[size=default]:h-11" id="llm-reasoning">
                            <SelectValue placeholder={t('settings.llm.reasoning.unset')} />
                        </SelectTrigger>
                        <SelectContent>
                            {REASONING_OPTIONS.map((option) => (
                                <SelectItem key={option.value} value={option.value}>
                                    {t(option.label)}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </label>

                <label className="space-y-1 text-sm text-gray-300 md:col-span-2" htmlFor="llm-api-key">
                    <span>{t('settings.llm.apiKey')}</span>
                    <Input
                        className="h-11"
                        autoComplete="new-password"
                        disabled={busy || !canStoreKey}
                        id="llm-api-key"
                        onChange={(event) => {
                            setApiKey(event.target.value);
                            if (event.target.value) setClearApiKey(false);
                        }}
                        placeholder={
                            status.api_key_configured && status.api_key_last4
                                ? t('settings.llm.apiKeySaved', { last4: status.api_key_last4 })
                                : t('settings.llm.apiKeyPaste')
                        }
                        type="password"
                        value={apiKey}
                    />
                    <span className="block text-xs text-gray-500">
                        {t('settings.llm.apiKeyHint')}
                    </span>
                </label>
            </div>

            {status.api_key_configured ? (
                <label className="flex min-h-11 cursor-pointer items-start gap-3 py-2 text-sm leading-6 text-gray-300">
                    <input
                        checked={clearApiKey}
                        disabled={busy}
                        onChange={(event) => {
                            setClearApiKey(event.target.checked);
                            if (event.target.checked) setApiKey('');
                        }}
                        className="mt-0.5 size-5 shrink-0 accent-teal-500"
                        type="checkbox"
                    />
                    {t('settings.llm.clearKey')}
                </label>
            ) : null}

            <label className="flex min-h-11 cursor-pointer items-start gap-3 py-2 text-sm leading-6 text-gray-300">
                <input
                    checked={enabled}
                    disabled={busy}
                    onChange={(event) => setEnabled(event.target.checked)}
                    className="mt-0.5 size-5 shrink-0 accent-teal-500"
                    type="checkbox"
                />
                {t('settings.llm.useForAccount')}
            </label>

            <p className="text-xs text-gray-500">
                {t('settings.llm.paidNote')}{' '}
                {t('settings.llm.privacyPrefix')} <a className="text-teal-300 underline underline-offset-4 hover:text-teal-200" href="/privacidad">{t('settings.llm.privacyLink')}</a>.
            </p>

            {testResult ? (
                <p
                    aria-live="polite"
                    className={testResult.ok ? 'text-sm text-teal-300' : 'text-sm text-amber-300'}
                >
                    {testResult.message}
                    {testResult.status_code ? ` (HTTP ${testResult.status_code})` : ''}
                </p>
            ) : null}

            <p className="text-xs text-gray-400" id="llm-test-help">
                {t('settings.llm.testHelp')}
                {hasTestKey ? t('settings.llm.testHelpReady') : t('settings.llm.testHelpNoKey')}
            </p>
            <div className="flex flex-wrap gap-2">
                <Button disabled={busy || !model.trim()} type="submit">
                    {busy ? t('settings.llm.saving') : t('settings.common.save')}
                </Button>
                <Button
                    aria-describedby="llm-test-help"
                    disabled={busy || testing || !model.trim() || !hasTestKey}
                    onClick={() => void testConnection()}
                    type="button"
                    variant="outline"
                >
                    {testing ? t('settings.llm.testing') : t('settings.llm.test')}
                </Button>
            </div>
        </form>
    );
}
