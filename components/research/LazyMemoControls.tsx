'use client';

import dynamic from 'next/dynamic';

// Frontera cliente para diferir las islas interactivas del memorando de
// tesis: dynamic() dentro de un componente de servidor no saca el chunk del
// bundle inicial (el SSR lo necesita para hidratar), así que los dynamic()
// viven aquí y ThesisMemo (server) consume estas versiones perezosas.
const memoSectionFallback = () => (
  <div role="status" aria-label="Cargando la sección" className="rounded-lg border border-gray-800 bg-gray-900/40 p-4">
    <span className="block h-4 w-1/3 animate-pulse rounded bg-gray-700/60" aria-hidden="true" />
  </div>
);

export const LazyThesisHumanInputForm = dynamic(() => import('@/components/research/ThesisHumanInputForm'), { loading: memoSectionFallback });
export const LazyThesisInvalidationRulesForm = dynamic(() => import('@/components/research/ThesisInvalidationRulesForm'), { loading: memoSectionFallback });
export const LazyThesisDebatePanel = dynamic(() => import('@/components/research/ThesisDebatePanel'), { loading: memoSectionFallback });
