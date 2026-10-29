import type { ResearchFact } from '@/lib/actions/research.actions';

/** A filing source does not make a derived value a reported value. */
export function FactCalculatedLabel({ fact }: { fact: Pick<ResearchFact, 'is_reported'> }) {
  return fact.is_reported === false
    ? <span className="ml-2 text-xs text-amber-300">Calculado</span>
    : null;
}
