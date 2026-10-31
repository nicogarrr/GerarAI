'use client';

import { useState } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { saveTaxDeclarant, type TaxCustodyEntity, type TaxDeclarant } from '@/lib/actions/taxes.actions';
import { useT } from '@/lib/i18n/client';
import type { TranslateFn } from '@/lib/i18n/translate';
import { spanishTaxIdWarning } from '@/lib/nif';
import { showErrorToast } from '@/lib/toast';

const FIELDS = [
    { key: 'apellidos_nombre', label: 'settings.tax.fields.fullName', autoComplete: 'name' },
    { key: 'nif', label: 'settings.tax.fields.nif', autoComplete: 'off' },
    { key: 'numero_declaracion', label: 'settings.tax.fields.returnNumber', autoComplete: 'off' },
    { key: 'telefono', label: 'settings.tax.fields.phone', autoComplete: 'tel' },
] as const;

const FILED = [
    { value: '', label: 'settings.tax.filed.unset' },
    { value: 'true', label: 'settings.tax.filed.yes' },
    { value: 'false', label: 'settings.tax.filed.no' },
] as const;

const ENTITY_FIELDS: { key: keyof TaxCustodyEntity; label: `settings.tax.entity.${keyof TaxCustodyEntity}` }[] = [
    { key: 'name', label: 'settings.tax.entity.name' },
    { key: 'nif', label: 'settings.tax.entity.nif' },
    { key: 'street', label: 'settings.tax.entity.street' },
    { key: 'complement', label: 'settings.tax.entity.complement' },
    { key: 'city', label: 'settings.tax.entity.city' },
    { key: 'region', label: 'settings.tax.entity.region' },
    { key: 'zip', label: 'settings.tax.entity.zip' },
    { key: 'country', label: 'settings.tax.entity.country' },
];

const EMPTY_ENTITY: TaxCustodyEntity = { name: '', nif: '', street: '', city: '', zip: '', country: '', complement: '', region: '' };
const ISIN = /^[A-Z]{2}[A-Z0-9]{9}\d$/;

function partidaLabel(key: string, t: TranslateFn): string {
    return key.startsWith('cash:') ? t('settings.tax.cashAccount', { currency: key.slice(5) }) : key;
}

export default function TaxDeclarantForm({ initial }: { initial: TaxDeclarant }) {
    const t = useT();
    const [values, setValues] = useState({
        apellidos_nombre: initial.apellidos_nombre,
        nif: initial.nif,
        numero_declaracion: initial.numero_declaracion,
        telefono: initial.telefono,
    });
    const [filed, setFiled] = useState(initial.filed_720_before === null ? '' : String(initial.filed_720_before));
    const [custody, setCustody] = useState<Record<string, string>>(initial.custody);
    const [entities, setEntities] = useState<Record<string, TaxCustodyEntity>>(initial.custody_entities);
    const [dates, setDates] = useState<Record<string, string>>(initial.first_acquisition_dates);
    const [busy, setBusy] = useState(false);
    // Aviso suave (no bloquea el guardado: puede ser un NIF extranjero).
    const nifWarning = spanishTaxIdWarning(values.nif);

    async function submit(event: React.FormEvent<HTMLFormElement>) {
        event.preventDefault();
        setBusy(true);
        try {
            const saved = await saveTaxDeclarant({
                ...values,
                filed_720_before: filed === '' ? null : filed === 'true',
                custody: Object.fromEntries(initial.partidas.map((key) => [key, (custody[key] ?? '').trim() || null])),
                custody_entities: Object.fromEntries(initial.partidas.map((key) => [key, entities[key] ?? null])),
                first_acquisition_dates: Object.fromEntries(
                    initial.partidas.filter((key) => ISIN.test(key)).map((key) => [key, dates[key] || null]),
                ),
            });
            setValues({
                apellidos_nombre: saved.apellidos_nombre,
                nif: saved.nif,
                numero_declaracion: saved.numero_declaracion,
                telefono: saved.telefono,
            });
            setCustody(saved.custody);
            setEntities(saved.custody_entities);
            setDates(saved.first_acquisition_dates);
            toast.success(t('settings.tax.saved'));
        } catch (cause) {
            showErrorToast(cause);
        } finally {
            setBusy(false);
        }
    }

    return (
        <form onSubmit={submit} className="space-y-5">
            <div className="grid gap-4 md:grid-cols-2">
                {FIELDS.map((field) => (
                    <label className="space-y-1 text-sm text-gray-300" key={field.key}>
                        <span>{t(field.label)}</span>
                        <Input
                            // Sin aria-label el aviso suave (que vive dentro del
                            // <label>) pasaba al nombre accesible del campo y el
                            // lector de pantalla lo anunciaba como su nombre; el
                            // aviso corresponde a la descripción, no al nombre.
                            aria-label={t(field.label)}
                            aria-describedby={field.key === 'nif' && nifWarning ? 'tax-declarant-nif-warning' : undefined}
                            className="h-11"
                            autoComplete={field.autoComplete}
                            disabled={busy}
                            onChange={(event) => setValues((current) => ({ ...current, [field.key]: event.target.value }))}
                            value={values[field.key]}
                        />
                        {field.key === 'nif' && nifWarning ? (
                            <p className="text-xs text-amber-400/90" id="tax-declarant-nif-warning" role="status">
                                {nifWarning}
                            </p>
                        ) : null}
                    </label>
                ))}
                <label className="space-y-1 text-sm text-gray-300">
                    <span>{t('settings.tax.filedBefore')}</span>
                    <select
                        className="h-11 w-full rounded-lg border border-gray-600 bg-transparent px-3 text-base sm:text-sm"
                        disabled={busy}
                        onChange={(event) => setFiled(event.target.value)}
                        value={filed}
                    >
                        {FILED.map((option) => <option className="bg-gray-900" key={option.value} value={option.value}>{t(option.label)}</option>)}
                    </select>
                </label>
            </div>
            {initial.partidas.length ? (
                <details className="rounded-lg border border-gray-800 p-3">
                    <summary className="min-h-11 cursor-pointer py-2 text-sm font-medium text-gray-200">
                        {t('settings.tax.custodyTitle', { count: initial.partidas.length })}
                    </summary>
                    <fieldset className="mt-3 space-y-2">
                    <legend className="sr-only">{t('settings.tax.custodyLegend')}</legend>
                    <div className="space-y-3">
                        {initial.partidas.map((key) => {
                            const entity = entities[key] ?? EMPTY_ENTITY;
                            return (
                                <div className="rounded-md border border-gray-800 p-3 text-sm text-gray-300" key={key}>
                                    <div className="flex flex-wrap items-center justify-between gap-3">
                                        <span className="min-w-0 break-words font-medium">{partidaLabel(key, t)}</span>
                                        <label className="flex items-center gap-2 text-xs text-gray-400" htmlFor={`custody-country-${key}`}>
                                            <span>{t('settings.tax.custodyCountry')}</span>
                                            <Input
                                                aria-label={t('settings.tax.custodyCountryOf', { item: partidaLabel(key, t) })}
                                                className="h-11 w-24 uppercase"
                                                id={`custody-country-${key}`}
                                                placeholder={t('settings.tax.countryPlaceholder')}
                                                disabled={busy}
                                                maxLength={2}
                                                onChange={(event) => setCustody((current) => ({ ...current, [key]: event.target.value }))}
                                                value={custody[key] ?? ''}
                                            />
                                        </label>
                                    </div>
                                    <details className="mt-3">
                                        <summary className="min-h-11 cursor-pointer py-2 text-teal-300">{t('settings.tax.entityAndDate')}</summary>
                                        <div className="mt-2 grid gap-3 md:grid-cols-2">
                                            {ISIN.test(key) ? (
                                                <label className="space-y-1">
                                                    <span>{t('settings.tax.firstAcquisition')}</span>
                                                    <Input
                                                        className="h-11"
                                                        disabled={busy}
                                                        onChange={(event) => setDates((current) => ({ ...current, [key]: event.target.value }))}
                                                        type="date"
                                                        value={dates[key] ?? ''}
                                                    />
                                                </label>
                                            ) : null}
                                            {ENTITY_FIELDS.map((field) => (
                                                <label className="space-y-1" key={field.key}>
                                                    <span>{t(field.label)}</span>
                                                    <Input
                                                        className="h-11"
                                                        disabled={busy}
                                                        onChange={(event) => setEntities((current) => ({
                                                            ...current,
                                                            [key]: { ...(current[key] ?? EMPTY_ENTITY), [field.key]: event.target.value },
                                                        }))}
                                                        value={entity[field.key]}
                                                    />
                                                </label>
                                            ))}
                                        </div>
                                    </details>
                                </div>
                            );
                        })}
                    </div>
                    </fieldset>
                </details>
            ) : null}
            <Button disabled={busy} type="submit">{busy ? t('settings.common.saving') : t('settings.common.save')}</Button>
        </form>
    );
}
