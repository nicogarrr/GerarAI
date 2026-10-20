/**
 * Ventana del gráfico de NAV de cartera. La ventana se elige por FECHAS (las
 * últimas N fechas del periodo) y solo DESPUÉS se omiten los puntos sin NAV:
 * filtrar antes de cortar colaba datos fuera de la ventana (p. ej. con
 * dates=[2025-12-30..2026-01-02] y un hueco, YTD=2 llegaba a pintar el 31 de
 * diciembre). Un punto sin NAV se omite, jamás se dibuja como 0.
 */
export type NavPoint = { date: string; value: number };

export function windowNav(dates: string[], nav: (number | null)[], period: string): NavPoint[] {
    if (!dates.length) return [];
    const latestDate = new Date(`${dates.at(-1)}T00:00:00`);
    const yearStart = new Date(latestDate.getFullYear(), 0, 1);
    const ytdPoints = Math.max(1, dates.filter((date) => new Date(`${date}T00:00:00`) >= yearStart).length);
    const maxPoints: Record<string, number> = {
        '1S': 7,
        '1M': 30,
        '3M': 90,
        '6M': 180,
        'YTD': ytdPoints,
        '1A': 365,
        'Todo': dates.length,
    };
    const size = Math.min(dates.length, maxPoints[period] ?? 30);
    const start = dates.length - size;
    return dates.slice(start).flatMap((date, offset) => {
        const value = nav[start + offset];
        return value == null ? [] : [{ date, value }];
    });
}
