'use client';

import { Check } from 'lucide-react';
import {
    Command,
    CommandEmpty,
    CommandGroup,
    CommandInput,
    CommandItem,
    CommandList,
} from '@/components/ui/command';
import { cn } from '@/lib/utils';
import { useT } from '@/lib/i18n/client';

export type CountryOption = { value: string; label: string; search: string };

/**
 * Menú del selector de país (cmdk): solo se descarga al abrir el desplegable.
 * Antes era un import estático de CountrySelectField y cmdk viajaba en el
 * bundle inicial de /sign-up, una página pública de entrada, aunque la
 * mayoría nunca abre el selector (país por defecto ES).
 */
export default function CountrySelectCommand({
    countries,
    value,
    flagFor,
    onSelect,
}: {
    countries: CountryOption[];
    value: string;
    flagFor: (countryCode: string) => string;
    onSelect: (value: string) => void;
}) {
    const t = useT();
    return (
        <Command className='bg-gray-800 border-gray-600'>
            <CommandInput
                placeholder={t('auth.signUp.countrySearchPlaceholder')}
                className='country-select-input'
            />
            <CommandEmpty className='country-select-empty'>
                {t('auth.signUp.countryEmpty')}
            </CommandEmpty>
            <CommandList className='max-h-60 bg-gray-800 scrollbar-hide-default'>
                <CommandGroup className='bg-gray-800'>
                    {countries.map((country) => (
                        <CommandItem
                            key={country.value}
                            value={country.search}
                            onSelect={() => onSelect(country.value)}
                            className='country-select-item'
                        >
                            <Check
                                className={cn(
                                    'mr-2 h-4 w-4 text-teal-500',
                                    value === country.value ? 'opacity-100' : 'opacity-0'
                                )}
                            />
                            <span className='flex items-center gap-2'>
                <span>{flagFor(country.value)}</span>
                <span>{country.label}</span>
              </span>
                        </CommandItem>
                    ))}
                </CommandGroup>
            </CommandList>
        </Command>
    );
}
