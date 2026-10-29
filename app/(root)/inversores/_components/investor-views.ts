// Módulo sin 'use client': lo usan la página (servidor) y el selector (cliente).
// Exportarlo desde InvestorViewSelector.tsx lo convertía en referencia de
// cliente y la página de servidor fallaba con 500 (#2971).
export const VIEWS = [
    { id: 'posiciones', label: 'Cartera' },
    { id: 'distribucion', label: 'Distribución' },
    { id: 'cambios', label: 'Últimos movimientos' },
    { id: 'cartas', label: 'Cartas' },
    { id: 'videos', label: 'Vídeos' },
] as const;

export type InvestorViewId = (typeof VIEWS)[number]['id'];
