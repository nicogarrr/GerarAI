'use client';

import { createContext, useContext, useState, type ReactNode } from 'react';

const Membership = createContext({ removed: new Set<string>(), confirmRemoval: (_symbol: string) => {} });
const normalize = (symbol: string) => symbol.trim().toUpperCase();

/** Confirmed DELETEs stay hidden while the server refresh is still in flight. */
export function WatchlistMembership({ children }: { children: ReactNode }) {
    const [removed, setRemoved] = useState<Set<string>>(() => new Set());
    return <Membership.Provider value={{ removed, confirmRemoval: (symbol) => setRemoved((current) => new Set(current).add(normalize(symbol))) }}>{children}</Membership.Provider>;
}

export function useConfirmWatchlistRemoval() {
    return useContext(Membership).confirmRemoval;
}

export function WatchlistEntry({ symbol, as: Tag, children, className }: { symbol: string; as: 'article' | 'tr'; children: ReactNode; className?: string }) {
    const { removed } = useContext(Membership);
    return removed.has(normalize(symbol)) ? null : <Tag data-slot={Tag === 'tr' ? 'table-row' : undefined} className={className}>{children}</Tag>;
}

export function WatchlistCount({ symbols, page, totalPages }: { symbols: string[]; page: number; totalPages: number }) {
    const { removed } = useContext(Membership);
    const count = symbols.filter((symbol) => !removed.has(normalize(symbol))).length;
    return <span aria-live="polite">{count} {count === 1 ? 'empresa' : 'empresas'} · <span className="whitespace-nowrap">Página {page} de {totalPages}</span></span>;
}
