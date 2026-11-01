// Monograma propio: la G de GerarAI construida con un arco y la barra
// ascendente de una gráfica. Antes era un icono lucide de stock
// (ChartNoAxesCombined): idéntico al de mil webs más (rediseño 1-nov-2026).
export function GerarAIMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true" fill="none">
      <g stroke="currentColor" strokeWidth="3.2" strokeLinecap="round">
        <path d="M17.39 18.89A8.75 8.75 0 1 1 17.37 5.11" />
        <path d="M12.4 12H18.8V14.3" strokeLinejoin="round" />
      </g>
    </svg>
  );
}

export function GerarAIWordmark({ compact = false }: { compact?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2" aria-label="GerarAI">
      <span className="grid h-9 w-9 place-items-center rounded-xl border border-teal-300/30 bg-teal-400/10 text-teal-300">
        <GerarAIMark className="h-5 w-5" />
      </span>
      {!compact && (
        <span className="text-xl font-semibold tracking-tight text-white">
          Gerar<span className="text-teal-300">AI</span>
        </span>
      )}
    </span>
  );
}
