'use client';

import { alertThesisHref } from '@/lib/alerts/card-destination';
import { Suspense, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Bell, History, Plus, RefreshCcw, Send, Trash2 } from 'lucide-react';
// Espejo de la validación de createAlert (lib/actions/alerts.actions.ts).
const ALERT_SYMBOL_PATTERN = /^[A-Z0-9.\-]{1,20}$/;

import { createAlertResult, getRecentTriggeredAlerts, getTelegramStatus, getUserAlertsResult, deleteAlert, type Alert, type AlertsLoadCause, type CreateAlertInput, type AlertType, type TelegramStatus, type TriggeredAlertDelivery } from '@/lib/actions/alerts.actions';
import { parseLocalizedNumberDetailed } from '@/lib/i18n/parse-number';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
} from '@/components/ui/dialog';
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select';
import { Input } from '@/components/ui/input';
import { TickerSearchInput } from '@/components/search/TickerSearchInput';
import { Label } from '@/components/ui/label';
import { toast } from 'sonner';
import { showErrorToast } from '@/lib/toast';
import SectionLoadError from '@/components/system/SectionLoadError';
import { classifyError, getFriendlyErrorMessage, isNextRedirectError } from '@/lib/types/errors';
import { t } from '@/lib/i18n/t';
import { useT, useLocale, useFormat } from '@/lib/i18n/client';
import { reviewResearchExpectations } from '@/lib/actions/research.actions';
import { ExternalNewsHeadline } from '@/components/research/ExternalNewsHeadline';
import { alertCardCopy, alertSummaryIsSourceHeadline } from '@/lib/alerts/card-copy';
import { etiquetaCanal, etiquetaEstadoEntrega } from '@/lib/alerts/delivery-labels';
import { alertSkipNote } from '@/lib/alerts/skip-note';

const isAlertType = (value: string | null | undefined): value is AlertType =>
    value === 'price_above' || value === 'price_below' || value === 'price_change' || value === 'news' || value === 'earnings';

function AlertsManager() {
    const cardT = useT();
    const cardLocale = useLocale();
    const searchParams = useSearchParams();
    const ti = useT();
    const locale = useLocale();
    const f = useFormat();
    const alertTypeLabels: Record<AlertType, string> = {
        price_above: ti('alerts.types.priceAbove'),
        price_below: ti('alerts.types.priceBelow'),
        price_change: ti('alerts.types.priceChange'),
        news: ti('alerts.types.news'),
        earnings: ti('alerts.types.earnings'),
    };
    const [alerts, setAlerts] = useState<Alert[]>([]);
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState<{ message: string; cause: AlertsLoadCause } | null>(null);
    // Deep-link desde QuickAlertButton (/alerts?symbol=MSFT&type=price_below&value=300):
    // el diálogo arranca abierto y pre-rellenado desde la URL, sin efecto.
    const [open, setOpen] = useState(() => searchParams.get('symbol') !== null);
    const [reviewing, setReviewing] = useState<string | null>(null);
    /** Borrado en curso: sin esto el boton se puede pulsar dos veces. */
    const [deleting, setDeleting] = useState<string | null>(null);
    const [confirmAlert, setConfirmAlert] = useState<Alert | null>(null);
    /** Alta en curso: igual que el borrado, doble click = alerta duplicada. */
    const [creating, setCreating] = useState(false);
    // Fallo de ALTA con el motor caído: se muestra y se reintenta DENTRO del
    // diálogo. El toast con acción quedaba inutilizable bajo el modal: el
    // click caía en el overlay y cerraba el formulario, y Tab no alcanzaba
    // el botón dentro del focus-trap de Radix.
    const [createError, setCreateError] = useState<string | null>(null);
    const createErrorRef = useRef<HTMLDivElement | null>(null);
    /** Estado de entrega del motor (evaluacion cada 5 min + Telegram). */
    const [telegram, setTelegram] = useState<TelegramStatus | null>(null);
    const [triggered, setTriggered] = useState<TriggeredAlertDelivery[]>([]);
    const [formData, setFormData] = useState<CreateAlertInput>(() => {
        const symbol = searchParams.get('symbol');
        if (!symbol) {
            return { symbol: '', type: 'price_above', condition: { operator: '>', value: '' } };
        }
        const type = searchParams.get('type');
        return {
            symbol: symbol.toUpperCase(),
            type: isAlertType(type) ? type : 'price_above',
            condition: {
                operator: type === 'price_below' || type === 'price_change' ? '<' : '>',
                value: searchParams.get('value') ?? '',
            },
        };
    });

    const loadAlerts = async () => {
        setLoadError(null);
        try {
            // getUserAlertsResult resuelve la causa en servidor, donde el
            // código del AppError aún existe: session (local, probada),
            // forbidden (403), rate (429), offline (5xx/red), unknown
            // (incluido un 401 del backend, causa no probada). La vista no
            // adivina causas ni induce re-login sin prueba.
            const [result, telegramStatus, recent] = await Promise.all([
                getUserAlertsResult(),
                getTelegramStatus().catch(() => null),
                getRecentTriggeredAlerts(10).catch(() => [] as TriggeredAlertDelivery[]),
            ]);
            if (!result.ok) {
                const message = result.cause === 'session'
                    ? t('common.states.alertsLoadErrorSession')
                    : result.cause === 'forbidden'
                        ? t('common.states.alertsLoadErrorForbidden')
                        : result.cause === 'rate'
                            ? t('common.states.alertsLoadErrorRate')
                            : t('common.states.alertsLoadError');
                setLoadError({ message, cause: result.cause });
                return;
            }
            setAlerts(result.alerts);
            setTelegram(telegramStatus);
            setTriggered(recent);
        } catch (error) {
            if (isNextRedirectError(error)) throw error;
            // El fallo de CARGA queda en el estado inline con Reintentar;
            // un segundo toast con el mismo fallo era ruido duplicado.
            // Los errores de MUTACIÓN (crear/borrar/revisar) sí conservan
            // su toast: no tienen otro feedback visible.
            setLoadError({ message: t('common.states.alertsLoadError'), cause: 'unknown' });
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        // Carga inicial tras montar: el setState de loadAlerts no es síncrono
        // dentro del efecto.
        queueMicrotask(() => void loadAlerts());
    }, []);

    useEffect(() => {
        if (createError) createErrorRef.current?.focus();
    }, [createError]);

    const handleCreateAlert = async () => {
        if (creating) return;
        setCreateError(null);
        try {
            // Mismo patrón que valida createAlert en servidor. Sin este filtro,
            // un símbolo largo o con caracteres raros llegaba a la server action,
            // que lanza ValidationError: POST /alerts 500 y, en producción, un
            // error genérico en inglés en vez de este aviso (agent-qa 28/10).
            if (!ALERT_SYMBOL_PATTERN.test(formData.symbol.trim().toUpperCase())) {
                toast.error(ti('alerts.errors.invalidSymbol'));
                return;
            }
            const isValueless = formData.type === 'news' || formData.type === 'earnings';
            const parsed = parseLocalizedNumberDetailed(String(formData.condition.value), locale);
            if (!isValueless && !parsed.ok) {
                // El umbral ambiguo («1,234») se rechaza enseñando el formato,
                // como en transacciones/tesis/screener: el mensaje genérico no
                // le dice al usuario qué corregir.
                toast.error(parsed.error === 'ambiguous'
                    ? ti('alerts.errors.ambiguousNumber')
                    : ti('alerts.errors.invalidNumber'));
                return;
            }
            const parsedValue = parsed.ok ? parsed.value : null;
            if ((formData.type === 'price_above' || formData.type === 'price_below') && (parsedValue === null || parsedValue <= 0)) {
                toast.error(ti('alerts.errors.pricePositive'));
                return;
            }
            const numericValue: string | number = isValueless
                ? formData.condition.value
                : (parsedValue as number);

            setCreating(true);
            const result = await createAlertResult({
                ...formData,
                condition: {
                    ...formData.condition,
                    // Cinturón y tirantes: aunque el select de tipo ya sincroniza
                    // la dirección, el alta deriva el operador del tipo para que
                    // un estado viejo (deep-link, HMR) nunca guarde la alerta al
                    // revés de lo que anuncia su etiqueta.
                    operator:
                        formData.type === 'price_above'
                            ? '>'
                            : formData.type === 'price_below'
                              ? '<'
                              : formData.condition.operator,
                    value: numericValue,
                },
            });
            if (!result.ok) {
                // Rechazo de negocio (símbolo inexistente, duplicada): su
                // mensaje, sin «reintenta» ni cerrar el diálogo.
                if (result.cause === 'duplicate') toast.info(result.message);
                else toast.error(result.message);
                return;
            }
            toast.success(ti('alerts.toast.created'));

            setOpen(false);
            setFormData({
                symbol: '',
                type: 'price_above',
                condition: {
                    operator: '>',
                    value: '',
                },
            });
            loadAlerts();
        } catch (error) {
            if (isNextRedirectError(error)) throw error;
            if (classifyError(error) === 'offline') {
                // Superficie inline: el reintento debe ser alcanzable con
                // teclado y no puede cerrar el diálogo al pulsarse.
                setCreateError(getFriendlyErrorMessage(error));
            } else {
                showErrorToast(error, {
                    duplicateMessage: ti('alerts.errors.duplicate'),
                });
            }
        } finally {
            setCreating(false);
        }
    };

    const handleDeleteAlert = async (alertId: string) => {
        const alert = alerts.find(item => item._id === alertId);
        if (!alert) return;
        setDeleting(alertId);
        try {
            await deleteAlert(alertId);
            await loadAlerts();
            toast.success(ti('alerts.toast.deleted'));
        } catch (error) {
            if (isNextRedirectError(error)) throw error;
            showErrorToast(error, {
                onRetry: () => handleDeleteAlert(alertId),
            });
        } finally {
            setDeleting(null);
        }
    };

    /**
     * Revisión de expectativas vs realidad para el ticker de la alerta:
     * dispara reviewResearchExpectations (POST expectation-reality/review)
     * para contrastar lo prometido con los hechos canónicos.
     */
    const handleReview = async (alert: Alert) => {
        if (!alert.symbol || reviewing) return;
        setReviewing(alert._id);
        try {
            await reviewResearchExpectations(alert.symbol);
            toast.success(ti('alerts.toast.reviewLaunched', { symbol: alert.symbol }));
        } catch (error) {
            if (isNextRedirectError(error)) throw error;
            showErrorToast(error, {
                onRetry: () => handleReview(alert),
            });
        } finally {
            setReviewing(null);
        }
    };

    const getAlertLabel = (alert: Alert) => {
        const symbol = alert.symbol;
        const type = alert.type;
        const operator = alert.condition.operator;
        const value = alert.condition.value;
        // La regla guarda operador y umbral, no la divisa: el motor lo compara
        // con el último cierre del valor en la divisa de su bolsa. Se pinta el
        // número sin símbolo (y la nota de debajo lo declara) en vez de anteponer
        // un «$» que solo es cierto para las líneas en dólares.
        const threshold = f.formatNumber(value, { maximumFractionDigits: 4 });

        if (type === 'price_above' || type === 'price_below') {
            return ti('alerts.labels.price', { symbol, type: alertTypeLabels[type], threshold });
        }
        if (type === 'price_change') {
            const direction = operator === '>' ? ti('alerts.labels.changeUp') : ti('alerts.labels.changeDown');
            return ti('alerts.labels.priceChange', { symbol, type: alertTypeLabels.price_change, direction, threshold });
        }
        if (type === 'news' || type === 'earnings') {
            return ti('alerts.labels.simple', { symbol, type: alertTypeLabels[type] });
        }
        return ti('alerts.labels.simple', { symbol, type: ti('alerts.labels.fallback') });
    };

    return (
        <Card className="p-4 sm:p-6 rounded-lg border border-gray-700 bg-gray-800/50">
            <div className="flex items-center justify-between gap-2 mb-4">
                <div className="flex items-center gap-3">
                    <Bell aria-hidden="true" className="h-5 w-5 shrink-0 text-teal-400" />
                    <h2 className="text-sm font-semibold text-gray-200">{ti('alerts.manager.title')}</h2>
                </div>
                <Dialog open={open} onOpenChange={(next) => {
                        setOpen(next);
                        if (!next) setCreateError(null);
                    }}>
                    <DialogTrigger asChild>
                        <Button size="sm" className="gap-2 min-h-[44px] px-4 text-sm sm:min-h-0 sm:text-xs">
                            <Plus aria-hidden="true" className="h-4 w-4" />
                            {ti('alerts.new')}
                        </Button>
                    </DialogTrigger>
                    <DialogContent className="bg-gray-800 border-gray-700 max-h-[90dvh] overflow-y-auto w-[calc(100vw-2rem)] sm:max-w-md">
                        <DialogHeader>
                            <DialogTitle className="text-gray-100">{ti('alerts.create')}</DialogTitle>
                            <DialogDescription className="text-gray-400">
                                {ti('alerts.dialog.description')}
                            </DialogDescription>
                        </DialogHeader>
                        <div className="space-y-4 mt-4">
                            <div>
                                <Label htmlFor="symbol" className="text-gray-300">{ti('alerts.form.symbol')}</Label>
                                <TickerSearchInput
                                    id="symbol"
                                    value={formData.symbol}
                                    onValueChange={(value) => setFormData({ ...formData, symbol: value.toUpperCase() })}
                                    onSelect={(stock) => setFormData({ ...formData, symbol: stock.symbol.toUpperCase() })}
                                    placeholder="AAPL"
                                    ariaLabel={ti('alerts.form.symbol')}
                                    className="bg-gray-900 border-gray-600 text-gray-100 h-11 text-base sm:h-9 sm:text-sm w-full"
                                />
                            </div>
                            <div>
                                <Label htmlFor="type" className="text-gray-300">{ti('alerts.form.type')}</Label>
                                <Select
                                    value={formData.type}
                                    onValueChange={(value: AlertType) =>
                                        setFormData({
                                            ...formData,
                                            type: value,
                                            // La dirección de price_above/price_below ya la anuncia el
                                            // tipo y el motor evalúa el OPERADOR: sin sincronizarlos se
                                            // guardaba price_below con '>' y la alerta saltaba al revés
                                            // de lo que prometía su etiqueta. En price_change la
                                            // dirección sí la elige el usuario, así que se conserva.
                                            condition: {
                                                ...formData.condition,
                                                operator:
                                                    value === 'price_above'
                                                        ? '>'
                                                        : value === 'price_below'
                                                          ? '<'
                                                          : formData.condition.operator,
                                            },
                                        })
                                    }
                                >
                                    <SelectTrigger id="type" className="bg-gray-900 border-gray-600 text-gray-100 h-11 text-base sm:h-9 sm:text-sm">
                                        <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent className="bg-gray-900 border-gray-600">
                                        {Object.entries(alertTypeLabels).map(([value, label]) => (
                                            <SelectItem key={value} value={value}>{label}</SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>
                            {(formData.type === 'price_above' || formData.type === 'price_below' || formData.type === 'price_change') && (
                                <>
                                    {formData.type === 'price_change' && (
                                    <div>
                                        <Label htmlFor="operator" className="text-gray-300">{ti('alerts.form.operator')}</Label>
                                        <Select
                                            value={formData.condition.operator === '<' ? '<' : '>'}
                                            onValueChange={(value: CreateAlertInput['condition']['operator']) =>
                                                setFormData({
                                                    ...formData,
                                                    condition: { ...formData.condition, operator: value }
                                                })
                                            }
                                        >
                                            <SelectTrigger id="operator" className="bg-gray-900 border-gray-600 text-gray-100 h-11 text-base sm:h-9 sm:text-sm">
                                                <SelectValue />
                                            </SelectTrigger>
                                            <SelectContent className="bg-gray-900 border-gray-600">
                                                {/* Solo las dos direcciones que la etiqueta sabe pintar
                                                    («mayor/menor a X%»): '>=', '<=' y '==' se disparaban
                                                    bien pero se anunciaban como «menor». */}
                                                <SelectItem value=">">{ti('alerts.form.operatorGt')}</SelectItem>
                                                <SelectItem value="<">{ti('alerts.form.operatorLt')}</SelectItem>
                                            </SelectContent>
                                        </Select>
                                    </div>
                                    )}
                                    <div>
                                        <Label htmlFor="value" className="text-gray-300">
                                            {formData.type === 'price_change' ? ti('alerts.form.valuePercent') : ti('alerts.form.valuePrice')}
                                        </Label>
                                        <Input
                                            id="value"
                                            // type="text" (no "number"): el input numérico
                                            // rechaza la coma decimal, así que un umbral
                                            // es-ES ("1522,60") llegaba vacío a
                                            // parseLocalizedNumber. inputMode="decimal"
                                            // conserva el teclado numérico en móvil.
                                            type="text"
                                            inputMode="decimal"
                                            value={formData.condition.value}
                                            onChange={(e) =>
                                                setFormData({
                                                    ...formData,
                                                    condition: { ...formData.condition, value: e.target.value }
                                                })
                                            }
                                            placeholder={formData.type === 'price_change' ? ti('alerts.form.percentPlaceholder') : ti('alerts.form.pricePlaceholder')}
                                            className="bg-gray-900 border-gray-600 text-gray-100 h-11 text-base sm:h-9 sm:text-sm"
                                        />
                                        {formData.type !== 'price_change' ? (
                                            <p className="mt-1 text-xs text-gray-500">
                                                {ti('alerts.form.thresholdNote')}
                                            </p>
                                        ) : null}
                                    </div>
                                </>
                            )}
                            {createError ? (
                                <div
                                    ref={createErrorRef}
                                    role="alert"
                                    tabIndex={-1}
                                    className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-200 outline-none"
                                >
                                    <p>{createError}</p>
                                    <Button
                                        type="button"
                                        size="sm"
                                        variant="outline"
                                        onClick={handleCreateAlert}
                                        disabled={creating}
                                        className="mt-2 gap-2 border-amber-500/50 text-amber-200 hover:text-amber-100"
                                    >
                                        <RefreshCcw aria-hidden="true" className="h-4 w-4" />
                                        {t('common.actions.retry')}
                                    </Button>
                                </div>
                            ) : null}
                            <Button onClick={handleCreateAlert} disabled={creating} aria-busy={creating} className="w-full min-h-[44px] text-sm sm:text-xs">
                                {ti('alerts.create')}
                            </Button>
                        </div>
                    </DialogContent>
                </Dialog>
            </div>

            {telegram ? (
                <div className="mb-4 rounded-lg border border-amber-900/60 bg-amber-950/20 p-3" role="note">
                    <p className="flex items-center gap-2 text-sm text-amber-200">
                        <Send aria-hidden="true" className="h-4 w-4" />
                        {telegram.configured ? ti('alerts.telegram.configured') : ti('alerts.telegram.notConfigured')}
                    </p>
                </div>
            ) : null}

            {loading ? (
                <div className="space-y-3 py-8">
                    {/* Un único texto de carga accesible; el spinner es decorativo. */}
                    <div aria-hidden="true" className="mx-auto h-5 w-5 animate-spin rounded-full border-2 border-gray-700 border-t-teal-300" />
                    <div className="text-center text-sm text-gray-500">{t('common.states.loadingAlerts')}</div>
                </div>
            ) : loadError ? (
                <SectionLoadError
                    message={loadError.message}
                    onRetry={() => void loadAlerts()}
                    retryLabel={t('common.actions.retry')}
                    extra={loadError.cause === 'session' ? (
                        <Link href="/sign-in" className="mt-3 inline-flex min-h-[44px] items-center text-sm text-teal-300 hover:underline">
                            {ti('alerts.session.signIn')}
                        </Link>
                    ) : undefined}
                />
            ) : alerts.length === 0 ? (
                <div className="text-center py-8 text-gray-500">
                    <Bell aria-hidden="true" className="h-12 w-12 mx-auto mb-3 text-gray-500" />
                    <p>{t('common.states.noAlerts')}</p>
                    <p className="text-sm mt-2">{t('common.states.noAlertsHint')}</p>
                    <Button
                        size="sm"
                        variant="outline"
                        className="mt-4 min-h-[44px] px-4 sm:min-h-0"
                        onClick={() => setOpen(true)}
                    >
                        <Plus aria-hidden="true" className="h-4 w-4" />
                        {ti('alerts.empty.createFirst')}
                    </Button>
                </div>
            ) : (
                <div className="space-y-3">
                    {alerts.map((alert) => (
                        <div
                            key={alert._id}
                            className="flex flex-col gap-3 p-4 bg-gray-900/50 rounded-lg border border-gray-700/50 sm:flex-row sm:items-center sm:justify-between"
                        >
                            <div className="flex-1 min-w-0">
                                <p className="text-sm font-medium text-gray-200 break-words">
                                    {getAlertLabel(alert)}
                                </p>
                                <div className="mt-1.5 flex flex-wrap items-center gap-2">
                                    <p className="text-xs text-gray-500">
                                        {ti('alerts.list.createdAt', { date: f.formatDate(alert.createdAt) })}
                                    </p>
                                    <p className={`inline-flex items-center gap-1 text-xs ${alert.lastTriggered ? 'text-amber-300' : 'text-gray-500'}`}>
                                        <History aria-hidden="true" className="h-3.5 w-3.5" />
                                        {alert.lastTriggered
                                            ? ti('alerts.list.lastTriggered', { date: f.formatUserDateTime(alert.lastTriggered) })
                                            : t('common.states.neverTriggered')}
                                    </p>
                                    <p className="inline-flex items-center gap-1 text-xs text-gray-500" title={ti('alerts.list.channelsTitle', { channels: (alert.channels.map(etiquetaCanal).join(', ') || etiquetaCanal('in_app')), count: String(alert.triggerCount) })}>
                                        <Send aria-hidden="true" className="h-3.5 w-3.5" />
                                        {alert.lastEvaluatedAt
                                            ? ti('alerts.list.motorEvaluated', { date: f.formatUserDateTime(alert.lastEvaluatedAt), count: String(alert.triggerCount), channels: (alert.channels.map(etiquetaCanal).join(', ') || etiquetaCanal('in_app')) })
                                            : ti('alerts.list.motorPending')}
                                        {alertSkipNote(alert.lastResultStatus) ? ` · ${alertSkipNote(alert.lastResultStatus)}` : null}
                                    </p>
                                    {alert.symbol ? (
                                        <Link
                                            href={`/research/${encodeURIComponent(alert.symbol)}`}
                                            className="inline-flex min-h-[44px] items-center px-2 py-2 text-xs text-teal-400 hover:text-teal-300 sm:min-h-0 sm:p-0"
                                        >
                                            {ti('alerts.list.viewResearch')}
                                        </Link>
                                    ) : null}
                                </div>
                            </div>
                            <div className="flex items-center justify-end gap-1">
                                {alert.symbol ? (
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        onClick={() => handleReview(alert)}
                                        disabled={reviewing === alert._id}
                                        aria-busy={reviewing === alert._id}
                                        aria-label={ti('alerts.list.reviewAria', { symbol: alert.symbol })}
                                        className="min-h-[44px] gap-1.5 px-3 text-xs sm:min-h-0"
                                    >
                                        <RefreshCcw aria-hidden="true" className={`h-3.5 w-3.5 ${reviewing === alert._id ? 'animate-spin' : ''}`} />
                                        {ti('alerts.list.review')}
                                    </Button>
                                ) : null}
                                <Button
                                    variant="ghost"
                                    size="sm"
                                    onClick={() => setConfirmAlert(alert)}
                                    disabled={deleting === alert._id}
                                    aria-busy={deleting === alert._id}
                                    aria-label={ti('alerts.list.deleteAria', { label: getAlertLabel(alert) })}
                                    className="min-h-[44px] min-w-[44px] text-gray-400 hover:text-red-400"
                                >
                                    <Trash2 aria-hidden="true" className="h-4 w-4" />
                                </Button>
                            </div>
                        </div>
                    ))}
                    <p className="text-xs text-gray-500">
                        {ti('alerts.list.thresholdNote')}
                    </p>
                </div>
            )}

            {!loading && triggered.length > 0 ? (
                <div className="mt-6">
                    <h3 className="text-sm font-semibold uppercase tracking-wide text-gray-400">
                        {ti('alerts.triggered.title')}
                    </h3>
                    <div className="mt-2 space-y-2">
                        {triggered.map((item) => (
                            <div
                                key={item.id}
                                className="rounded-lg border border-gray-700/50 bg-gray-900/50 p-3"
                            >
                                <div className="flex flex-wrap items-baseline justify-between gap-2">
                                    <p className="text-sm font-medium text-gray-200">{alertCardCopy(item, cardT, cardLocale).heading}</p>
                                    <time
                                        className="text-xs text-gray-500"
                                        dateTime={item.triggeredAt ?? item.createdAt}
                                        suppressHydrationWarning
                                    >
                                        {item.triggeredAt
                                            ? ti('alerts.triggered.lastShot', { date: f.formatUserDateTime(item.triggeredAt) })
                                            : ti('alerts.triggered.created', { date: f.formatUserDateTime(item.createdAt) })}
                                    </time>
                                </div>
                                {alertSummaryIsSourceHeadline(item) ? <ExternalNewsHeadline headline={alertCardCopy(item, cardT, cardLocale).summary} url={item.sourceUrl} className="mt-1 text-sm text-gray-300" /> : <p className="mt-1 text-sm text-gray-300">{alertCardCopy(item, cardT, cardLocale).summary}</p>}
                                <details className="mt-2 text-xs text-gray-400"><summary className="min-h-10 cursor-pointer py-2 text-teal-300">{ti('alerts.triggered.viewOriginal')}</summary><p className="whitespace-pre-wrap break-words">{alertCardCopy(item, cardT, cardLocale).technical}</p></details>
                                {(item.ticker || item.sourceUrl) && (
                                    <span className="mt-1 inline-flex flex-wrap gap-x-3">
                                        {item.ticker && (
                                            <Link
                                                className="inline-flex min-h-[44px] items-center text-xs text-teal-400 hover:text-teal-300 hover:underline"
                                                href={alertThesisHref(item.ticker)}
                                            >
                                                {ti('alerts.triggered.reviewThesis', { ticker: item.ticker })}
                                            </Link>
                                        )}
                                        {item.sourceUrl && (
                                            <a
                                                className="inline-flex min-h-[44px] items-center text-xs text-teal-400 hover:text-teal-300 hover:underline"
                                                href={item.sourceUrl}
                                                rel="noopener noreferrer"
                                                target="_blank"
                                            >
                                                {ti('alerts.triggered.openDocument')}
                                            </a>
                                        )}
                                    </span>
                                )}
                                <div className="mt-2 flex flex-wrap gap-1.5">
                                    {item.channels.length === 0 ? (
                                        <span className="text-xs text-gray-500">{ti('alerts.triggered.noChannels')}</span>
                                    ) : (
                                        item.channels.map((channel) => {
                                            const delivery = item.deliveries[channel];
                                            // Sin registro de entrega no hay estado «pendiente»:
                                            // mostrar pendiente sería inventar un envío en curso.
                                            const status = delivery?.status ?? ti('alerts.triggered.noDeliveryRecord');
                                            const statusText = etiquetaEstadoEntrega(status);
                                            const channelText = etiquetaCanal(channel);
                                            const tone =
                                                status === 'delivered'
                                                    ? 'border-teal-800 text-teal-300'
                                                    : status === 'failed'
                                                      ? 'border-red-800 text-red-300'
                                                      : 'border-gray-700 text-gray-400';
                                            return (
                                                <span
                                                    key={channel}
                                                    title={delivery?.error ?? ti('alerts.triggered.channelTitle', { channel: channelText, status: statusText })}
                                                    className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs ${tone}`}
                                                >
                                                    {channelText}: {statusText}
                                                </span>
                                            );
                                        })
                                    )}
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            ) : null}
            <ConfirmDialog
                open={confirmAlert !== null}
                onOpenChange={(next) => { if (!next) setConfirmAlert(null); }}
                title={ti('alerts.confirm.title')}
                description={confirmAlert ? ti('alerts.confirm.description', { label: getAlertLabel(confirmAlert) }) : ''}
                onConfirm={() => { if (confirmAlert) handleDeleteAlert(confirmAlert._id); }}
            />
        </Card>
    );
}

/**
 * `useSearchParams` exige Suspense en el árbol del cliente; el contenido real
 * vive en AlertsManager y aquí se envuelve para cumplir el contrato de Next.
 */
export default function AlertsManagerWithSuspense() {
    return (
        <Suspense fallback={<div className="py-8 text-center text-gray-500">{t('common.states.loadingAlerts')}</div>}>
            <AlertsManager />
        </Suspense>
    );
}
