'use client';

import { useState } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { saveTaxDeclarant, type TaxDeclarant } from '@/lib/actions/taxes.actions';
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
    const [busy, setBusy] = useState(false);

    async function submit(event: React.FormEvent<HTMLFormElement>) {
        event.preventDefault();
        setBusy(true);
        try {
            const saved = await saveTaxDeclarant({
                ...values,
                filed_720_before: filed === '' ? null : filed === 'true',
                custody: Object.fromEntries(initial.partidas.map((key) => [key, (custody[key] ?? '').trim() || null])),
            });
            setValues({
                apellidos_nombre: saved.apellidos_nombre,
                nif: saved.nif,
                numero_declaracion: saved.numero_declaracion,
                telefono: saved.telefono,
            });
            setCustody(saved.custody);
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
                            autoComplete={field.autoComplete}
                            disabled={busy}
                            onChange={(event) => setValues((current) => ({ ...current, [field.key]: event.target.value }))}
                            value={values[field.key]}
                        />
                    </label>
                ))}
                <label className="space-y-1 text-sm text-gray-300">
                    <span>Presentaste el 720 en ejercicios anteriores</span>
                    <select
                        className="h-10 w-full rounded-lg border border-gray-600 bg-transparent px-3 text-sm"
                        disabled={busy}
                        onChange={(event) => setFiled(event.target.value)}
                        value={filed}
                    >
                        {FILED.map((option) => <option className="bg-gray-900" key={option.value} value={option.value}>{option.label}</option>)}
                    </select>
                </label>
            </div>
            {initial.partidas.length ? (
                <fieldset className="space-y-2">
                    <legend className="text-sm font-medium text-gray-200">País de custodia por partida (ISO, ej. IE, US, ES)</legend>
                    <div className="grid gap-3 md:grid-cols-2">
                        {initial.partidas.map((key) => (
                            <label className="flex items-center justify-between gap-3 rounded-md border border-gray-800 p-3 text-sm text-gray-300" key={key}>
                                <span className="min-w-0 break-words">{partidaLabel(key)}</span>
                                <Input
                                    aria-label={`País de custodia de ${partidaLabel(key)}`}
                                    className="w-20 uppercase"
                                    disabled={busy}
                                    maxLength={2}
                                    onChange={(event) => setCustody((current) => ({ ...current, [key]: event.target.value }))}
                                    value={custody[key] ?? ''}
                                />
                            </label>
                        ))}
                    </div>
                </fieldset>
            ) : null}
            <Button disabled={busy} type="submit">{busy ? 'Guardando…' : 'Guardar'}</Button>
        </form>
    );
}
