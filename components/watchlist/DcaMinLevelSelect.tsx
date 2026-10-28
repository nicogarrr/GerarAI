'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { setDcaAlertMinLevel } from '@/lib/actions/dca-signals.actions';
import { DCA_MIN_LEVEL_OPTIONS } from '@/lib/dca/format';
import { showErrorToast } from '@/lib/toast';

interface DcaMinLevelSelectProps {
    symbol: string;
    override: number | null;
    globalMinLevel: number;
}

/** Nivel mínimo de aviso DCA por ticker: Global / 1X-4X / Desactivado. */
export default function DcaMinLevelSelect({ symbol, override, globalMinLevel }: DcaMinLevelSelectProps) {
    const router = useRouter();
    const [value, setValue] = useState(override === null ? 'global' : String(override));
    const [saving, setSaving] = useState(false);

    const labelFor = (option: string) =>
        option === 'global'
            ? `Global (${globalMinLevel}X)`
            : DCA_MIN_LEVEL_OPTIONS.find((entry) => entry.value === option)?.label ?? option;

    const handleChange = async (next: string) => {
        const previous = value;
        setValue(next);
        setSaving(true);
        try {
            const res = await setDcaAlertMinLevel(symbol, next === 'global' ? null : Number(next));
            if (res.success) {
                toast.success(`Avisos DCA de ${symbol}: ${labelFor(next)}`);
                router.refresh();
            } else {
                setValue(previous);
                showErrorToast(res.message ?? 'No se pudo guardar el nivel de aviso');
            }
        } catch (error) {
            setValue(previous);
            showErrorToast(error);
        } finally {
            setSaving(false);
        }
    };

    return (
        <Select value={value} onValueChange={handleChange} disabled={saving}>
            <SelectTrigger
                aria-label={`Nivel mínimo de aviso DCA para ${symbol}`}
                className="min-h-11 w-[150px] border-gray-700 bg-gray-800 text-xs text-gray-300"
            >
                <SelectValue>{labelFor(value)}</SelectValue>
            </SelectTrigger>
            <SelectContent className="border-gray-700 bg-gray-800">
                {DCA_MIN_LEVEL_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value} className="text-xs text-gray-200">
                        {labelFor(option.value)}
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    );
}
