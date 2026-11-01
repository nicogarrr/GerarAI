'use client';

import { useRouter } from 'next/navigation';
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select';
import { useT } from '@/lib/i18n/client';

interface Strategy {
    id: string;
    name: string;
    description: string;
}

interface StrategySelectorProps {
    strategies: Strategy[];
    currentStrategy: string;
    /** Callback opcional para notificar cambios sin depender de la navegación */
    onStrategyChange?: (strategyId: string) => void;
    /**
     * Catálogo público completo (p. ej. las 4 estrategias Propicks). Las que no
     * estén en `strategies` se muestran igual pero marcadas como «sin datos»,
     * para poder seleccionarlas y ver su ficha honesta.
     */
    catalog?: Strategy[];
}

export default function StrategySelector({ strategies, currentStrategy, onStrategyChange, catalog }: StrategySelectorProps) {
    const router = useRouter();
    const t = useT();

    const handleStrategyChange = (strategyId: string) => {
        onStrategyChange?.(strategyId);
        router.push(`/propicks?strategy=${strategyId}`);
        router.refresh();
    };

    // Catálogo público primero; las no servidas por el backend van marcadas.
    const options: Array<Strategy & { available: boolean }> =
        catalog && catalog.length > 0
            ? catalog.map((entry) => {
                  const server = strategies.find((s) => s.id === entry.id);
                  return server
                      ? { ...server, available: true }
                      : { ...entry, available: false };
              })
            : strategies.map((s) => ({ ...s, available: true }));
    // Estrategias del servidor fuera del catálogo (compatibilidad futura).
    for (const s of strategies) {
        if (catalog && catalog.length > 0 && !catalog.some((c) => c.id === s.id)) {
            options.push({ ...s, available: true });
        }
    }

    // F151: el SelectValue de Radix pinta por defecto TODO el contenido del
    // item seleccionado (nombre + descripción), así que el selector cerrado
    // mostraba un fragmento de la descripción. El valor cerrado muestra solo
    // el nombre; la descripción sigue dentro del desplegable.
    const selectedOption = options.find((option) => option.id === currentStrategy);

    return (
        <div className="flex w-full min-w-0 flex-col gap-3 sm:flex-row sm:items-center sm:gap-4">
            <label className="shrink-0 text-sm font-medium text-gray-400">{t('propicks.strategySelector.label')}</label>
            <Select value={currentStrategy} onValueChange={handleStrategyChange}>
                <SelectTrigger aria-label={t('propicks.strategySelector.aria')} className="h-11 w-full border-gray-700 bg-gray-800 text-sm text-gray-300 sm:w-[300px]">
                    <SelectValue placeholder={t('propicks.strategySelector.placeholder')}>{selectedOption?.name}</SelectValue>
                </SelectTrigger>
                <SelectContent className="bg-gray-800 border-gray-700">
                    {options.map((strategy) => (
                        <SelectItem 
                            key={strategy.id} 
                            value={strategy.id}
                            className="text-gray-300 hover:bg-gray-700"
                        >
                            <div className="flex flex-col">
                                <span className="font-medium">
                                    {strategy.name}
                                    {!strategy.available && (
                                        <span className="ml-2 text-[10px] font-normal uppercase tracking-wide text-amber-400">
                                            {t('propicks.strategySelector.noData')}
                                        </span>
                                    )}
                                </span>
                                <span className="text-xs text-gray-500">{strategy.description}</span>
                            </div>
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
        </div>
    );
}

