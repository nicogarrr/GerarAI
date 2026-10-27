/**
 * Ventana del gráfico de NAV de cartera. La ventana se elige por FECHAS (las
 * últimas N fechas del periodo) y solo DESPUÉS se omiten los puntos sin NAV:
 * filtrar antes de cortar colaba datos fuera de la ventana (p. ej. con
 * dates=[2025-12-30..2026-01-02] y un hueco, YTD=2 llegaba a pintar el 31 de
 * diciembre). Un punto sin NAV se omite, jamás se dibuja como 0.
 *
 * Las ventanas son de CALENDARIO (1S = últimos 7 días, 1M = 30, 3M = 90,
 * 6M = 180, 1A = 365, contando el último día), no un número de puntos: las
 * fotos de cartera no son diarias garantizadas (solo días con refresco, sin
 * fines de semana), y «los últimos 30 puntos» podía pintar meses bajo «1M».
 * Con una serie diaria sin huecos el resultado es el mismo que antes.
 */
export type NavPoint = { date: string; value: number };

export function windowNav(dates: string[], nav: (number | null)[], period: string): NavPoint[] {
    if (!dates.length) return [];
    const dayMs = (date: string) => Date.parse(`${date}T00:00:00Z`);
    const latestMs = dayMs(dates.at(-1) as string);
    const latestYear = new Date(latestMs).getUTCFullYear();
    const windowDays: Record<string, number> = { '1S': 7, '1M': 30, '3M': 90, '6M': 180, '1A': 365 };
    const inWindow = (date: string): boolean => {
        if (period === 'Todo') return true;
        if (period === 'YTD') return new Date(dayMs(date)).getUTCFullYear() === latestYear;
        const days = windowDays[period] ?? 30;
        return (latestMs - dayMs(date)) / 86_400_000 < days;
    };
    // Las fechas llegan ordenadas: la ventana es el sufijo que cae dentro.
    let start = dates.length - 1;
    while (start > 0 && inWindow(dates[start - 1])) start -= 1;
    return dates.slice(start).flatMap((date, offset) => {
        const value = nav[start + offset];
        return value == null ? [] : [{ date, value }];
    });
}
