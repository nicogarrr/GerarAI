'use client';
import { TickerSearchInput } from '@/components/search/TickerSearchInput';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Plus, Target, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { upsertPlan, type PlanTargetInput } from '@/lib/actions/plan.actions';
import { todayLocal } from '@/lib/format';
import { parseLocalizedNumber } from '@/lib/i18n/parse-number';
import { useFormat, useLocale, useT } from '@/lib/i18n/client';
import { overallocatedDimension } from '@/lib/plan/target-totals';
import { showErrorToast } from '@/lib/toast';
import { toast } from 'sonner';

type AllocationRow = { kind: PlanTargetInput['kind']; label: string; target_pct: string; band_pct: string };

/**
 * Alta/edición del plan de inversión (B12): el backend tenía PUT /api/plan
 * pero la UI no ofrecía ninguna vía para crear el plan.
 */
type PlanInitial = {
    monthly_contribution?: unknown;
    start_date?: unknown;
    horizon_years?: unknown;
    target_allocations?: unknown;
    monthly_contribution_currency?: unknown;
    currency_contract_enabled?: unknown;
};

// Sin `required` nativo: el aviso propio (role=alert) es el que se ve y se anuncia.
const CURRENCY_OPTIONS = ['EUR', 'USD', 'GBP', 'CHF', 'JPY'];

export default function PlanSetupDialog({
    triggerLabel,
    initial,
    onSaved,
}: {
    triggerLabel?: string;
    /** Plan existente para precargar el formulario (edición). */
    initial?: PlanInitial | null;
    onSaved?: () => void;
}) {
    const router = useRouter();
    const t = useT();
    const f = useFormat();
    const locale = useLocale();
    const triggerText = triggerLabel ?? t('plan.setup.trigger');
    const currencyRequiredError = t('plan.setup.currencyRequired');
    function asText(value: unknown): string {
        // Números del backend en la gramática del locale activo (el parser
        // del formulario la espera): String(300.5) daría «300.5» con punto;
        // las fechas y demás cadenas pasan intactas.
        if (typeof value === 'number') return f.formatNumberForInput(value);
        return typeof value === 'string' ? value : '';
    }
    const [open, setOpen] = useState(false);
    const [pending, setPending] = useState(false);
    const [error, setError] = useState<string | null>(null);
    // Capability del backend: sin ella el contrato de divisa no existe (flag OFF).
    const currencyEnabled = initial?.currency_contract_enabled === true;
    const [currency, setCurrency] = useState(() => asText(initial?.monthly_contribution_currency).toUpperCase());
    const legacyWithoutCurrency = Boolean(initial) && !currency;
    const [monthly, setMonthly] = useState(() => asText(initial?.monthly_contribution));
    const [startDate, setStartDate] = useState(
        () => asText(initial?.start_date) || todayLocal(),
    );
    const [horizon, setHorizon] = useState(() => asText(initial?.horizon_years) || '30');
    const [rows, setRows] = useState<AllocationRow[]>(() => {
        const allocations = Array.isArray(initial?.target_allocations)
            ? (initial?.target_allocations as Record<string, unknown>[])
            : [];
        const parsed = allocations
            .filter((a) => a && typeof a === 'object')
            .map((a): AllocationRow => ({
                kind: a.kind === 'sector' || a.kind === 'asset_class' ? a.kind : 'ticker',
                label: asText(a.label),
                target_pct: asText(a.target_pct),
                band_pct: asText(a.band_pct) || '5',
            }))
            .filter((a) => a.label);
        return parsed.length ? parsed : [{ kind: 'ticker', label: '', target_pct: '', band_pct: '5' }];
    });

    const addRow = () => setRows((prev) => [...prev, { kind: 'ticker', label: '', target_pct: '', band_pct: '5' }]);
    const removeRow = (index: number) => setRows((prev) => prev.filter((_, i) => i !== index));
    const updateRow = (index: number, patch: Partial<AllocationRow>) =>
        setRows((prev) => prev.map((row, i) => (i === index ? { ...row, ...patch } : row)));

    const handleSubmit = async (event: React.FormEvent) => {
        event.preventDefault();
        setError(null);

        const monthlyContribution = parseLocalizedNumber(monthly, locale);
        if (monthlyContribution === null || monthlyContribution <= 0) {
            setError(t('plan.setup.errorMonthly'));
            return;
        }
        if (currencyEnabled && !currency) {
            setError(currencyRequiredError);
            return;
        }
        // parseInt truncaba "30,5" a 30 en silencio: solo se aceptan enteros exactos (F388).
        const horizonYears = /^\d+$/.test(horizon.trim()) ? Number(horizon.trim()) : Number.NaN;
        if (!Number.isInteger(horizonYears) || horizonYears < 1 || horizonYears > 80) {
            setError(t('plan.setup.errorHorizon'));
            return;
        }
        const allocations: PlanTargetInput[] = [];
        for (const row of rows) {
            const label = row.kind === 'ticker' ? row.label.trim().toUpperCase() : row.label.trim();
            if (!label && !row.target_pct.trim()) continue;
            const pct = parseLocalizedNumber(row.target_pct, locale);
            if (!label || pct === null || pct < 0 || pct > 100) {
                setError(t('plan.setup.errorAllocation'));
                return;
            }
            const band = parseLocalizedNumber(row.band_pct, locale);
            if (band === null || band < 0 || band > 50) {
                setError(t('plan.setup.errorBand'));
                return;
            }
            if (allocations.some((allocation) => allocation.kind === row.kind && allocation.label.toUpperCase() === label.toUpperCase())) {
                setError(t('plan.setup.errorDuplicate'));
                return;
            }
            allocations.push({ kind: row.kind, label, target_pct: pct, band_pct: band });
        }
        const overallocated = overallocatedDimension(allocations);
        if (overallocated) {
            const labels = {
                ticker: t('plan.setup.dimensionTicker'),
                sector: t('plan.setup.dimensionSector'),
                asset_class: t('plan.setup.dimensionAssetClass'),
            };
            setError(
                t('plan.setup.overallocated', {
                    dimension: labels[overallocated.kind],
                    total: f.formatNumber(overallocated.total, { maximumFractionDigits: 2 }),
                }),
            );
            return;
        }

        setPending(true);
        try {
            const result = await upsertPlan({
                monthly_contribution: monthlyContribution,
                ...(currencyEnabled ? { monthly_contribution_currency: currency } : {}),
                start_date: startDate,
                horizon_years: horizonYears,
                target_allocations: allocations,
            });
            if (!result.ok) {
                // Rechazo del contrato de divisa: nada se guardo; aviso inline y diálogo abierto.
                setError(
                    result.code === 'plan_currency_required_for_amount_change'
                        ? t('plan.setup.errorCurrencyChange')
                        : t('plan.setup.errorCurrencyUnavailable'),
                );
                return;
            }
            toast.success(t('plan.setup.savedToast'));
            setOpen(false);
            router.refresh();
            onSaved?.();
        } catch (exc) {
            showErrorToast(exc, { onRetry: () => handleSubmitRetry() });
        } finally {
            setPending(false);
        }
    };

    // Reintento desde el toast (motor caído): reenvía el último submit válido.
    const handleSubmitRetry = async () => {
        const form = document.getElementById('plan-setup-form') as HTMLFormElement | null;
        form?.requestSubmit();
    };

    return (
        <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
                <Button type="button" className="gap-2">
                    <Target className="h-4 w-4" />
                    {triggerText}
                </Button>
            </DialogTrigger>
            <DialogContent className="border-gray-700 bg-gray-900 text-gray-100 sm:max-w-xl max-h-[90dvh] overflow-y-auto">
                <DialogHeader>
                    <DialogTitle>{t('plan.setup.title')}</DialogTitle>
                    <DialogDescription className="text-gray-400">
                        {t('plan.setup.description')}
                    </DialogDescription>
                </DialogHeader>
                <form id="plan-setup-form" onSubmit={handleSubmit} className="space-y-4">
                    {/* items-end: la etiqueta «Aportación mensual (€)» ocupa dos líneas a ancho
                    de diálogo y el campo quedaba 14 px más bajo que Inicio/Horizonte. */}
                    <div className="grid items-end gap-4 sm:grid-cols-3">
                        <div className="space-y-1.5">
                            <Label htmlFor="plan-monthly" className="text-gray-300">{currencyEnabled ? t('plan.setup.monthlyLabel') : t('plan.setup.monthlyLabelEur')}</Label>
                            <Input
                                id="plan-monthly"
                                inputMode="decimal"
                                value={monthly}
                                onChange={(e) => setMonthly(e.target.value)}
                                placeholder="300"
                                className="border-gray-700 bg-gray-800 text-gray-100"
                                required
                            />
                        </div>
                        <div className="space-y-1.5">
                            <Label htmlFor="plan-start" className="text-gray-300">{t('plan.setup.startLabel')}</Label>
                            <Input
                                id="plan-start"
                                type="date"
                                value={startDate}
                                onChange={(e) => setStartDate(e.target.value)}
                                className="border-gray-700 bg-gray-800 text-gray-100"
                                required
                            />
                        </div>
                        <div className="space-y-1.5">
                            <Label htmlFor="plan-horizon" className="text-gray-300">{t('plan.setup.horizonLabel')}</Label>
                            <Input
                                id="plan-horizon"
                                inputMode="numeric"
                                value={horizon}
                                onChange={(e) => setHorizon(e.target.value)}
                                className="border-gray-700 bg-gray-800 text-gray-100"
                                required
                            />
                        </div>
                    </div>

                    {currencyEnabled ? (
                        <div className="space-y-1.5">
                            <Label htmlFor="plan-currency" className="text-gray-300">{t('plan.setup.currencyLabel')}</Label>
                            <select
                                id="plan-currency"
                                value={currency}
                                onChange={(e) => setCurrency(e.target.value)}
                                aria-invalid={error === currencyRequiredError}
                                className="h-9 w-full rounded-md border border-gray-700 bg-gray-800 px-2 text-sm text-gray-100"
                            >
                                <option value="" disabled>{t('plan.setup.currencyPlaceholder')}</option>
                                {/* Una divisa registrada fuera de la lista se conserva como opción: nunca se muestra otra. */}
                                {(currency && !CURRENCY_OPTIONS.includes(currency) ? [currency, ...CURRENCY_OPTIONS] : CURRENCY_OPTIONS).map((code) => (
                                    <option key={code} value={code}>{code}</option>
                                ))}
                            </select>
                            {legacyWithoutCurrency ? (
                                <p className="text-xs text-amber-300">{t('plan.setup.currencyLegacyNote')}</p>
                            ) : null}
                        </div>
                    ) : null}

                    <div className="space-y-2">
                        <p className="text-sm font-medium text-gray-300">{t('plan.setup.allocationTitle')}</p>
                        {rows.map((row, index) => (
                            <div key={index} className="grid grid-cols-2 items-center gap-2 rounded-md border border-gray-800 p-2 sm:grid-cols-[9.5rem_1fr_5rem_5rem_auto]">
                                {/* 9.5rem fijos: con 1fr «Clase de activo» quedaba truncado («Clase de a»). */}
                                <select
                                    aria-label={t('plan.setup.categoryAria', { n: index + 1 })}
                                    value={row.kind}
                                    onChange={(e) => updateRow(index, { kind: e.target.value as AllocationRow['kind'] })}
                                    className="h-9 min-w-0 rounded-md border border-gray-700 bg-gray-800 px-2 text-sm text-gray-100"
                                >
                                    <option value="ticker">{t('plan.setup.kindTicker')}</option>
                                    <option value="sector">{t('plan.setup.kindSector')}</option>
                                    <option value="asset_class">{t('plan.setup.kindAssetClass')}</option>
                                </select>
                                {row.kind === 'ticker' ? (
                                <TickerSearchInput
                                    ariaLabel={t('plan.setup.targetAria', { n: index + 1 })}
                                    value={row.label}
                                    onValueChange={(value) => updateRow(index, { label: value })}
                                    onSelect={(stock) => updateRow(index, { label: stock.symbol })}
                                    placeholder={t('plan.setup.searchPlaceholder')}
                                    className="border-gray-700 bg-gray-800 text-gray-100"
                                />
                                ) : (
                                <Input
                                    aria-label={t('plan.setup.targetAria', { n: index + 1 })}
                                    value={row.label}
                                    onChange={(e) => updateRow(index, { label: e.target.value })}
                                    placeholder={t('plan.setup.labelPlaceholder')}
                                    className="border-gray-700 bg-gray-800 text-gray-100"
                                />
                                )}
                                <Input
                                    aria-label={t('plan.setup.targetPctAria', { n: index + 1 })}
                                    inputMode="decimal"
                                    value={row.target_pct}
                                    onChange={(e) => updateRow(index, { target_pct: e.target.value })}
                                    placeholder="%"
                                    className="min-w-0 border-gray-700 bg-gray-800 text-gray-100"
                                />
                                <Input
                                    aria-label={t('plan.setup.bandAria', { n: index + 1 })}
                                    inputMode="decimal"
                                    value={row.band_pct}
                                    onChange={(e) => updateRow(index, { band_pct: e.target.value })}
                                    placeholder={t('plan.setup.bandPlaceholder')}
                                    className="min-w-0 border-gray-700 bg-gray-800 text-gray-100"
                                />
                                <Button
                                    type="button"
                                    variant="ghost"
                                    size="sm"
                                    onClick={() => removeRow(index)}
                                    disabled={rows.length === 1}
                                    aria-label={t('plan.setup.removeRow')}
                                    className="text-gray-400 hover:text-red-400"
                                >
                                    <Trash2 className="h-4 w-4" />
                                </Button>
                            </div>
                        ))}
                        <Button type="button" variant="outline" size="sm" onClick={addRow} className="gap-2 border-gray-600 text-gray-300">
                            <Plus className="h-4 w-4" />
                            {t('plan.addTicker')}
                        </Button>
                    </div>

                    {error ? (
                        <p className="text-sm text-red-300" role="alert">{error}</p>
                    ) : null}

                    <div className="flex justify-end gap-2">
                        <Button type="button" variant="outline" onClick={() => setOpen(false)} className="border-gray-600 text-gray-300">
                            {t('plan.setup.cancel')}
                        </Button>
                        <Button type="submit" disabled={pending}>
                            {pending ? t('plan.setup.saving') : t('plan.setup.save')}
                        </Button>
                    </div>
                </form>
            </DialogContent>
        </Dialog>
    );
}
