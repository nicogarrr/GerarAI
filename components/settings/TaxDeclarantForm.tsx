'use client';

import { useState } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { saveTaxDeclarant, type TaxCustodyEntity, type TaxDeclarant } from '@/lib/actions/taxes.actions';
import { spanishTaxIdWarning } from '@/lib/nif';
import { showErrorToast } from '@/lib/toast';

const FIELDS = [
    { key: 'apellidos_nombre', label: 'Apellidos y nombre', autoComplete: 'name' },
    { key: 'nif', label: 'NIF', autoComplete: 'off' },
    { key: 'numero_declaracion', label: 'Número de declaración (720)', autoComplete: 'off' },
    { key: 'telefono', label: 'Teléfono', autoComplete: 'tel' },
] as const;

const FILED = [
    { value: '', label: 'Sin indicar' },
    { value: 'true', label: 'Sí' },
    { value: 'false', label: 'No' },
] as const;

const ENTITY_FIELDS: { key: keyof TaxCustodyEntity; label: string }[] = [
    { key: 'name', label: 'Entidad depositaria' },
    { key: 'nif', label: 'NIF de la entidad' },
    { key: 'street', label: 'Domicilio' },
    { key: 'complement', label: 'Complemento' },
    { key: 'city', label: 'Ciudad' },
    { key: 'region', label: 'Región' },
    { key: 'zip', label: 'Código postal' },
    { key: 'country', label: 'País (ISO)' },
];

const EMPTY_ENTITY: TaxCustodyEntity = { name: '', nif: '', street: '', city: '', zip: '', country: '', complement: '', region: '' };
const ISIN = /^[A-Z]{2}[A-Z0-9]{9}\d$/;

function partidaLabel(key: string): string {
    return key.startsWith('cash:') ? `Cuenta ${key.slice(5)}` : key;
}

export default function TaxDeclarantForm({ initial }: { initial: TaxDeclarant }) {
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
            toast.success('Datos guardados');
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
                        <span>{field.label}</span>
                        <Input
                            // Sin aria-label el aviso suave (que vive dentro del
                            // <label>) pasaba al nombre accesible del campo y el
                            // lector de pantalla lo anunciaba como su nombre; el
                            // aviso corresponde a la descripción, no al nombre.
                            aria-label={field.label}
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
                    <span>Presentaste el 720 en ejercicios anteriores</span>
                    <select
                        className="h-11 w-full rounded-lg border border-gray-600 bg-transparent px-3 text-sm"
                        disabled={busy}
                        onChange={(event) => setFiled(event.target.value)}
                        value={filed}
                    >
                        {FILED.map((option) => <option className="bg-gray-900" key={option.value} value={option.value}>{option.label}</option>)}
                    </select>
                </label>
            </div>
            {initial.partidas.length ? (
                <details className="rounded-lg border border-gray-800 p-3">
                    <summary className="min-h-11 cursor-pointer py-2 text-sm font-medium text-gray-200">
                        Custodia por partida ({initial.partidas.length})
                    </summary>
                    <fieldset className="mt-3 space-y-2">
                    <legend className="sr-only">Custodia por partida</legend>
                    <div className="space-y-3">
                        {initial.partidas.map((key) => {
                            const entity = entities[key] ?? EMPTY_ENTITY;
                            return (
                                <div className="rounded-md border border-gray-800 p-3 text-sm text-gray-300" key={key}>
                                    <div className="flex flex-wrap items-center justify-between gap-3">
                                        <span className="min-w-0 break-words font-medium">{partidaLabel(key)}</span>
                                        <label className="flex items-center gap-2 text-xs text-gray-400" htmlFor={`custody-country-${key}`}>
                                            <span>País de custodia</span>
                                            <Input
                                                aria-label={`País de custodia de ${partidaLabel(key)}`}
                                                className="h-11 w-24 uppercase"
                                                id={`custody-country-${key}`}
                                                placeholder="Ej. ES"
                                                disabled={busy}
                                                maxLength={2}
                                                onChange={(event) => setCustody((current) => ({ ...current, [key]: event.target.value }))}
                                                value={custody[key] ?? ''}
                                            />
                                        </label>
                                    </div>
                                    <details className="mt-3">
                                        <summary className="min-h-11 cursor-pointer py-2 text-teal-300">Entidad depositaria y fecha</summary>
                                        <div className="mt-2 grid gap-3 md:grid-cols-2">
                                            {ISIN.test(key) ? (
                                                <label className="space-y-1">
                                                    <span>Primera adquisición</span>
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
                                                    <span>{field.label}</span>
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
            <Button disabled={busy} type="submit">{busy ? 'Guardando…' : 'Guardar'}</Button>
        </form>
    );
}
