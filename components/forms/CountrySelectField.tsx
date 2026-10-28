/* eslint-disable @typescript-eslint/no-explicit-any */
'use client';

import { useMemo, useState } from 'react';
import { Control, Controller, FieldError, FieldValues, Path } from 'react-hook-form';
import {
    Popover,
    PopoverContent,
    PopoverTrigger,
} from '@/components/ui/popover';
import dynamic from 'next/dynamic';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { ChevronsUpDown } from 'lucide-react';
import type { CountryOption } from '@/components/forms/CountrySelectCommand';

// El menú (cmdk) solo se descarga al abrir el desplegable: /sign-up es una
// página pública de entrada y el selector casi nunca se abre (defecto ES).
// Se precarga al pulsar/enfocar el gatillo para que no se note.
const CountrySelectCommand = dynamic(() => import('@/components/forms/CountrySelectCommand'), {
    loading: () => <div className='h-40 animate-pulse rounded bg-gray-800' aria-hidden='true' />,
});
const preloadCountryCommand = () => void import('@/components/forms/CountrySelectCommand');
import countryList from 'react-select-country-list';

// Los nombres visibles van en español; el value sigue siendo el código ISO.
// `react-select-country-list` solo trae etiquetas en inglés. Si el runtime no
// implementa `Intl.DisplayNames` (o falla para un código), se conserva la
// etiqueta inglesa: la pantalla nunca se queda sin nombre.
const regionNames = (() => {
    try {
        if (typeof Intl === 'undefined' || typeof Intl.DisplayNames !== 'function') return null;
        return new Intl.DisplayNames(['es'], { type: 'region' });
    } catch {
        return null;
    }
})();

function countryLabel(code: string, fallback: string): string {
    try {
        return regionNames?.of(code) ?? fallback;
    } catch {
        return fallback;
    }
}

type CountrySelectProps<TFieldValues extends FieldValues = FieldValues> = {
    name: Path<TFieldValues>;
    label: string;
    control: Control<TFieldValues, any, any>;
    error?: FieldError;
    required?: boolean;
};

const CountrySelect = ({
                           value,
                           onChange,
                           invalid = false,
                           describedBy,
                           label,
                       }: {
    value: string;
    onChange: (value: string) => void;
    invalid?: boolean;
    describedBy?: string;
    label: string;
}) => {
    const [open, setOpen] = useState(false);

    // Get country options with Spanish labels and flags. `search` lleva el
    // nombre español, el inglés original y el ISO para que buscar «España»
    // (o «Spain», o «ES») encuentre la misma opción.
    const countries: CountryOption[] = useMemo(
        () => countryList().getData().map((country) => {
            const label = countryLabel(country.value, country.label);
            return {
                value: country.value,
                label,
                search: `${label} ${country.label} ${country.value}`,
            };
        }),
        [],
    );

    // Helper function to get flag emoji
    const getFlagEmoji = (countryCode: string) => {
        const codePoints = countryCode
            .toUpperCase()
            .split('')
            .map((char) => 127397 + char.charCodeAt(0));
        return String.fromCodePoint(...codePoints);
    };

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger asChild>
                <Button
                    variant='outline'
                    role='combobox'
                    onPointerDown={preloadCountryCommand}
                    onFocus={preloadCountryCommand}
                    aria-expanded={open}
                    aria-label={label}
                    aria-invalid={invalid}
                    aria-describedby={describedBy}
                    className='country-select-trigger'
                >
                    {value ? (
                        <span className='flex items-center gap-2'>
              <span>{getFlagEmoji(value)}</span>
              <span>{countries.find((c) => c.value === value)?.label}</span>
            </span>
                    ) : (
                        'Selecciona tu país…'
                    )}
                    <ChevronsUpDown className='ml-2 h-4 w-4 shrink-0 opacity-50' />
                </Button>
            </PopoverTrigger>
            <PopoverContent
                className='w-full p-0 bg-gray-800 border-gray-600'
                align='start'
            >
                <CountrySelectCommand
                    countries={countries}
                    value={value}
                    flagFor={getFlagEmoji}
                    onSelect={(next) => {
                        onChange(next);
                        setOpen(false);
                    }}
                />
            </PopoverContent>
        </Popover>
    );
};

export const CountrySelectField = <TFieldValues extends FieldValues = FieldValues>({
                                       name,
                                       label,
                                       control,
                                       error,
                                       required = false,
                                   }: CountrySelectProps<TFieldValues>) => {
    const errorId = `${name}-error`;
    const hintId = `${name}-hint`;
    return (
        <div className='space-y-2'>
            <Label htmlFor={name} className='form-label'>
                {label}
            </Label>
            <Controller
                name={name}
                control={control}
                rules={{
                    required: required ? `Por favor, selecciona ${label.toLowerCase()}` : false,
                }}
                render={({ field }) => (
                    <CountrySelect
                        value={field.value}
                        onChange={field.onChange}
                        label={label}
                        invalid={!!error}
                        describedBy={error ? errorId : hintId}
                    />
                )}
            />
            {error ? <p id={errorId} role='alert' className='text-sm text-red-500'>{error.message}</p> : null}
            <p id={hintId} className='text-xs text-gray-500'>
                Te mostramos datos de mercado y noticias relevantes según tu país.
            </p>
        </div>
    );
};