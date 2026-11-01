import type { Locale } from '@/lib/i18n/locale';
import type { TranslateFn } from '@/lib/i18n/translate';

/**
 * Nombre y descripción de las 4 estrategias públicas en el idioma elegido.
 * En español se pinta lo que llega (servidor o catálogo), sin tocarlo; en
 * inglés se usa el texto del diccionario por id. Claves literales para que
 * check:i18n las cuente.
 */
const STRATEGY_KEYS = {
    adaptive: { name: 'propicks.strategies.adaptive.name', description: 'propicks.strategies.adaptive.description' },
    value: { name: 'propicks.strategies.value.name', description: 'propicks.strategies.value.description' },
    momentum: { name: 'propicks.strategies.momentum.name', description: 'propicks.strategies.momentum.description' },
    defensiva: { name: 'propicks.strategies.defensiva.name', description: 'propicks.strategies.defensiva.description' },
} as const;

export function localizeStrategy<T extends { id: string; name: string; description: string }>(
    strategy: T,
    locale: Locale,
    t: TranslateFn,
): T {
    if (locale !== 'en') return strategy;
    const keys = STRATEGY_KEYS[strategy.id as keyof typeof STRATEGY_KEYS];
    return keys ? { ...strategy, name: t(keys.name), description: t(keys.description) } : strategy;
}
