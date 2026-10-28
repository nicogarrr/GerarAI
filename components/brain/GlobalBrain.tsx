'use client';

import dynamic from 'next/dynamic';
import { useEffect, useRef, useState } from 'react';
import { usePathname } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { BrainGlassesIcon } from '@/components/brain/BrainGlassesIcon';
import { brainStorageKey, restoreConversation, serializeConversation } from '@/lib/brain/conversation';
import { markBrainReady, OPEN_BRAIN_PENDING_KEY, type OpenBrainDetail, knowledgeHandoff, type KnowledgeBrainContext } from '@/lib/brain/open-brain';
import type { BrainMessage } from './GlobalBrainPanel';

// El panel del cerebro (chat, guía, biblioteca: ~16 KB gz con sus dependencias)
// solo hace falta al abrirlo. Importado estático viajaba en el layout
// autenticado, es decir, en la carga inicial de TODAS las páginas, aunque el
// panel esté cerrado. El gatillo queda eager aquí; el panel carga diferido y
// se precarga al rozar el gatillo (pointerdown/focus) o al llegar una apertura
// por evento/handoff.
const loadBrainPanel = () => import('./GlobalBrainPanel');
const GlobalBrainPanel = dynamic(() => loadBrainPanel().then((mod) => mod.GlobalBrainPanel), {
    loading: () => (
        <div
            role="status"
            aria-label="Cargando el cerebro"
            className="fixed z-50 inset-x-2 bottom-[calc(7rem+env(safe-area-inset-bottom))] top-20 rounded-lg border border-indigo-500/30 bg-slate-950/95 p-4 md:inset-x-auto md:top-0 md:bottom-0 md:right-0 md:w-[420px] md:h-dvh md:rounded-none"
        >
            <span className="block h-4 w-1/2 animate-pulse rounded bg-slate-700/60" aria-hidden="true" />
        </div>
    ),
});

const GREETING: BrainMessage = { role: 'assistant', content: '¡Hola! Soy el cerebro de GerarAI. Pregúntame sobre tu cartera, tus tesis de inversión o lo que estés viendo.' };

interface GlobalBrainProps {
    userId: string;
}

/**
 * Shell del cerebro global de GerarAI, montado UNA vez en el layout
 * autenticado: mantiene el gatillo (botón fijo que nunca tapa la BottomNav),
 * los oyentes de apertura (evento gerarai:open-brain, handoff pendiente en
 * sessionStorage, slot incrustado de la biblioteca) y el estado de la
 * conversación, para que cerrar y reabrir no la pierda aunque el panel se
 * desmonte. El panel pesado vive en GlobalBrainPanel (chunk diferido).
 */
export function GlobalBrain({ userId }: GlobalBrainProps) {
    const pathname = usePathname();
    const [isOpen, setIsOpen] = useState(false);
    // Pista de apertura: la etiqueta "Pregunta al Cerebro" se ve unos
    // segundos al cargar y se pliega sola (vuelve con hover/foco). Sin ella
    // el botón flotante era un cerebro suelto que nadie tocaba (Tester Nico).
    const [showHint, setShowHint] = useState(true);
    const [knowledge, setKnowledge] = useState<KnowledgeBrainContext | null>(null);
    const [librarySlot, setLibrarySlot] = useState<HTMLElement | null>(null);
    // La conversación se conserva al navegar y al cerrar el panel: se restaura
    // al montar (solo cliente, así el SSR siempre pinta el saludo y no hay
    // desajuste de hidratación) y se guarda recortada tras cada cambio.
    const restoredRef = useRef(false);
    const [messages, setMessages] = useState<BrainMessage[]>([GREETING]);
    // Handoffs de apertura con el panel desmontado: el contador obliga al
    // panel a aplicar cada apertura aunque llegue con el mismo detalle.
    const openSeqRef = useRef(0);
    const [openDetail, setOpenDetail] = useState<{ detail: OpenBrainDetail | null; seq: number } | null>(null);

    useEffect(() => {
        const t = setTimeout(() => setShowHint(false), 4000);
        return () => clearTimeout(t);
    }, []);

    // The page owns only a slot. This layout instance keeps the transcript
    // when moving between embedded doctrine and the floating panel elsewhere.
    useEffect(() => {
        let current: HTMLElement | null = null;
        const sync = () => {
            const slot = document.getElementById('brain-library-slot');
            if (slot === current) return;
            current = slot;
            setLibrarySlot(slot);
            if (slot) {
                let authors: string[] = [];
                try { authors = JSON.parse(slot.dataset.authors ?? '[]'); } catch { /* empty filter */ }
                // knowledgeHandoff sanea el contexto (documentId numérico,
                // título y autores acotados) antes de fijarlo.
                setKnowledge(knowledgeHandoff({ knowledge: { scope: slot.dataset.scope === 'letters' ? 'letters' : 'library', authors, documentId: Number(slot.dataset.documentId), documentTitle: slot.dataset.documentTitle } }));
                void loadBrainPanel();
            } else { setKnowledge(null); setIsOpen(false); }
        };
        queueMicrotask(sync);
        const observer = new MutationObserver(sync);
        observer.observe(document.body, { childList: true, subtree: true });
        return () => observer.disconnect();
    }, [pathname]);

    function openWithDetail(detail?: OpenBrainDetail | null) {
        setIsOpen(true);
        setKnowledge(knowledgeHandoff(detail));
        openSeqRef.current += 1;
        setOpenDetail({ detail: detail ?? null, seq: openSeqRef.current });
        void loadBrainPanel();
    }

    useEffect(() => {
        const openFromNavigation = (event: Event) => {
            openWithDetail((event as CustomEvent<OpenBrainDetail>).detail);
        };
        window.addEventListener('gerarai:open-brain', openFromNavigation);
        markBrainReady(true);
        return () => {
            markBrainReady(false);
            window.removeEventListener('gerarai:open-brain', openFromNavigation);
        };
    }, []);

    // Handoff sin carrera: la página-redirect del antiguo /research/assistant
    // escribe el detalle ANTES de navegar y aquí se recoge ya montado (también
    // en la carga directa, donde los efectos hijos corren antes que este).
    useEffect(() => {
        let pending: OpenBrainDetail | null = null;
        try {
            const raw = window.sessionStorage.getItem(OPEN_BRAIN_PENDING_KEY);
            if (raw) {
                window.sessionStorage.removeItem(OPEN_BRAIN_PENDING_KEY);
                pending = JSON.parse(raw) as OpenBrainDetail;
            }
        } catch {
            pending = null;
        }
        // Handoff desde un almacén externo (sessionStorage) tras montar o
        // cambiar de ruta: el setState no puede ser síncrono en el efecto.
        if (pending) {
            const detail = pending;
            queueMicrotask(() => openWithDetail(detail));
        }
    }, [pathname]);

    useEffect(() => {
        try {
            const stored = restoreConversation(window.sessionStorage.getItem(brainStorageKey(userId)));
            // Restauración desde sessionStorage tras montar: setState
            // diferido, no síncrono dentro del efecto.
            if (stored) queueMicrotask(() => setMessages(stored as BrainMessage[]));
        } catch {
            // sessionStorage no disponible: el panel funciona sin persistencia.
        } finally {
            restoredRef.current = true;
        }
    }, [userId]);

    useEffect(() => {
        if (!restoredRef.current) return;
        try {
            // Las respuestas de guía se guardan solo como texto: el payload
            // estructurado (secciones y citas tipadas) no viaja a sessionStorage.
            window.sessionStorage.setItem(brainStorageKey(userId), serializeConversation(
                messages.map((m) => ({ role: m.role, content: m.content, ...(m.citations ? { citations: m.citations } : {}) })),
            ));
        } catch {
            // Cuota llena o almacenamiento bloqueado: no pasa nada, se sigue sin persistir.
        }
    }, [messages, userId]);

    if (isOpen || librarySlot) {
        return (
            <GlobalBrainPanel
                userId={userId}
                knowledge={knowledge}
                librarySlot={librarySlot}
                openDetail={openDetail}
                messages={messages}
                setMessages={setMessages}
                onClose={() => setIsOpen(false)}
                onClearKnowledge={() => setKnowledge(null)}
            />
        );
    }

    // Burbuja fija: en móvil queda POR ENCIMA de la BottomNav (min-h-14 +
    // safe-area), nunca la tapa; en escritorio vuelve a la esquina habitual.
    // `viewportFit: "cover"` + barra de inicio de iOS: sin el inset la
    // burbuja queda bajo la barra en modo standalone.
    return (
        <div className="group fixed bottom-[calc(1.5rem+env(safe-area-inset-bottom))] right-[calc(1.5rem+env(safe-area-inset-right))] z-50 hidden items-center gap-2 md:flex">
            <span
                aria-hidden="true"
                className={`whitespace-nowrap rounded-full border border-indigo-500/30 bg-slate-950/90 px-3 py-1 text-xs text-indigo-200 shadow-lg motion-safe:transition-all motion-safe:duration-500 ${showHint
                    ? 'translate-x-0 opacity-100'
                    : 'pointer-events-none translate-x-2 opacity-0'
                    } group-hover:pointer-events-auto group-hover:translate-x-0 group-hover:opacity-100 group-focus-within:pointer-events-auto group-focus-within:translate-x-0 group-focus-within:opacity-100`}
            >
                Pregunta al Cerebro
            </span>
            <Button
                onClick={() => setIsOpen(true)}
                onPointerDown={() => void loadBrainPanel()}
                onFocus={() => void loadBrainPanel()}
                aria-label="Abrir el cerebro"
                title="Pregunta al Cerebro"
                className="h-14 w-14 p-0 rounded-none shadow-none bg-transparent hover:bg-transparent text-white"
            >
                <BrainGlassesIcon className={`h-14 w-14 shrink-0 object-contain ${showHint ? 'brain-breathe' : ''}`} />
            </Button>
        </div>
    );
}
