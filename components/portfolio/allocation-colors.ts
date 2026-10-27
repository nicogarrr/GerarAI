// Paleta del donut de distribución. Vive fuera de PortfolioAllocationChart
// para que el panel (PortfolioAllocation) pueda colorear la leyenda sin
// importar el módulo del gráfico: cualquier import estático de ese módulo
// arrastra recharts (~365 kB sin comprimir) a la carga inicial de /portfolio
// y anula el dynamic(..., { ssr: false }).
export const COLORS = [
    '#14b8a6', // teal-500
    '#8b5cf6', // violet-500
    '#f59e0b', // amber-500
    '#ef4444', // red-500
    '#3b82f6', // blue-500
    '#ec4899', // pink-500
    '#22c55e', // green-500
    '#f97316', // orange-500
    '#06b6d4', // cyan-500
    '#a855f7', // purple-500
    '#eab308', // yellow-500
    '#6366f1', // indigo-500
];
