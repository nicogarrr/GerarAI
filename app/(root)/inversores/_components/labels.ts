/** "1 nueva" / "2 nuevas": concordancia de la etiqueta de posiciones nuevas. Sin imports: se testea en node. */
export function newLabel(count: number, locale: 'es' | 'en' = 'es'): string {
    if (locale === 'en') return `${count.toLocaleString('en-US', { maximumFractionDigits: 0 })} new`;
    const text = count.toLocaleString('es-ES', { maximumFractionDigits: 0 });
    return `${text} ${count === 1 ? 'nueva' : 'nuevas'}`;
}
