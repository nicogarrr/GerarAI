"use client"

import dynamic from 'next/dynamic';
import { useEffect, useId, useRef, useSyncExternalStore } from "react"
import { Search } from "lucide-react";
import {
    subscribeSearchCommand,
    getSearchCommandSnapshot,
    registerSearchCommandInstance,
    ensureSearchCommandShortcutListener,
    openSearchCommand,
} from "@/lib/search/search-command-store";

// La paleta (cmdk + Finnhub, ~42 KB gzip) solo se descarga al abrir el
// buscador: antes viajaba en el bundle inicial de TODAS las páginas
// autenticadas porque Header la importaba en estático. El gatillo, el atajo
// Ctrl+K y el owner único (lib/search/search-command-store) se quedan aquí,
// eager, para que el atajo funcione desde el primer pintado. Se precarga al
// pulsar (pointerdown llega antes que click), así la primera apertura no
// nota la descarga.
const SearchCommandDialog = dynamic(() => import('@/components/SearchCommandDialog'), {
    loading: () => null,
});
const preloadDialog = () => void import('@/components/SearchCommandDialog');

export default function SearchCommand({ renderAs = 'button', label = 'Añadir acción', initialStocks }: SearchCommandProps) {
    // Guard de hidratación sin efecto: false en SSR y en el primer render
    // del cliente, true tras hidratar (useSyncExternalStore).
    const mounted = useSyncExternalStore(
        () => () => {},
        () => true,
        () => false,
    );
    const triggerRef = useRef<HTMLButtonElement | null>(null);
    const returnFocusRef = useRef<HTMLElement | null>(null);

    // Owner único (lib/search/search-command-store): el estado open/ownerId
    // es compartido; solo la instancia dueña monta el CommandDialog, así que
    // Ctrl+K ya no abre varios diálogos apilados (desktop + icono + drawer).
    const instanceId = useId();
    const { open: storeOpen, ownerId } = useSyncExternalStore(
        subscribeSearchCommand,
        getSearchCommandSnapshot,
        getSearchCommandSnapshot,
    );
    const isDialogOpen = storeOpen && ownerId === instanceId;

    useEffect(() => {
        ensureSearchCommandShortcutListener();
        return registerSearchCommandInstance({
            id: instanceId,
            isTriggerVisible: () => {
                const el = triggerRef.current;
                return !!el && el.getClientRects().length > 0;
            },
            captureReturnFocus: () => {
                returnFocusRef.current = document.activeElement instanceof HTMLElement && document.activeElement !== document.body
                    ? document.activeElement : triggerRef.current;
            },
        });
    }, [instanceId]);

    const openSearch = () => {
        preloadDialog();
        openSearchCommand(instanceId);
    };

    const getFocusTarget = () =>
        returnFocusRef.current?.isConnected ? returnFocusRef.current : triggerRef.current;

    // Evitar hydration mismatch: el fallback pre-hidratado debe ser
    // visualmente IDENTICO al boton hidratado (input sutil), no una pildora
    // primaria con el label crudo. Sin onClick hasta montar.
    if (!mounted) {
        if (renderAs === 'icon') {
            return (
                <button type="button" tabIndex={-1} aria-hidden="true"
                    className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg p-2 text-gray-300">
                    <Search aria-hidden="true" className="h-5 w-5" />
                </button>
            );
        }
        if (renderAs === 'text') {
            return <button type="button" tabIndex={-1} aria-hidden="true" className="search-text">{label}</button>;
        }
        return (
            <button
                type="button"
                tabIndex={-1}
                aria-hidden="true"
                className="flex min-h-11 w-full items-center gap-2 rounded-lg border border-gray-700 bg-gray-800/60 px-4 py-2.5 text-sm text-gray-400 backdrop-blur-sm"
            >
                <Search aria-hidden="true" className="h-4 w-4 text-gray-500" />
                <span className="flex-1 text-left">Buscar acciones...</span>
                <kbd className="hidden items-center gap-1 rounded border border-gray-600 bg-gray-900/50 px-2 py-0.5 text-xs text-gray-500 sm:inline-flex">
                    Ctrl+K
                </kbd>
            </button>
        );
    }

    return (
        <>
            {renderAs === 'text' ? (
                <button
                    type="button"
                    ref={triggerRef}
                    onClick={openSearch}
                    onPointerDown={preloadDialog}
                    className="search-text"
                    data-testid="search-command-trigger"
                >
                    {label}
                </button>
            ) : renderAs === 'icon' ? (
                <button
                    type="button"
                    ref={triggerRef}
                    onClick={openSearch}
                    onPointerDown={preloadDialog}
                    aria-label="Abrir buscador"
                    data-testid="search-command-trigger"
                    className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg p-2 text-gray-300 transition-colors hover:bg-gray-700/50 hover:text-white"
                >
                    <Search aria-hidden="true" className="h-5 w-5" />
                </button>
            ) : (
                <button
                    type="button"
                    ref={triggerRef}
                    onClick={openSearch}
                    onPointerDown={preloadDialog}
                    onFocus={preloadDialog}
                    className="flex min-h-11 w-full items-center gap-2 rounded-lg border border-gray-700 bg-gray-800/60 px-4 py-2.5 text-sm text-gray-400 backdrop-blur-sm transition-all duration-200 hover:bg-gray-700/60"
                    data-testid="search-command-trigger"
                >
                    <Search aria-hidden="true" className="h-4 w-4 text-gray-500" />
                    <span className="flex-1 text-left">Buscar acciones...</span>
                    <kbd className="hidden items-center gap-1 rounded border border-gray-600 bg-gray-900/50 px-2 py-0.5 text-xs text-gray-500 sm:inline-flex">
                        Ctrl+K
                    </kbd>
                </button>
            )}
            {/* Owner sticky: tras cerrar, la misma instancia sigue montando el
                diálogo (cerrado) para que Radix complete animación y
                devolución de foco. */}
            {ownerId === instanceId && (
                <SearchCommandDialog open={isDialogOpen} initialStocks={initialStocks} getFocusTarget={getFocusTarget} />
            )}
        </>
    )
}
