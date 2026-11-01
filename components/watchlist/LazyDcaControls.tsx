'use client';

import dynamic from 'next/dynamic';
import { useT } from '@/lib/i18n/client';

// Frontera cliente para diferir las islas interactivas del panel DCA
// (evaluación manual y detalle de aciertos): el
// panel es contenido SSR al final de /watchlist, pero estos controles solo
// hacen falta al interactuar. dynamic() dentro de un server component no
// saca el chunk del bundle inicial, así que los dynamic() viven aquí.
function ControlFallback() {
  const t = useT();
  return <span role="status" aria-label={t('watchlist.lazy.loading')} className="inline-block h-8 w-24 animate-pulse rounded-md border border-gray-800 bg-gray-900/40" />;
}

export const LazyDcaEvaluateButton = dynamic(() => import('@/components/watchlist/DcaEvaluateButton'), { loading: () => <ControlFallback /> });
export const LazyDcaHitRatesPopover = dynamic(() => import('@/components/watchlist/DcaHitRatesPopover'), { loading: () => <ControlFallback /> });
