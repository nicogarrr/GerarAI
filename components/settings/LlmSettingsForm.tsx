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
import { showErrorToast } from '@/lib/toast';

const REASONING_OPTIONS = [
    { value: '__unset__', label: 'Sin especificar' },
    { value: 'none', label: 'Ninguno' },
    { value: 'minimal', label: 'Mínimo' },
    { value: 'low', label: 'Bajo' },
    { value: 'medium', label: 'Medio' },
    { value: 'high', label: 'Alto' },
    { value: 'max', label: 'Máximo' },
] as const;

export function statusLabel(settings: LlmSettings): string {
    if (!settings.encryption_available) {
        return 'Cifrado no disponible';
    }
    if (settings.source === 'platform') {
        return 'Usando proveedor de GerarAI';
    }
    if (settings.status === 'tenant') {
        return `Configurado con tu clave${settings.api_key_last4 ? ` (...${settings.api_key_last4})` : ''}`;
    }
    if (settings.status === 'missing_key') {
        return 'Falta tu clave API';
    }
    return 'Configuración desactivada';
}

export default function LlmSettingsForm({ initial }: { initial: LlmSettings }) {
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
            toast.success('Ajustes de IA guardados');
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
            const message = 'No se pudo comprobar tu clave. Revisa proveedor y clave API; si sigue fallando, vuelve a intentarlo más tarde.';
            setTestResult({ ok: false, status_code: null, provider, base_url: '', model, message });
            toast.error(message);
        } finally {
            setTesting(false);
        }
    }

    return (
        <form aria-label="Configuración del modelo de IA" className="space-y-4" onSubmit={submit}>
            <div className="rounded-lg border border-gray-700/50 bg-gray-900/40 p-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-gray-100">{statusLabel(status)}</span>
                    <span className="rounded-full border border-gray-600 px-2 py-0.5 text-xs text-gray-400">
                        {status.billing_scope === 'tenant' ? 'La clave y el coste son tuyos' : 'Coste de GerarAI'}
                    </span>
                </div>
                <p className="mt-1 text-gray-400">{status.message}</p>
                {!status.encryption_available ? (
                    <p className="mt-2 text-amber-300">
                        El cifrado no está configurado en el servidor. Puedes elegir proveedor y modelo,
                        pero no guardar una clave API propia.
                    </p>
                ) : null}
            </div>

            <div className="grid gap-4 md:grid-cols-2">
                <label className="space-y-1 text-sm text-gray-300" htmlFor="llm-provider">
                    <span>Proveedor</span>
                    <Select disabled={busy} onValueChange={changeProvider} value={provider}>
                        <SelectTrigger className="w-full data-[size=default]:h-11" id="llm-provider">
                            <SelectValue placeholder="Elige proveedor" />
                        </SelectTrigger>
                        <SelectContent>
                            {status.providers.map((entry) => (
                                <SelectItem key={entry.id} value={entry.id}>
                                    {entry.label}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </label>

                <label className="space-y-1 text-sm text-gray-300" htmlFor="llm-model">
                    <span>Modelo</span>
                    <Input
                        className="h-11"
                        autoComplete="off"
                        disabled={busy}
                        id="llm-model"
                        onChange={(event) => setModel(event.target.value)}
                        placeholder="p. ej. gpt-4.1-mini"
                        value={model}
                    />
                </label>

                {isCustom ? (
                    <label className="space-y-1 text-sm text-gray-300 md:col-span-2" htmlFor="llm-base-url">
                        <span>URL base (HTTPS público compatible con OpenAI)</span>
                        <Input
                            className="h-11"
                            autoComplete="off"
                            disabled={busy}
                            id="llm-base-url"
                            inputMode="url"
                            onChange={(event) => setBaseUrl(event.target.value)}
                            placeholder="https://tu-proveedor.example/v1"
                            value={baseUrl}
                        />
                        <span className="block text-xs text-gray-500">
                            Solo HTTPS público. No se permiten IP privadas, loopback ni credenciales en la URL.
                        </span>
                    </label>
                ) : (
                    <p className="text-sm text-gray-400 md:col-span-2">
                        URL del proveedor: <span className="text-gray-300">{spec?.base_url}</span>
                    </p>
                )}

                <label className="space-y-1 text-sm text-gray-300" htmlFor="llm-fallback">
                    <span>Modelo de respaldo (opcional)</span>
                    <Input
                        className="h-11"
                        autoComplete="off"
                        disabled={busy}
                        id="llm-fallback"
                        onChange={(event) => setFallbackModel(event.target.value)}
                        placeholder="Opcional"
                        value={fallbackModel}
                    />
                </label>

                <label className="space-y-1 text-sm text-gray-300" htmlFor="llm-reasoning">
                    <span>Razonamiento</span>
                    <Select
                        disabled={busy}
                        onValueChange={setReasoningEffort}
                        value={reasoningEffort}
                    >
                        <SelectTrigger className="w-full data-[size=default]:h-11" id="llm-reasoning">
                            <SelectValue placeholder="Sin especificar" />
                        </SelectTrigger>
                        <SelectContent>
                            {REASONING_OPTIONS.map((option) => (
                                <SelectItem key={option.value} value={option.value}>
                                    {option.label}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </label>

                <label className="space-y-1 text-sm text-gray-300 md:col-span-2" htmlFor="llm-api-key">
                    <span>Clave API</span>
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
                                ? `Guardada (...${status.api_key_last4}); escribe otra para cambiarla`
                                : 'Pega tu clave API'
                        }
                        type="password"
                        value={apiKey}
                    />
                    <span className="block text-xs text-gray-500">
                        Se guarda cifrada y no se vuelve a mostrar. La clave la paga tu proveedor.
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
                    Borrar la clave guardada y desactivar la IA propia
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
                Usar esta configuración para la IA de mi cuenta
            </label>

            <p className="text-xs text-gray-500">
                Los proveedores de pago los paga el usuario; GerarAI no asume ese coste.
                Consulta la <a className="text-teal-300 underline underline-offset-4 hover:text-teal-200" href="/privacidad">política de privacidad</a>.
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
                Esta prueba comprueba tu clave API propia, no el proveedor de GerarAI.
                {hasTestKey ? ' Consulta la conexión sin generar texto ni consumir tokens.' : ' Introduce una clave para habilitarla. No necesitas una clave propia para usar la IA de GerarAI.'}
            </p>
            <div className="flex flex-wrap gap-2">
                <Button disabled={busy || !model.trim()} type="submit">
                    {busy ? 'Guardando...' : 'Guardar'}
                </Button>
                <Button
                    aria-describedby="llm-test-help"
                    disabled={busy || testing || !model.trim() || !hasTestKey}
                    onClick={() => void testConnection()}
                    type="button"
                    variant="outline"
                >
                    {testing ? 'Probando...' : 'Probar conexión'}
                </Button>
            </div>
        </form>
    );
}
