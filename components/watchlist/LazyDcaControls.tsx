'use client';

import dynamic from 'next/dynamic';

// Frontera cliente para diferir las islas interactivas del panel DCA
// (evaluación manual, detalle de aciertos y aviso mínimo por símbolo): el
// panel es contenido SSR al final de /watchlist, pero estos controles solo
// hacen falta al interactuar. dynamic() dentro de un server component no
// saca el chunk del bundle inicial, así que los dynamic() viven aquí.
const controlFallback = () => (
  <span role="status" aria-label="Cargando el control" className="inline-block h-8 w-24 animate-pulse rounded-md border border-gray-800 bg-gray-900/40" />
);

export const LazyDcaEvaluateButton = dynamic(() => import('@/components/watchlist/DcaEvaluateButton'), { loading: controlFallback });
export const LazyDcaHitRatesPopover = dynamic(() => import('@/components/watchlist/DcaHitRatesPopover'), { loading: controlFallback });
export const LazyDcaMinLevelSelect = dynamic(() => import('@/components/watchlist/DcaMinLevelSelect'), { loading: controlFallback });
